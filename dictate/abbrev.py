"""Skracenice: „ne znam" -> „nzm". Ista pravila kao na Androidu.

Format je jedan red po pravilu, `fraza=skracenica`. Red koji pocinje sa `#` je
komentar. Dva posebna znaka:

  minuta=<min          `<` pojede i RAZMAK ISPRED, pa se zalepi: „15 minuta" -> „15min"
  ~(\\d+)\\s*dolara={1}   `~` znaci regularni izraz; `{1}` je uhvacena grupa

Regularni izrazi idu PRVI: „100 dolara" mora da postane „$100" pre nego sto
prosto pravilo stigne da pojede samu rec „dolara".
"""

import re

DEFAULT = [
    ("ne znam", "nzm"),
    ("jebi ga", "jbg"),
    ("znam", "znm"),
    ("ne mogu", "nmg"),
    ("nema veze", "nmvz"),
    ("na primer", "npr"),
    ("i tako dalje", "itd"),
    ("to jest", "tj"),
    ("to je to", "tjt"),
    ("svejedno", "svj"),
    ("mislim", "msm"),
    ("minuta", "<min"),
    ("minut", "<min"),
    # „posto" ne ide ovde: znaci i „procenata" i „buduci da", pa bi zamena
    # pokvarila drugu upotrebu. „procenata" je jednoznacno.
    ("procenata", "<%"),
    (r"~(\d+(?:[.,]\d+)?)\s*dolara?", "${1}"),
    ("dolara", "$"),
    ("dolar", "$"),
    ("rsd", "<din"),
    ("eur", "<€"),
]

_GRUPA = re.compile(r"\{(\d)\}")


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
    if not text.strip() or not rules:
        return text
    out = text

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
    return out
