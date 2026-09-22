"""`gemini-3.5-transcribe-live` kao izvor transkripcije, preko Live API-ja.

Zašto baš Live varijanta, a ne obična: besplatne kvote (AI Studio → Rate Limit,
28.08.2026) su `gemini-3.5-transcribe` **3 u minuti / 25 dnevno**, a
`gemini-3.5-transcribe-live` **bez granice** (20K tokena u minuti, što je oko
800s zvuka — diktat to ne dostiže). Dvadeset pet dnevno ne znači ništa za
svakodnevni rad, pa obična varijanta nije ni ostala u aplikaciji.

Zvuk se šalje tokom snimanja. Opcioni živi režim čita rezultate paralelno;
potvrđene celine može da upisuje u aktivno polje pre završetka snimanja.

Prednost nad besplatnim Web Speech endpointom: prima do sat vremena po zahtevu
(Web Speech ~30s), podržava `sr-RS`, i dobija `vocabulary` kao biasovanje —
a baš na skraćenicama i stranim nazivima Web Speech najviše greši.

Ključ je isti `polish_api_key` iz AI Studio — ne pravi se drugi ključ za istu
uslugu.
"""

import base64
import json
import threading
import time
import urllib.error
import urllib.request

from . import abbrev, webstt
from . import openai as openai_mod
from .wsock import WebSocket, WebSocketError, WebSocketTimeout

WS_ENDPOINT = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)

LIVE_MODEL = "gemini-3.5-transcribe-live"

USER_AGENT = "Diktat/1.0"
MIN_AUDIO_BYTES = 6400          # 0.2 s mono PCM-a na 16 kHz
MAX_VOCABULARY = 1000           # granica koju endpoint objavljuje
RETRY_WAIT = 1.0
MAX_RETRIES = 2
# Live API traži komade od ~100ms; veći komad kasni, manji troši okvire uzalud.
LIVE_CHUNK_MS = 100
# Rep tišine bez kog se POSLEDNJA izgovorena celina nikad ne finalizuje.
# Izmereno na snimku od 19s sa dve pauze: bez repa stignu 2 od 3 konačna
# prepisa, sa 2s tišine sva 3. Zvuk se šalje punom brzinom — slanje u realnom
# tempu daje isti rezultat, a traje 28.7s umesto 11.5s.
LIVE_TAIL_SILENCE = 2.0
# Posle zvuka server ne zatvara vezu: šalje prazne poruke dok radi, pa stane.
# Tišina je zato jedini znak da je gotov — i to je JEDINO što se još čeka:
# izmereno, poslednji prepis stigne 0.5s posle Stop-a bez obzira na dužinu
# diktata, pa je sve preko toga bila naša tempirana pauza.
#
# Dve strpljivosti, jer nisu isti slučajevi:
#   `IDLE`  — celina je započeta a nije finalizovana; prekid bi je odsekao,
#             pa se čeka dugo (razmaci dok server radi idu do ~1.4s).
#   `QUIET` — poslednja celina je finalizovana i ništa novo nije počelo;
#             tada tišina stvarno znači kraj i nema šta da se izgubi.
# Izmereno (strim, snimci koji staju usred govora, 8.5s i 26.6s): ni na 0.8s se
# ne izgubi nijedna celina — server je stigao dok se šalje rep. Ukupno čekanje
# posle Stop-a pada sa 3.5s na 1.5s. Rizičan slučaj (celina u letu) pokriva
# `IDLE`, pa `QUIET` sme da bude kratak.
#
# Najveći razmak između poruka posle Stop-a je 0.47s u strim režimu (u batch
# režimu je 1.4s, jer server tamo pacira sam sebe kroz nagomilan zvuk) — 1.0s
# je dakle dvostruka rezerva. Tok se uvek završava istim obrascem:
# `… FINAL → generationComplete → prazno →` tišina. `turnComplete` NE postoji,
# pa čistog signala za kraj nema; tišina je jedino što ga označava.
LIVE_IDLE_SECONDS = 3.0
LIVE_QUIET_SECONDS = 1.0
# Dok ne stigne NIJEDNA poruka sa prepisom, sekunda tisine jos ne znaci kraj:
# LIVE_QUIET_SECONDS je mereno za tisinu POSLE poslednje celine. Na snimak bez
# govora server ne vrati nista ni za 10 s (izmereno 22.09.2026. na tri takva),
# pa se tada ceka ovoliko i odustaje; da li je bilo govora presudjuje app.py.
LIVE_FIRST_SECONDS = 4.0


