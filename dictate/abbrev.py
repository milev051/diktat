"""Skracenice i uredjivanje jedinica, ista pravila kao na Androidu.

Format je jedan red po pravilu, `fraza=skracenica`. Red koji pocinje sa `#` je
komentar. Slepljene jedinice se razdvajaju, a brojevi napisani recima ostaju
onako kako ih je transkripcija vratila. Oblici „minut", „minuta" i „minute"
postaju „min"; uz cifru se lepe, pa „15 minuta" postaje „15min".
"""

import re

DEFAULT = [
    ("ne znam", "nzm"),
    ("jebi ga", "jbg"),
    ("jebem li ga", "jbm li ga"),
    ("je li", "je l"),
    ("jeli", "je l"),
    ("znam", "znm"),
    ("ne mogu", "nmg"),
    ("nema veze", "nmvz"),
    ("na primer", "npr"),
    ("i tako dalje", "itd"),
    ("to jest", "tj"),
    ("to je to", "tjt"),
    ("svejedno", "svj"),
    # Prepoznavanje ovo vraca i rastavljeno, pa oba oblika moraju u spisak.
    ("sve jedno", "svj"),
    ("mislim", "msm"),
]

_GRUPA = re.compile(r"\{(\d)\}")

_BROJEVI = {
    "nula": 0,
    "jedan": 1, "jedna": 1, "jedno": 1,
    "dva": 2, "dve": 2, "dvije": 2,
    "tri": 3, "četiri": 4, "cetiri": 4, "pet": 5,
    "šest": 6, "sest": 6, "sedam": 7, "osam": 8, "devet": 9,
    "deset": 10, "jedanaest": 11, "dvanaest": 12, "trinaest": 13,
    "četrnaest": 14, "cetrnaest": 14, "petnaest": 15,
    "šesnaest": 16, "sesnaest": 16, "sedamnaest": 17,
    "osamnaest": 18, "devetnaest": 19,
    "dvadeset": 20, "trideset": 30, "četrdeset": 40, "cetrdeset": 40,
    "pedeset": 50, "šezdeset": 60, "sezdeset": 60, "sedamdeset": 70,
    "osamdeset": 80, "devedeset": 90,
    "sto": 100, "stotinu": 100, "dvesta": 200, "trista": 300,
    "četiristo": 400, "cetiristo": 400, "petsto": 500, "šeststo": 600,
    "seststo": 600, "sedamsto": 700, "osamsto": 800, "devetsto": 900,
}
_SKALE = {
    "hiljadu": 1000, "hiljada": 1000, "hiljade": 1000,
    "milion": 1_000_000, "miliona": 1_000_000,
    "milijardu": 1_000_000_000, "milijarde": 1_000_000_000,
}
_BROJ_RECI = tuple(sorted(_BROJEVI | _SKALE, key=len, reverse=True))
_BROJ_DEO = "(?:" + "|".join(re.escape(reč) for reč in _BROJ_RECI) + ")"
_JEDINICE = (
    "minuta", "minut", "minute", "min", "sati", "sata", "sat", "časova",
    "časa", "čas", "sekundi", "sekunde", "sekunda", "sek", "dinara", "dinar",
    "din", "kilometara", "kilometar", "km", "metara", "metar", "m", "grama",
    "gram", "kg", "evra", "evro", "eur", "dolara", "dolar", "usd", "procenata",
    "procenat", "h", "s",
)
_JEDINICA_DEO = "(?:" + "|".join(
    re.escape(reč) for reč in sorted(_JEDINICE, key=len, reverse=True)
) + ")"
_SLEPLJENA_JEDINICA = re.compile(
    rf"(?<!\w)(?P<broj>{_BROJ_DEO})(?P<jedinica>{_JEDINICA_DEO})(?!\w)",
    re.IGNORECASE,
)
_SLEPLJENA_CIFRA = re.compile(
    rf"(?<!\w)(?P<broj>\d+(?:[.,]\d+)?)(?P<jedinica>{_JEDINICA_DEO})(?!\w)",
    re.IGNORECASE,
)
_CIFRA_UZ_JEDINICU = re.compile(
    rf"(?<!\w)(?P<broj>\d+(?:[.,]\d+)?)[ \t]+(?P<jedinica>{_JEDINICA_DEO})(?!\w)",
    re.IGNORECASE,
)
_MINUTA_UZ_CIFRU = re.compile(
    r"(?<!\w)(?P<broj>\d+(?:[.,]\d+)?)[ \t]+(?:minuta|minut|minute|min)(?!\w)",
    re.IGNORECASE,
)
_OBLIK_MINUTA = re.compile(
    r"(?<!\w)(?:minuta|minut|minute)(?!\w)",
    re.IGNORECASE,
)
_STO_KAO_STO = re.compile(
    r"(?i)(?<!\w)sto(?=\s+(?:je|sam|si|smo|ste|su|će|ce|ću|cu|bi|bih|bismo|biste|nisam|nije|nisi|nismo|niste|nisu|može|moze|mogu|treba|trebalo)(?!\w))"
)
_STO_U_KONTEKSTU = re.compile(
    r"(?i)(?<!\w)(zato)\s+sto(?!\w)"
)


