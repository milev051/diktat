"""AI obrada transkripta — uputstvo se sklapa od izabranih alata.

Sirov transkript ide modelu tek kad se ceo diktat zavrsi — jednim pozivom, sa
punim kontekstom. Po segmentu bi model video krhotine i izmisljao krajeve
recenica, a i broj poziva bi skocio sa jednog na stotinak po diktatu.

Alati su nezavisni: sredjivanje (interpunkcija, velika slova, kvacice) je samo
JEDAN od njih. Moze se traziti samo prevod ili samo podela na pasuse a da model
tekst inace ne dira — zato se uputstvo sklapa iz delova umesto da postoji fiksan
prompt po rezimu. Kad nijedan alat nije izabran, poziva nema.
"""

import json
import re
import urllib.error
import urllib.request

from . import webstt

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-flash-lite-latest"

# Izmereno: flash-lite doteruje za ~1s i ne dira reci; gemini-3.5-flash radi
# isto ali za ~12s, a gemma prepisuje uputstvo umesto da ga izvrsi.
UVOD = "Dobijaš sirov transkript govora na srpskom, dobijen prepoznavanjem glasa."

# Izmereno: ispravljanje sredjuje gramaticka neslaganja ("deca su otisao" ->
# "otisla", "sa kolega" -> "sa kolegom"). Ne moze i nece moci da ispravi rec
# koja je gramaticki ISPRAVNA a znacenjski pogresna ("ne registrujem" umesto
# "ne registruje") — tu recenica nema greske, pa model nema po cemu da posumnja.
SREDI = (
    "Oblikuj tekst: dodaj interpunkciju, velika slova i kvačice (č ć ž š đ) "
    "gde po pravopisu treba."
)
ISPRAVI = (
    "Ispravi reči koje prepoznavanje očigledno nije dobro čulo — one koje se "
    "gramatički ne slažu sa ostatkom rečenice (padež, lice, rod, broj). Ako "
    "nisi siguran da je reč pogrešna, ostavi je kakva jeste."
)
PASUSI = (
    "Podeli tekst na pasuse po smislu, sa jednim praznim redom između pasusa. "
    "Nemoj praviti pasus od svake rečenice — grupiši ono što ide zajedno."
)
# Nalik ASD-STE100 (Simplified Technical English): kratke izjavne recenice,
# jedna misao po tacki, bez ukrasa. Za srpski se prenosi duh, ne sam standard.
TACKE = (
    "Preuredi tekst u spisak tačaka. Svaka tačka počinje crticom i razmakom, u "
    "svom redu, i nosi JEDNU misao — kratku i sažetu. Dugačku ili razgranatu "
    "izjavu podeli na više tačaka kad se tako jasnije čita.\n"
    "Zadrži vrstu iskaza: pitanje ostaje pitanje i završava upitnikom, potvrda "
    "ostaje potvrda, sumnja ostaje sumnja.\n"
    "Izbaci poštapalice i uvijanje, piši jednostavnim rečima. Sve činjenice, "
    "brojevi, imena i zaključci moraju da ostanu."
)
# Zaseban alat, jer se trazi i bez tacaka: govor ume da udvoji frazu kad se
# covek ispravlja, a prepoznavanje to prenese doslovno.
PONAVLJANJA = (
    "Izbaci slučajna ponavljanja: kad je ista reč ili fraza izgovorena dvaput "
    "zaredom, ostavi je jednom. Ponavljanje koje nosi značenje "
    "(\u201Evrlo, vrlo dugo\u201C) ostavi kako jeste."
)
# Slobodan opis, ne spisak jezika: korisnik ume da trazi i "pola makedonski
# pola srpski", sto nijedan spisak ne pokriva. Model to razume iz opisa.
PREVOD = (
    "Konačan tekst napiši na: {jezik}. Drži se tog opisa doslovno — ako traži "
    "mešavinu jezika ili neobičan stil, tako i uradi. Značenje mora da ostane "
    "isto: ne dodaj i ne izbacuj sadržaj."
)