class GeminiSttError(Exception):
    """Greška poziva; `retryable` znači da drugi pokušaj ima smisla."""

    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


def enabled(cfg) -> bool:
    """Da li je Gemini Transcribe Live izabran kao izvor transkripcije."""
    return provider(cfg) == "gemini_live"


def provider(cfg) -> str:
    return str(cfg.get("transcription_provider", "google")).lower()


def model_for(_cfg=None) -> str:
    return LIVE_MODEL


def _key(cfg) -> str:
    key = (cfg.get("polish_api_key") or "").strip()
    if not key:
        raise GeminiSttError(
            "Gemini API ključ nije podešen (AI → API ključevi).", retryable=False
        )
    return key


def vocabulary(cfg) -> list[str]:
    """Pojmovi na kojima prepoznavanje inače greši — isti spisak koji ide i
    modelu uz snimak. Prazni i dupli se izbacuju, poslednji red pobeđuje."""
    sirovo = str(cfg.get("vocabulary") or "")
    pojmovi = []
    for deo in sirovo.replace("\n", ",").split(","):
        deo = deo.strip()
        if deo and deo not in pojmovi:
            pojmovi.append(deo)
    return pojmovi[:MAX_VOCABULARY]


def _language_codes(cfg) -> list[str]:
    """Nagovestaj jezika; prazno podesavanje pada na podrazumevani `sr-RS`.

    Prazan spisak bi znacio „sam prepoznaj jezik", sto je ovde losije: diktat je
    na srpskom, a bez nagovestaja model ume da odluta na hrvatski ili bosanski.
    """
    return [str(cfg.get("language") or "sr-RS").strip() or "sr-RS"]


def post_process(text: str, cfg) -> str:
    """Ista lokalna pravila kao za OpenAI: model vraća sređen tekst, pa se
    interpunkcija i velika slova diraju samo ako podešavanja to traže."""
    text = (text or "").strip()
    if not text:
        return text
    # Endpoint za `sr-RS` vraća ćirilicu, i to nedosledno — izmereno u istom
    # diktatu i „тест тест" i „Test test". Projekat je latinični (Android isto),
    # pa se pismo poravnava pre svega ostalog.
    text = openai_mod.to_latin(text)
    text = webstt.join_thousands(text)
    if cfg.get("strip_punctuation", True):
        text = "\n".join(webstt.strip_punctuation(red) for red in text.split("\n"))
    if cfg.get("lowercase", True):
        text = text.lower()
    else:
        text = webstt.capitalize_sentences(text)
    if cfg.get("abbreviations", True):
        rules = abbrev.parse(cfg.get("abbreviation_rules") or abbrev.default_text())
        text = abbrev.apply(text, rules)
    if cfg.get("ascii_diacritics", False):
        text = webstt.to_ascii(text)
    return text


# ---------------------------------------------------------------- Live (WSS)

def _live_setup(cfg) -> dict:
    return {"setup": {
        "model": f"models/{LIVE_MODEL}",
        "generationConfig": {"responseModalities": ["TEXT"]},
        "inputAudioTranscription": {"languageCodes": _language_codes(cfg)},
    }}


def _live_text(poruka: dict) -> str:
    """KONAČAN prepis jedne izgovorene celine, ili prazno.

    Endpoint polje zove i `inputTranscription` i `input_transcription` — zavisi
    od verzije, pa se gleda oboje.
    """
    sadrzaj = poruka.get("serverContent") or poruka.get("server_content") or {}
    for ime in ("inputTranscription", "input_transcription"):
        deo = sadrzaj.get(ime)
        if isinstance(deo, dict) and deo.get("text"):
            return deo["text"]
    return ""


