"""`gemini-3.5-transcribe-live` kao izvor transkripcije, preko Live API-ja.

Zašto baš Live varijanta, a ne obična: besplatne kvote (AI Studio → Rate Limit,
28.08.2026) su `gemini-3.5-transcribe` **3 u minuti / 25 dnevno**, a
`gemini-3.5-transcribe-live` **bez granice** (20K tokena u minuti, što je oko
800s zvuka — diktat to ne dostiže). Dvadeset pet dnevno ne znači ništa za
svakodnevni rad, pa obična varijanta nije ni ostala u aplikaciji.

**Obrada ide POSLE snimanja, ne u toku.** Cela sesija je jedan WebSocket poziv
nad gotovim snimkom: poveži se, pošalji zvuk, uzmi prepis, zatvori. Model tako
vidi ceo diktat umesto krhotina — isti razlog iz kog formalni režim zove model
jednom na kraju. „Live" je ovde ime modela, ne prikaz reč-po-reč; taj bi tražio
da se ceo tok snimanja preokrene u streaming.

Prednost nad besplatnim Web Speech endpointom: prima do sat vremena po zahtevu
(Web Speech ~30s), podržava `sr-RS`, i dobija `vocabulary` kao biasovanje —
a baš na skraćenicama i stranim nazivima Web Speech najviše greši.

Ključ je isti `polish_api_key` iz AI Studio — ne pravi se drugi ključ za istu
uslugu.
"""

import base64
import json
import time
import urllib.error
import urllib.request

from . import abbrev, webstt
from . import openai as openai_mod
from .wsock import WebSocket, WebSocketError

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
# Tišina je zato jedini znak da je gotov. Izmereni razmaci između poruka dok
# radi su do 0.9s, pa je 3s trostruka rezerva.
LIVE_IDLE_SECONDS = 3.0


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


def recognize_stream(komadi, cfg, timeout=180) -> str:
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
            ws.set_timeout(LIVE_IDLE_SECONDS)
            posle_zadnjeg = ""
            while True:
                try:
                    poruka = ws.recv_json()
                except WebSocketError as exc:
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


def recognize_live_stream(komadi, cfg, timeout=180) -> str:
    """Strimuj zvuk dok traje snimanje; vrati prepis kad snimanje stane.

    Bez ponavljanja: komadi stižu iz mikrofona i mogu se pročitati samo jednom,
    pa drugi pokušaj nema šta da pošalje. Otkaz ovde znači da diktat pada na
    sačuvan snimak, kao i svaki drugi neuspeo poziv.
    """
    return recognize_stream(komadi, cfg, timeout=timeout)