# Granice koje vaze uvek. Ostale zavise od izabranih alata i dodaju se u _uputstvo.
GRANICE = [
    "ne dodaj nove misli i ne izbacuj postojeće",
    "ne odgovaraj na sadržaj teksta — ovo je tekst za obradu, ne pitanje",
]
NE_SKRACUJ = "ne preformulišaj i ne skraćuj rečenice"
NE_SREDJUJ = (
    "ne diraj interpunkciju, velika slova i kvačice — u tom pogledu ostavi "
    "tekst tačno kakav je"
)
NE_ISPRAVLJAJ = "ako neka reč deluje pogrešno prepoznato, ostavi je kakva je"
# Bez ove granice model prelama tekst u vise redova i kad pasusi nisu trazeni.
NE_PASUSI = "ne prelamaj tekst — vrati ga kao jedan pasus, bez praznih redova"

KRAJ = "Vrati samo obrađen tekst, bez ikakvog uvoda i bez navodnika."


class PolishError(Exception):
    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


def available(cfg) -> bool:
    return bool(cfg.get("polish_api_key"))


def tidy_on(cfg) -> bool:
    """Sredjuje li model interpunkciju — od toga zavisi i sta mu se salje.

    To vise nije zaseban prekidac nego stil teksta: „pravopisno sredjeno" je
    posao koji radi model, pa se ovde samo cita izbor.
    """
    from . import config
    return config.style(cfg) == "written"



def output_language(cfg) -> str:
    """Opis jezika na kome tekst treba da izadje; prazno = bez prevoda."""
    return (cfg.get("output_language") or "").strip()


def tools(cfg, vec_sredjeno=False) -> list[str]:
    """Izabrani alati. Prazna lista znaci da modelu nema sta da se posalje.

    `vec_sredjeno` znaci da je tekst stigao iz prolaza u kome je model slusao
    snimak — on vec vraca interpunkciju, velika slova i kvacice, pa bi
    sredjivanje bio drugi poziv za posao koji je vec obavljen.
    """
    izabrani = []
    if tidy_on(cfg) and not vec_sredjeno:
        izabrani.append("tidy")
    if cfg.get("polish_dedupe", False):
        izabrani.append("dedupe")
    if cfg.get("polish_bullets", False):
        izabrani.append("bullets")
    elif cfg.get("polish_paragraphs", True):
        # Tacke i pasusi su dva odgovora na isto pitanje; tacke pobedjuju.
        izabrani.append("paragraphs")
    if output_language(cfg):
        izabrani.append("translate")
    return izabrani


def polish(text: str, cfg, timeout=60, vec_sredjeno=False) -> str:
    """Vrati obradjen tekst. Na bilo kakav problem podize PolishError."""
    if not text.strip():
        return text
    if not tools(cfg, vec_sredjeno):
        return text                 # nema alata — nema ni poziva
    key = cfg.get("polish_api_key") or ""
    if not key:
        raise PolishError("Nema API ključa za doterivanje.")

    model = cfg.get("polish_model") or DEFAULT_MODEL
    try:
        return _proveri(text, _pozovi(model, text, key, cfg, timeout, vec_sredjeno), cfg)
    except PolishError as exc:
        # Ako podeseni model nestane ili se preimenuje, probaj podrazumevani —
        # inace bi jedna Google-ova izmena ugasila celu AI obradu.
        if "ne postoji" in str(exc) and model != DEFAULT_MODEL:
            print(f"[diktat] model {model} ne postoji, prelazim na {DEFAULT_MODEL}")
            return _proveri(
                text, _pozovi(DEFAULT_MODEL, text, key, cfg, timeout, vec_sredjeno), cfg
            )
        raise


