"""AI obrada transkripta — uputstvo se sklapa od izabranih alata.

Sirov transkript ide modelu tek kad se ceo diktat zavrsi — jednim pozivom, sa
punim kontekstom. Po segmentu bi model video krhotine i izmisljao krajeve
recenica, a i broj poziva bi skocio sa jednog na stotinak po diktatu.

Alati su nezavisni: sredjivanje (interpunkcija, velika slova, kvacice) je samo
JEDAN od njih. Moze se traziti skracivanje ili emotikon a da model tekst inace
ne dira — zato se uputstvo sklapa iz delova umesto da postoji fiksan prompt po
rezimu. Kad nijedan alat nije izabran, poziva nema.
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

# Izmereno: "correct" ispravlja gramaticka neslaganja ("deca su otisao" ->
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
# Gustina emotikona. Kljucevi su vrednosti `polish_emoji_rate`.
EMOTIKONI = {
    "paragraph": (
        "na kraj svakog pasusa dodaj tačno jedan emoji znak (na primer 🙂 ili "
        "📌) koji odgovara njegovom tonu; ako je ceo tekst jedan pasus, emoji "
        "ide na sam kraj"
    ),
    "sentence": (
        "na kraj svake rečenice dodaj tačno jedan emoji znak koji odgovara "
        "onome što ta rečenica kaže"
    ),
    "dense": (
        "posle svake dve do tri reči ubaci po jedan emoji znak koji odgovara "
        "upravo rečenom — ne posle svake reči, nego na svake dve-tri"
    ),
}
# "ni broj ni oznaku" nije visak: izmereno je da model, kad mu se trazi
# raznolikost, pocne da numerise reci (juce¹ sam² bio³) da bi sam sebi brojao.
EMOTIKONI_KRAJ = " Dodaješ isključivo emoji znakove — nijednu reč, broj ni oznaku."
# Koliko znakova se pamti; isti se ne sme vratiti dok se toliko drugih ne potrosi.
EMOJI_PAMTI = 15
EMOTIKONI_RAZNOLIKOST = (
    "Nijedan emoji ne ponavljaj u istom tekstu — svaki mora da bude drugačiji. "
    "Izbegavaj i ove, upravo su korišćeni: {vec}"
)
# Kad nijedan drugi alat ne sme da menja reci, ispred zadatka ide ovaj uvod.
# Izmereno: nad tekstom koji se zavrsava sa "gledao film ... bio je jako dobar"
# obicna formulacija navede model da dopise REC "film" pre znaka — dovrsavanje
# recenice mu je ocekivanije od emotikona. "Prepisi od reci do reci" to ukloni
# (3/3), dok je strozija granica gasila i sam emotikon.
EMOTIKONI_VERNO = "Prepiši tekst od reči do reči, ne menjajući nijednu reč, i "
SAZMI = (
    "Skrati tekst: izbaci poštapalice i ponavljanja, a predugačke rečenice "
    "razbij na kraće i jasnije. Sve činjenice, brojevi, imena i zaključci "
    "moraju da ostanu — smeš da izbaciš reči, ne i sadržaj."
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
    """Sredjuje li model interpunkciju — od toga zavisi i sta mu se salje."""
    return bool(cfg.get("polish_tidy", True))


# Jedan emoji ume da bude sastavljen od vise kodnih tacaka (ZWJ, ton koze,
# selektor prikaza), pa se hvata kao celina — inace bi "👨‍💼" bio dva znaka.
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\u2190-\u2BFF\u2600-\u27BF\u2B00-\u2BFF]"
    "[\uFE00-\uFE0F\U0001F3FB-\U0001F3FF]?"
    "(?:\u200D[\U0001F000-\U0001FAFF\u2600-\u27BF][\uFE00-\uFE0F\U0001F3FB-\U0001F3FF]?)*"
)


def emoji_list(text: str) -> list[str]:
    """Emotikoni iz teksta, redom kojim se pojavljuju."""
    return _EMOJI.findall(text)


def bez_ponavljanja(text: str) -> str:
    """Izbaci emotikon koji se u istom tekstu vec pojavio.

    Uputstvo dovede model blizu — ali u gustom rezimu zna da ponovi jedan znak.
    Brisanje viska je bezbedno: tekst se ne dira, samo znak nestane.
    """
    videni = set()

    def zameni(m):
        znak = m.group(0)
        if znak in videni:
            return ""
        videni.add(znak)
        return znak

    out = _EMOJI.sub(zameni, text)
    out = re.sub(r"[^\S\n]{2,}", " ", out)      # dvostruki razmaci iza brisanja
    return re.sub(r"[^\S\n]+\n", "\n", out).strip()


def zapamti_emoji(text: str, cfg) -> None:
    """Dopuni istoriju poslednjih EMOJI_PAMTI znakova, bez ponavljanja."""
    istorija = list(cfg.get("polish_emoji_recent") or [])
    for znak in emoji_list(text):
        if znak in istorija:
            istorija.remove(znak)
        istorija.append(znak)
    cfg["polish_emoji_recent"] = istorija[-EMOJI_PAMTI:]


def emoji_rate(cfg) -> str:
    """paragraph | sentence | dense — koliko cesto emotikon."""
    rate = cfg.get("polish_emoji_rate", "paragraph")
    return rate if rate in EMOTIKONI else "paragraph"


def tools(cfg) -> list[str]:
    """Izabrani alati. Prazna lista znaci da modelu nema sta da se posalje."""
    izabrani = []
    if tidy_on(cfg):
        izabrani.append("tidy")
    if cfg.get("polish_paragraphs", True):
        izabrani.append("paragraphs")
    if cfg.get("polish_emoji", False):
        izabrani.append("emoji")
    if cfg.get("polish_concise", False):
        izabrani.append("concise")
    return izabrani


def polish(text: str, cfg, timeout=60) -> str:
    """Vrati obradjen tekst. Na bilo kakav problem podize PolishError."""
    if not text.strip():
        return text
    if not tools(cfg):
        return text                 # nema alata — nema ni poziva
    key = cfg.get("polish_api_key") or ""
    if not key:
        raise PolishError("Nema API ključa za doterivanje.")

    model = cfg.get("polish_model") or DEFAULT_MODEL
    try:
        return _proveri(text, _pozovi(model, text, key, cfg, timeout), cfg)
    except PolishError as exc:
        # Ako podeseni model nestane ili se preimenuje, probaj podrazumevani —
        # inace bi jedna Google-ova izmena ugasila celu AI obradu.
        if "ne postoji" in str(exc) and model != DEFAULT_MODEL:
            print(f"[diktat] model {model} ne postoji, prelazim na {DEFAULT_MODEL}")
            return _proveri(text, _pozovi(DEFAULT_MODEL, text, key, cfg, timeout), cfg)
        raise


def _pozovi(model, text, key, cfg, timeout):
    url = f"{ENDPOINT}/{model}:generateContent?key={key}"
    payload = {
        "systemInstruction": {"parts": [{"text": _uputstvo(cfg)}]},
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
    """Reci bez interpunkcije, emotikona, kvacica i velikih slova — za poredjenje."""
    return webstt.to_ascii(_NEREC.sub(" ", text)).lower().split()


def _sme_da_menja(cfg) -> bool:
    """Menja li ijedan izabrani alat same reci."""
    return bool(cfg.get("polish_concise", False)) or (
        tidy_on(cfg) and cfg.get("polish_level", "correct") == "correct"
    )


def _proveri(ulaz: str, izlaz: str, cfg) -> str:
    """Kad model NE sme da menja reci, proveri da ih zaista nije menjao.

    Izmereno: uz samo emotikon nad tekstom „...gledao film ... bio je jako
    dobar" model dopise REC „film" pre znaka — dovrsavanje recenice mu je
    ocekivanije od emotikona, a bez interpunkcije nema sta da ga zaustavi.
    Nijedno pooštravanje uputstva to nije uklonilo: strozija granica je ugasila
    i sam emotikon. Zato se veri proverava ovde, a nevernost pada na nas tekst.
    """
    if _sme_da_menja(cfg) or _reci(ulaz) == _reci(izlaz):
        return izlaz
    print("[diktat] model je menjao reči iako nije smeo — koristim nedoteran tekst")
    return ulaz


def _uputstvo(cfg) -> str:
    """Sklopi uputstvo od izabranih alata.

    Zadaci i granice moraju da se slazu: kad sredjivanje nije izabrano, modelu
    se izricito zabranjuje da dira interpunkciju — inace je dodaje svejedno,
    jer mu je to najocekivanija radnja nad sirovim transkriptom.
    """
    if cfg.get("polish_prompt"):
        return cfg["polish_prompt"]

    izabrani = tools(cfg)
    correct = cfg.get("polish_level", "correct") == "correct"

    zadaci = []
    granice = list(GRANICE)

    if "tidy" in izabrani:
        zadaci.append(SREDI)
        if correct:
            zadaci.append(ISPRAVI)
        else:
            granice.append(NE_ISPRAVLJAJ)
    else:
        granice.append(NE_SREDJUJ)
        granice.append(NE_ISPRAVLJAJ)

    if "paragraphs" in izabrani:
        zadaci.append(PASUSI)
    else:
        granice.append(NE_PASUSI)
    if "concise" in izabrani:
        zadaci.append(SAZMI)
    else:
        granice.append(NE_SKRACUJ)
    if "emoji" in izabrani:
        gustina = EMOTIKONI.get(emoji_rate(cfg), EMOTIKONI["paragraph"])
        zadatak = (
            gustina[0].upper() + gustina[1:] if _sme_da_menja(cfg)
            else EMOTIKONI_VERNO + gustina
        ) + "." + EMOTIKONI_KRAJ
        vec = cfg.get("polish_emoji_recent") or []
        if vec:
            zadatak += " " + EMOTIKONI_RAZNOLIKOST.format(vec=" ".join(vec))
        else:
            zadatak += " Nijedan emoji ne ponavljaj u istom tekstu."
        zadaci.append(zadatak)

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