def _live_interim(poruka: dict) -> str:
    """Međurezultat — koristi se SAMO ako celina nikad ne dobije konačan prepis.

    Endpoint ume da ostavi poslednju celinu nedovršenu; tada je pola prepisa
    bolje nego ništa. Inače se međurezultati preskaču, jer bi udvojili reči.
    """
    sadrzaj = poruka.get("serverContent") or poruka.get("server_content") or {}
    for ime in ("interimInputTranscription", "interim_input_transcription"):
        deo = sadrzaj.get(ime)
        if isinstance(deo, dict) and deo.get("text"):
            return deo["text"]
    return ""


def _zatvoreno(ws) -> str:
    """Razlog iz CLOSE okvira; bez njega otkaz izgleda kao nasumičan prekid."""
    if ws.close_reason:
        return f"Gemini Transcribe Live: {ws.close_reason}"
    if ws.close_code:
        return f"Gemini Transcribe Live: veza zatvorena ({ws.close_code})"
    return "Gemini Transcribe Live: veza zatvorena bez odgovora"


def _prolazno(ws) -> bool:
    """Pogrešan ključ i odbijen zahtev se ne ponavljaju; ostalo se ponavlja.

    1007 (neispravan podatak) nosi i „API key not valid" i pogrešan `setup` —
    oba su naša greška, drugi pokušaj bi dao isto.
    """
    if ws.close_code == 1007:
        return False
    return "api key" not in (ws.close_reason or "").lower()


def recognize_live(pcm: bytes, cfg, timeout=180) -> str:
    """Prepiši gotov snimak — zvuk se šalje odjednom, posle Stop-a."""
    return recognize_stream([pcm], cfg, timeout=timeout)