def normalize_spoken_numbers(text: str) -> str:
    """Razdvoji tekstualni broj od jedinice, bez menjanja samog broja."""
    if not text:
        return text
    # ASR ponekad vrati „sto“ umesto „što“. Zaštiti najčešće vezničke obrasce
    # pre ostalih pravila, da „zato što je“ ne postane „zato sto je“.
    text = _STO_U_KONTEKSTU.sub(lambda m: f"{m.group(1)} što", text)
    text = _STO_KAO_STO.sub("što", text)
    text = _SLEPLJENA_JEDINICA.sub(r"\g<broj> \g<jedinica>", text)
    text = _SLEPLJENA_CIFRA.sub(r"\g<broj> \g<jedinica>", text)
    text = _MINUTA_UZ_CIFRU.sub(r"\g<broj>min", text)
    text = _OBLIK_MINUTA.sub("min", text)
    return _OBLIK_MINUTA.sub("min", text)


def default_text() -> str:
    return "\n".join(f"{fraza}={kratko}" for fraza, kratko in DEFAULT)


def parse(text: str) -> list:
    """Pravila iz teksta. Ista fraza dvaput — POSLEDNJI red pobedjuje.

    Bez toga bi stari red iznad novog tiho pojeo rec pre nego sto novi dodje
    na red, pa bi izgledalo da izmena nije primljena.
    """
    videni = {}
    for red in (text or "").splitlines():
        red = red.strip()
        if not red or red.startswith("#") or "=" not in red:
            continue
        fraza, _, kratko = red.partition("=")
        fraza, kratko = fraza.strip(), kratko.strip()
        if fraza:
            videni[fraza.lower()] = kratko
    return list(videni.items())


def _zamena(korisnicka: str) -> str:
    """`{1}` je grupa; sve ostalo je doslovno (i `\\` i `\\1` iz govora)."""
    out, kraj = [], 0
    for m in _GRUPA.finditer(korisnicka):
        out.append(korisnicka[kraj:m.start()].replace("\\", r"\\"))
        out.append("\\" + m.group(1))
        kraj = m.end()
    out.append(korisnicka[kraj:].replace("\\", r"\\"))
    return "".join(out)


def apply(text: str, rules) -> str:
    if not text.strip():
        return text
    out = normalize_spoken_numbers(text)
    if not rules:
        return _CIFRA_UZ_JEDINICU.sub(r"\g<broj>\g<jedinica>", out)

    for uzorak, zamena in rules:
        if not uzorak.startswith("~"):
            continue
        try:
            out = re.sub(uzorak[1:], _zamena(zamena), out, flags=re.IGNORECASE)
        except re.error:
            continue        # neispravan izraz ne sme da obori diktat

    proste = [(f, z) for f, z in rules if not f.startswith("~")]
    for fraza, zamena in sorted(proste, key=lambda p: len(p[0]), reverse=True):
        lepi = zamena.startswith("<")
        # trim posle skidanja „<": napisano kao „< RSD" razmak bi inace dosao iz
        # same zamene, pa bi izgledalo da „<" ne radi.
        kratko = zamena[1:].strip() if lepi else zamena
        # Lookbehind ide POSLE \s*, ne pre: cifra ispred („15 minuta") je
        # rec-znak, pa bi provera stavljena ranije oborila poklapanje.
        uzorak = (r"\s*" if lepi else "") + rf"(?<!\w){re.escape(fraza)}(?!\w)"
        out = re.sub(uzorak, kratko.replace("\\", r"\\"), out, flags=re.IGNORECASE)
    # Posle korisničkih pravila: `dinara=RSD` zadržava razmak, dok
    # `dinara=<RSD` namerno lepi zamenu uz cifru.
    return _CIFRA_UZ_JEDINICU.sub(r"\g<broj>\g<jedinica>", out)