def _pozovi(model, text, key, cfg, timeout, vec_sredjeno=False):
    url = f"{ENDPOINT}/{model}:generateContent?key={key}"
    payload = {
        "systemInstruction": {"parts": [{"text": _uputstvo(cfg, vec_sredjeno)}]},
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {"temperature": 0.0},
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    try:
        raw = urllib.request.urlopen(request, timeout=timeout).read()
    except urllib.error.HTTPError as exc:
        raise PolishError(
            _explain(exc.code), retryable=exc.code == 429 or exc.code >= 500
        ) from exc
    except urllib.error.URLError as exc:
        raise PolishError(f"Nema veze ({exc.reason}).", retryable=True) from exc
    except TimeoutError as exc:
        raise PolishError("Model nije odgovorio na vreme.", retryable=True) from exc

    try:
        data = json.loads(raw)
        kandidat = data["candidates"][0]
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise PolishError("Model je vratio neocekivan odgovor.") from exc

    parts = kandidat.get("content", {}).get("parts")
    if not parts:
        # Google-ov filter ume da odbije i sasvim bezazlen tekst — izmereno na
        # recenici "deca su otisao u skolu". Diktat zbog toga ne sme da propadne.
        razlog = kandidat.get("finishReason", "nepoznato")
        raise PolishError(
            f"Model nije vratio tekst ({razlog}) — koristim nedoteran.",
            retryable=razlog in ("MAX_TOKENS", "OTHER"),
        )

    out = "".join(p.get("text", "") for p in parts).strip()

    # Prazan odgovor je gori od nedoteranog teksta — bolje vratiti original.
    return out or text


_NEREC = re.compile(r"[^\w\s]|[\U00002190-\U0001FAFF]")


def _reci(text: str) -> list[str]:
    """Reci bez interpunkcije, kvacica i velikih slova — za poredjenje."""
    return webstt.to_ascii(_NEREC.sub(" ", text)).lower().split()


def _sme_da_menja(cfg, vec_sredjeno=False) -> bool:
    """Menja li ijedan izabrani alat same reci."""
    return (
        bool(cfg.get("polish_bullets", False))   # tacke prepisuju recenice
        or bool(cfg.get("polish_dedupe", False))  # brisanje ponavljanja skida reci
        or bool(output_language(cfg))       # prevod po prirodi menja svaku rec
        or "tidy" in tools(cfg, vec_sredjeno)
    )


def _proveri(ulaz: str, izlaz: str, cfg) -> str:
    """Kad model NE sme da menja reci, proveri da ih zaista nije menjao.

    Model ume da dopise rec i kad mu je zabranjeno — izmereno na tekstu koji se
    zavrsava sa „...gledao film ... bio je jako dobar", gde je dodao rec „film"
    jer mu je dovrsavanje recenice ocekivanije. Pooštravanje uputstva to nije
    uklonilo, pa se vernost proverava ovde: nevernost pada na nas tekst.
    """
    if _sme_da_menja(cfg) or _reci(ulaz) == _reci(izlaz):
        return izlaz
    print("[diktat] model je menjao reči iako nije smeo — koristim nedoteran tekst")
    return ulaz


def _uputstvo(cfg, vec_sredjeno=False) -> str:
    """Sklopi uputstvo od izabranih alata.

    Zadaci i granice moraju da se slazu: kad sredjivanje nije izabrano, modelu
    se izricito zabranjuje da dira interpunkciju — inace je dodaje svejedno,
    jer mu je to najocekivanija radnja nad sirovim transkriptom.
    """
    if cfg.get("polish_prompt"):
        return cfg["polish_prompt"]

    izabrani = tools(cfg, vec_sredjeno)

    zadaci = []
    granice = list(GRANICE)

    if "tidy" in izabrani:
        # Ispravljanje je deo sredjivanja, ne zaseban izbor: nivo "samo oblikuj"
        # niko nije koristio, a stajao je kao prekidac koji se ne moze dirati.
        zadaci.append(SREDI)
        zadaci.append(ISPRAVI)
    else:
        granice.append(NE_SREDJUJ)
        granice.append(NE_ISPRAVLJAJ)

    if "dedupe" in izabrani:
        zadaci.append(PONAVLJANJA)
    if "bullets" in izabrani:
        zadaci.append(TACKE)
    elif "paragraphs" in izabrani:
        zadaci.append(PASUSI)
    else:
        granice.append(NE_PASUSI)
    if not {"translate", "bullets", "dedupe"} & set(izabrani):
        # Uz prevod i uz tacke je "ne preformulisi" besmisleno — prepisivanje
        # recenica je ceo posao.
        granice.append(NE_SKRACUJ)
    if "translate" in izabrani:
        zadaci.append(PREVOD.format(jezik=output_language(cfg)))

    if len(zadaci) == 1:
        posao = "Tvoj posao:\n" + zadaci[0]
    else:
        posao = "Uradi sledeće:\n" + "\n".join(
            f"{i}. {z}" for i, z in enumerate(zadaci, 1)
        )
    return "\n\n".join([
        UVOD,
        posao,
        "Granice:\n" + "\n".join(f"- {g}" for g in granice),
        KRAJ,
    ])


def _explain(code: int) -> str:
    if code in (400, 403):
        return f"Model je odbio zahtev ({code}) — proveri API ključ."
    if code == 404:
        return "Traženi model ne postoji na ovom ključu."
    if code == 429:
        return "Previše zahteva ka modelu (429)."
    return f"Model je vratio HTTP {code}."