def recognize_stream(komadi, cfg, timeout=180, on_update=None,
                     on_final=None, on_interim=None) -> str:
    """Isto, ali zvuk stiže IZ GENERATORA — dok korisnik još priča.

    Ovo je jedini način da se ukloni čekanje na kraju. Izmereno na 64.7s zvuka:
    kad se sve pošalje posle Stop-a, čeka se **15.6s**; kad se šalje u toku
    snimanja, čeka se **0.0s** — server stiže u realnom vremenu, pa je prepis
    gotov u trenutku kad pustiš taster. Broj prepoznatih celina je isti (11).

    `komadi` je bilo koji iterator PCM komada; lista sa jednim elementom daje
    staro ponašanje, pa oba puta idu kroz isti kod.
    """
    key = _key(cfg)
    rate = int(cfg.get("sample_rate", 16000))
    # 16-bit mono: dva bajta po semplu, pa je komad od 100ms rate/10*2 bajtova.
    korak = max(2, (rate // 1000) * LIVE_CHUNK_MS * 2)
    delovi = []
    try:
        with WebSocket(f"{WS_ENDPOINT}?key={key}", timeout=timeout) as ws:
            ws.send_json(_live_setup(cfg))
            odgovor = ws.recv_json()
            if odgovor is None:
                raise GeminiSttError(_zatvoreno(ws), _prolazno(ws))
            if "setupComplete" not in odgovor and "setup_complete" not in odgovor:
                raise GeminiSttError(
                    f"Live API nije prihvatio podešavanje: {str(odgovor)[:200]}",
                    retryable=False,
                )
            def posalji(data):
                for i in range(0, len(data), korak):
                    ws.send_json({"realtimeInput": {"audio": {
                        "data": base64.b64encode(data[i:i + korak]).decode("ascii"),
                        "mimeType": f"audio/pcm;rate={rate}",
                    }}})

            if any(callback is not None for callback in (on_update, on_final, on_interim)):
                return _stream_with_preview(
                    ws, komadi, posalji, korak, rate, on_update, on_final, on_interim
                )

            # Ostatak koji nije pun komad nosi se u sledeći prolaz: komadi sa
            # mikrofona ne padaju na granicu od 100ms, a slanje krnjih okvira
            # razbija prepoznavanje po sredini reči.
            ostatak = b""
            for komad in komadi:
                if not komad:
                    continue
                ostatak += komad
                celi = len(ostatak) - (len(ostatak) % korak)
                if celi:
                    posalji(ostatak[:celi])
                    ostatak = ostatak[celi:]
            # Rep tišine: bez njega poslednja celina ostane na međurezultatu.
            posalji(ostatak + b"\x00" * (int(rate * LIVE_TAIL_SILENCE) * 2))
            ws.send_json({"realtimeInput": {"audioStreamEnd": True}})

            # Od sada tišina znači "gotov je", pa se čeka kratko.
            ws.set_timeout(LIVE_QUIET_SECONDS)
            posle_zadnjeg = ""
            produzeno = False
            ceka_prvi = False
            while True:
                try:
                    poruka = ws.recv_json()
                except WebSocketError:
                    if not delovi and not posle_zadnjeg and not ceka_prvi:
                        ceka_prvi = True
                        ws.set_timeout(LIVE_FIRST_SECONDS)
                        continue
                    if posle_zadnjeg and not produzeno:
                        # Celina je u toku: video se međurezultat bez svog
                        # finala. Prekid ovde bi je odsekao, pa joj se jednom
                        # da pun rok.
                        produzeno = True
                        ws.set_timeout(LIVE_IDLE_SECONDS)
                        continue
                    if delovi or posle_zadnjeg:
                        break            # utihnuo je — to je kraj, ne greška
                    raise
                if poruka is None:
                    if not delovi and ws.close_reason:
                        # Zatvaranje bez ijednog prepisa je otkaz, ne kraj.
                        raise GeminiSttError(_zatvoreno(ws), _prolazno(ws))
                    break
                if "error" in poruka:
                    raise GeminiSttError(
                        f"Live API: {str(poruka['error'])[:200]}", retryable=True
                    )
                tekst = _live_text(poruka)
                if tekst:
                    delovi.append(tekst)
                    posle_zadnjeg = ""
                    produzeno = False
                    ws.set_timeout(LIVE_QUIET_SECONDS)
                    continue
                # `generationComplete` stiže posle SVAKE izgovorene celine, ne
                # na kraju diktata — prekid na njemu bi odbacio sve posle prve
                # pauze. Izmereno na snimku sa dve pauze: stizao je tri puta.
                medju = _live_interim(poruka)
                if medju:
                    posle_zadnjeg = medju
            if posle_zadnjeg:
                delovi.append(posle_zadnjeg)
    except WebSocketError as exc:
        raise GeminiSttError(f"Gemini Transcribe Live: {exc}", exc.retryable) from exc
    return " ".join(deo.strip() for deo in delovi if deo.strip()).strip()


def _stream_with_preview(ws, komadi, posalji, korak, rate, on_update,
                         on_final, on_interim):
    """Čitaj Live odgovore paralelno sa slanjem zvuka za živi režim.

    Potvrđene celine se prosleđuju čim stignu. Međurezultat sme da se menja,
    pa se samo prikazuje i ne dodaje u `delovi` dok ne stigne konačna celina.
    Tako reči ne mogu da se dupliraju.
    """
    delovi = []
    stanje = {"interim": "", "error": None}
    poslato = threading.Event()
    procitano = threading.Event()
    ws.set_timeout(0.5)

    def prikazi():
        tekst = " ".join([*delovi, stanje["interim"]]).strip()
        pozovi(on_update, tekst)

    def pozovi(callback, tekst):
        if callback is not None:
            try:
                callback(tekst)
            except Exception:
                # Prikaz je dodatak; ne sme da obori niti izgubi prepis.
                pass

    def citaj():
        zadnja_poruka = time.monotonic()
        try:
            while True:
                try:
                    poruka = ws.recv_json()
                except WebSocketTimeout:
                    if not poslato.is_set():
                        continue
                    if not delovi and not stanje["interim"]:
                        rok = LIVE_FIRST_SECONDS
                    elif stanje["interim"]:
                        rok = LIVE_IDLE_SECONDS
                    else:
                        rok = LIVE_QUIET_SECONDS
                    if time.monotonic() - zadnja_poruka >= rok:
                        if delovi or stanje["interim"]:
                            break
                        raise GeminiSttError("Gemini Transcribe Live nije vratio prepis.", True)
                    continue
                if poruka is None:
                    if not delovi and not stanje["interim"] and ws.close_reason:
                        raise GeminiSttError(_zatvoreno(ws), _prolazno(ws))
                    break
                if "error" in poruka:
                    raise GeminiSttError(
                        f"Live API: {str(poruka['error'])[:200]}", retryable=True
                    )
                zadnja_poruka = time.monotonic()
                tekst = _live_text(poruka)
                if tekst:
                    delovi.append(tekst)
                    stanje["interim"] = ""
                    pozovi(on_final, tekst)
                    pozovi(on_interim, "")
                    prikazi()
                else:
                    medju = _live_interim(poruka)
                    if medju:
                        stanje["interim"] = medju
                        pozovi(on_interim, medju)
                        prikazi()
        except (GeminiSttError, WebSocketError) as exc:
            stanje["error"] = exc
        finally:
            procitano.set()

    reader = threading.Thread(target=citaj, name="gemini-live-preview", daemon=True)
    reader.start()
    ostatak = b""
    try:
        for komad in komadi:
            if stanje["error"] is not None:
                raise stanje["error"]
            if not komad:
                continue
            ostatak += komad
            celi = len(ostatak) - (len(ostatak) % korak)
            if celi:
                posalji(ostatak[:celi])
                ostatak = ostatak[celi:]
        posalji(ostatak + b"\x00" * (int(rate * LIVE_TAIL_SILENCE) * 2))
        ws.send_json({"realtimeInput": {"audioStreamEnd": True}})
        poslato.set()
        if not procitano.wait(LIVE_FIRST_SECONDS + LIVE_IDLE_SECONDS + 2):
            raise GeminiSttError("Gemini Transcribe Live nije završio odgovor.", True)
        if stanje["error"] is not None:
            raise stanje["error"]
        if stanje["interim"]:
            delovi.append(stanje["interim"])
            pozovi(on_final, stanje["interim"])
        return " ".join(deo.strip() for deo in delovi if deo.strip()).strip()
    finally:
        poslato.set()


# ------------------------------------------------------------------ zajedničko

def recognize(pcm: bytes, cfg, timeout=180) -> str:
    """Prepiši ceo snimljen diktat.

    Prolazne greške se ponavljaju jednom, kao i svuda u projektu; mrtav ključ i
    odbijeno rukovanje se ne ponavljaju — drugi pokušaj bi dao isto.
    """
    if not pcm:
        return ""
    if len(pcm) < MIN_AUDIO_BYTES:
        raise GeminiSttError("Snimak je prekratak za Gemini Transcribe.", False)
    return _sa_ponavljanjem(lambda: recognize_live(pcm, cfg, timeout=timeout))


def _sa_ponavljanjem(posao):
    poslednja = None
    for pokusaj in range(MAX_RETRIES):
        try:
            return posao()
        except GeminiSttError as exc:
            poslednja = exc
            if not exc.retryable or pokusaj == MAX_RETRIES - 1:
                raise
            time.sleep(RETRY_WAIT)
    raise poslednja


def recognize_live_stream(komadi, cfg, timeout=180, on_update=None,
                          on_final=None, on_interim=None) -> str:
    """Strimuj zvuk dok traje snimanje; vrati prepis kad snimanje stane.

    Bez ponavljanja: komadi stižu iz mikrofona i mogu se pročitati samo jednom,
    pa drugi pokušaj nema šta da pošalje. Otkaz ovde znači da diktat pada na
    sačuvan snimak, kao i svaki drugi neuspeo poziv.
    """
    return recognize_stream(
        komadi, cfg, timeout=timeout, on_update=on_update,
        on_final=on_final, on_interim=on_interim,
    )
