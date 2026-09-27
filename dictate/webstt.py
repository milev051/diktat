"""Besplatni Google Web Speech endpoint — onaj koji koristi Chromium.

Bez naloga i bez kredencijala. Isti onaj koji `SpeechRecognition.recognize_google()`
zove vec godinama. Srpski radi vrlo dobro.

Ogranicenja, znaj ih:
  * BATCH, ne streaming — tekst stize tek kad se posalje ceo komad
    (~1.2s za snimke do 30s).
  * Nema automatske interpunkcije ni velikih slova.
  * Endpoint je nedokumentovan i kljuc je javni Chromium kljuc. Radi godinama,
    ali Google ga moze ugasiti bez najave.
  * Prakticno ide do ~30s po zahtevu; duze snimke bolje seci.
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import flac

ENDPOINT = "https://www.google.com/speech-api/v2/recognize"
# Javni Chromium kljuc, ne privatni nalog: isti je u svakoj Chromium instalaciji
# i sa njim radi besplatni Web Speech endpoint. Sme da stoji u repozitorijumu.
DEFAULT_KEY = "AIzaSyBOti4mM-6x9WDnZIjIeyEU21OpBXqWBgw"


class WebSttError(Exception):
    """`retryable` je True samo za prolazne smetnje — mrezu, 429 i 5xx.

    Odbijen kljuc (403) ili neispravan zahtev (400) se ne ponavljaju: drugi
    pokusaj bi dao isto, a diktat bi samo duze cekao.
    """

    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


RETRY_WAIT = 1.0
MAX_RETRIES = 5


def recognize(
    pcm: bytes,
    language="sr-RS",
    sample_rate=16000,
    key=None,
    timeout=30,
    profanity_filter=False,
    retries=MAX_RETRIES,
):
    """Salje sirov 16-bit PCM i vraca prepoznat tekst ('' ako nista).

    Bez `pFilter=0` Google maskira psovke zvezdicama ("sranje" -> "s*****").
    Ime parametra je osetljivo na velika slova — `pfilter` se ignorise.
    """
    return recognize_full(
        pcm, language, sample_rate, key, timeout, profanity_filter, retries
    )[0]


def recognize_full(
    pcm: bytes,
    language="sr-RS",
    sample_rate=16000,
    key=None,
    timeout=30,
    profanity_filter=False,
    retries=MAX_RETRIES,
    compress=True,
):
    """Kao `recognize`, ali vraca i pouzdanost — (tekst, 0.0-1.0).

    Pouzdanost je jedini signal koji endpoint daje o tome koliko je siguran u
    ono sto je cuo; po njoj se odlucuje da li vredi drugo misljenje.
    """
    if not pcm:
        return "", 0.0

    for attempt in range(retries + 1):
        try:
            return _request(
                pcm, language, sample_rate, key, timeout, profanity_filter, compress
            )
        except WebSttError as exc:
            if attempt >= retries or not exc.retryable:
                raise
            print(
                f"[diktat] {exc} — pokusavam ponovo "
                f"({attempt + 1}/{retries})"
            )
            time.sleep(RETRY_WAIT * min(attempt + 1, 5))
    return "", 0.0


def _request(pcm, language, sample_rate, key, timeout, profanity_filter,
             compress=True):
    # FLAC je 36-42% manji, a prepis isti. Ako ffmpeg ne postoji ili zakaze,
    # salje se sirov PCM — usteda ne sme da obori diktat.
    telo, tip = pcm, f"audio/l16; rate={sample_rate}"
    if compress:
        sazeto = flac.encode(pcm, sample_rate)
        if sazeto:
            # Bez `rate=` i sa `audio/flac` endpoint vraca 400 — iskljucivo ovako.
            telo, tip = sazeto, f"audio/x-flac; rate={sample_rate}"
    url = (
        f"{ENDPOINT}?client=chromium"
        f"&lang={urllib.parse.quote(language)}"
        f"&key={key or DEFAULT_KEY}"
        f"&pFilter={1 if profanity_filter else 0}"
    )
    request = urllib.request.Request(url, data=telo, headers={"Content-Type": tip})

    try:
        raw = urllib.request.urlopen(request, timeout=timeout).read()
    except urllib.error.HTTPError as exc:
        raise WebSttError(
            _explain_http(exc.code),
            retryable=exc.code == 429 or exc.code >= 500,
        ) from exc
    except urllib.error.URLError as exc:
        raise WebSttError(
            f"Nema veze sa internetom ({exc.reason}).", retryable=True
        ) from exc
    except TimeoutError as exc:
        raise WebSttError("Isteklo vreme cekanja.", retryable=True) from exc

    return _parse(raw.decode("utf-8", "replace"))


def _parse(body: str):
    """Odgovor je vise JSON linija; prva je obicno prazna {"result":[]}."""
    best = ""
    best_conf = -1.0
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        for result in payload.get("result", []):
            for alt in result.get("alternative", []):
                text = (alt.get("transcript") or "").strip()
                conf = float(alt.get("confidence", 0.0))
                if text and conf >= best_conf:
                    best, best_conf = text, conf
    return best, max(best_conf, 0.0)


def _explain_http(code: int) -> str:
    if code == 403:
        return "Google je odbio kljuc (403) — endpoint je verovatno stegnut."
    if code == 400:
        return "Neispravan zahtev (400) — proveri jezik i sample_rate."
    if code == 429:
        return "Previse zahteva (429). Sacekaj malo."
    return f"Google je vratio HTTP {code}."


# Tacka, zarez i dvotacka se brisu samo kad NISU izmedju cifara: endpoint ih
# vraca kao decimalni separator ("3,5") i kao satnicu ("10:00"), pa bi ih slepo
# brisanje spojilo u 35 i 1000. Crtica i simboli se uklanjaju, osim brojčanih
# separatora (1/2, 10-20).
# Deo koji je isti i za „samo zarezi i upitnici": navodnici, zagrade, crte i
# simboli nestaju u oba slucaja.
_OSTALI_ZNACI = (
    # Apostrof (' i \u2019) NIJE ovde: on je deo reci, vidi `_bez_navodnika`.
    r"[\u00AB\u00BB\u201E\u201C\u201D\"\u2018\u201A\u2039\u203A()\[\]{}]"
    # Crtica i kosa crta nestaju samo kad STOJE SAME. Uslov je `\w`, ne `\d`:
    # sa `\d` je i „crno-beli" gubio crtu i postajao „crnobeli", jer slovo nije
    # cifra. Sada spoj dve reci prezivi („crno-beli", „and/or"), a crta izmedju
    # razmaka se brise („ovo - ono").
    r"|(?<!\w)[-–—/]|[-–—/](?!\w)"
    # `%` NIJE ovde: endpoint ga vrati za izgovoreno „procenata" (izmereno:
    # „popust je dvadeset procenata" -> „popusti je 20%"), pa bi brisanje pojelo
    # jedini trag jedinice. Isto vazi za `$` i `€`, koji nikad nisu ni bili tu.
    r"|[#&*+<=>@\\^_`|~]"
)
_PUNCT = re.compile(
    r"(?<!\d)[.,:]"     # tacka/zarez/dvotacka bez cifre ispred
    r"|[.,:](?!\d)"     # ili bez cifre iza
    r"|[!?;\u2026]|" + _OSTALI_ZNACI
)


# Tacka je separator hiljada samo ako je prate TACNO tri cifre i tu se broj
# zavrsava: "5.000" -> "5000", ali "verzija 2.0" i "android 4.4" ostaju celi.
_THOUSANDS = re.compile(r"(?<=\d)\.(?=\d{3}(?!\d))")


def join_thousands(text: str) -> str:
    prethodno = None
    while text != prethodno:        # "1.500.000" ima vise tacaka
        prethodno = text
        text = _THOUSANDS.sub("", text)
    return text


# Znak koji stoji IZMEDJU DVA SLOVA, bez razmaka, drzi dve reci razdvojene:
# brisanje bi ih slepilo ("gotovo je.sada" -> "gotovo jesada"). Zato prvo
# postaje razmak, pa se tek onda ostatak brise. Apostrof i navodnici namerno
# NISU ovde: „ć'š" mora da ostane jedna rec, ne „ć š".
_LEPAK = re.compile(r"(?<=[^\W\d_])[.,:;!?\u2026]+(?=[^\W\d_])")


# Apostrof je deo reci („je l'", „ć'š", „'ajde") i ostaje. Brisu se samo
# jednostruki navodnici u paru oko reci („'ovako'", „‘ovako’") i apostrof koji
# stoji sam, izmedju razmaka.
_NAVODNICI = re.compile(
    r"(?<!\w)['\u2018\u201A](?=\w)([^'\u2018\u2019\u201A]*?\w)['\u2019](?!\w)"
)
_SAM_APOSTROF = re.compile(r"(?<!\w)['\u2019](?!\w)")


def _bez_navodnika(text: str) -> str:
    return _SAM_APOSTROF.sub("", _NAVODNICI.sub(r"\1", text))


def strip_punctuation(text: str) -> str:
    """Skloni interpunkciju, ali ne diraj brojeve ni spojene reci."""
    if not text:
        return text
    text = _bez_navodnika(text)
    text = _LEPAK.sub(" ", text)
    return " ".join(_PUNCT.sub("", text).split())


_DIACRITICS = str.maketrans({
    "č": "c", "ć": "c", "ž": "z", "š": "s", "đ": "dj",
    "Č": "C", "Ć": "C", "Ž": "Z", "Š": "S", "Đ": "Dj",
})


def to_ascii(text: str) -> str:
    """č ć ž š đ -> c c z s dj. Opciono; podrazumevano iskljuceno."""
    return text.translate(_DIACRITICS) if text else text


# Reci koje se zavrsavaju tackom a NE zavrsavaju recenicu. Posle njih ostaje
# malo slovo. Spisak je namerno kratak i jednoznacan: svaka dodata rec mora da
# bude takva da iza nje nikad ne pocinje recenica.
_SKRACENICE = {
    "br", "cca", "dr", "god", "inz", "inž", "isl", "itd", "mr", "npr",
    "odn", "prof", "sl", "str", "tel", "tj", "tzv", "ul",
}


def _kraj_recenice(rec: str, znak: str) -> bool:
    """Da li `znak` posle reci `rec` zaista zavrsava recenicu.

    Upitnik i uzvicnik uvek zavrsavaju. Tacka ne: u srpskom stoji i iza godine
    i rednog broja ("2026. godine", "5. mesto"), iza skracenica ("npr. ovako")
    i iza inicijala ("M. Petrovic"). U tim slucajevima ostaje malo slovo.
    """
    if znak != ".":
        return True
    if not rec:
        return True
    if rec[-1].isdigit():           # godina, redni broj, verzija
        return False
    if len(rec) == 1:               # inicijal
        return False
    return rec.lower() not in _SKRACENICE


# Slepljena granica: ".Cetvrta" umesto ". Cetvrta". Trazi se VELIKO slovo posle
# tacke, jer malo slovo tu je po pravilu domen ili ime fajla ("config.json",
# "google.com") koje ne sme da se raskine. Upitnik i uzvicnik u njima ne
# postoje, pa posle njih razmak ide bez tog uslova.
_SLEPLJENO = re.compile(r"([.!?])(?=[^\W\d_])")

# Granica recenice sa razmakom: znak, pa razmak, pa slovo koje treba podici.
_GRANICA = re.compile(r"([^\s.!?]*)([.!?])([ \t]+)([^\W\d_])")


def capitalize_sentences(text: str) -> str:
    """Razmak i veliko slovo posle tacke, upitnika i uzvicnika.

    Radi samo kad je izabran pisani stil: uz "izgovoreno" se interpunkcija ionako
    brise, pa nema granice recenice. Prvo slovo celog komada se NE dira — diktat
    se secka na pauzama, pa svaki sledeci komad ume da bude nastavak recenice.
    """
    if not text:
        return text

    def _razmak(m):
        znak = m.group(1)
        slovo = text[m.end(1)]
        if znak == "." and not slovo.isupper():
            return znak
        return znak + " "

    text = _SLEPLJENO.sub(_razmak, text)

    def _veliko(m):
        rec, znak, razmak, slovo = m.groups()
        if not _kraj_recenice(rec, znak):
            return m.group(0)
        return rec + znak + razmak + slovo.upper()

    return _GRANICA.sub(_veliko, text)


# Znakovi koji zavrsavaju misao. Tacka i dvotacka IZMEDJU cifara („10:30",
# „2.0") se ovde ne vide, jer iza njih nije razmak.
_KRAJ_MISLI = re.compile(r"(\S*?)([.!?;:\u2026]+)(?=\s|$)")
# Isto, ali slepljeno uz sledecu rec: „idem.Sutra", „idem?sutra".
_SLEPLJEN_KRAJ = re.compile(r"(?<=[^\W\d_])([.!?;:\u2026]+)(?=[^\W\d_])")
_SLEPLJEN_ZAREZ = re.compile(r"(?<=[^\W\d_]),+(?=[^\W\d_])")
_OSTALO = re.compile(_OSTALI_ZNACI)


def _slepljen_kraj(m) -> str:
    znakovi = m.group(1)
    if "?" in znakovi:
        return "? "
    # Tacka ispred malog slova je domen ili ime fajla („google.com").
    if set(znakovi) == {"."} and not m.string[m.end()].isupper():
        return znakovi
    return ", "


def _kraj_misli(m) -> str:
    rec, znakovi = m.groups()
    if "?" in znakovi:
        return rec + "?"
    # „2026. godine", „5. mesto", „npr." nisu kraj recenice, tacka ostaje.
    # Broj ipak zavrsava recenicu kad iza njega krece nova, velikim slovom:
    # „u 10:30. Sutra".
    if set(znakovi) == {"."} and rec and not _kraj_recenice(rec, "."):
        dalje = m.string[m.end():].lstrip()
        if not (rec[-1].isdigit() and dalje[:1].isupper()):
            return m.group(0)
    return rec + ","


def samo_zarezi(text: str) -> str:
    """Tacke postaju zarezi, a ostaju samo zarezi i upitnici.

    Za pisanje malim slovima: tacka usred teksta tu izgleda cudno, a granica
    misli ipak treba da se vidi. Uzvicnik, tri tacke, tacka-zarez i dvotacka
    postaju zarez; navodnici, zagrade i crte nestaju kao uz „bez
    interpunkcije". Na samom kraju ne ostaje ni tacka ni zarez, samo upitnik.
    """
    if not text:
        return text
    text = _bez_navodnika(text)
    text = _SLEPLJEN_KRAJ.sub(_slepljen_kraj, text)
    text = _SLEPLJEN_ZAREZ.sub(", ", text)
    text = " ".join(_OSTALO.sub("", text).split())
    text = _KRAJ_MISLI.sub(_kraj_misli, text)
    text = re.sub(r"\s+(?=[,?])", "", text)       # „idem ," -> „idem,"
    text = re.sub(r",(?:\s*,)+", ",", text)        # „idem,, ," -> „idem,"
    text = re.sub(r",\s*\?", "?", text)            # „zar ne,?" -> „zar ne?"
    text = re.sub(r"\?\s*,", "?", text)
    text = re.sub(r"\?(?=[^\W\d_])", "? ", text)   # posle upitnika ide razmak
    text = re.sub(r"^[,\s]+", "", text)
    return re.sub(r"[.,\s]+$", "", text)


# Glasovne komande: izgovoreno „novi red" i „novi pasus" postaje prelom.
# Google ih vraca kao obicne reci, bez znakova (izmereno 27.09.2026). Zarez i
# razmak ispred komande nestaju, a tacka ostaje („grad. Novi red." -> „grad.\n").
_KOMANDA = re.compile(
    r"\s*,?\s*\b(?:novi|nov)\s+(red|pasus)\b[.,;:!]?[ \t]*", re.IGNORECASE
)


def glasovne_komande(text: str) -> str:
    """„novi red" -> nov red, „novi pasus" -> prazan red.

    Radi se tek pri upisu (insert.py) i u istoriji, ne u pravilima: pravila i
    AI obrada rade red po red i skupljaju razmake, pa bi prelom izgubili.
    Komanda izgovorena sama, posle pauze, stigne kao zaseban deo diktata;
    prelom tada pojede i razmak koji je dobila na kraju.
    """
    if not text or "n" not in text.lower():
        return text
    return _KOMANDA.sub(
        lambda m: "\n\n" if m.group(1).lower() == "pasus" else "\n", text
    )


def interpunkcija(text: str, cfg) -> str:
    """Lokalni izbor interpunkcije za jedan red teksta.

    „Bez interpunkcije" pobedjuje „samo zareze": uz oba upaljena ne ostaje
    nista. Ni jedno ni drugo znaci da tekst ostaje onakav kakav je stigao.
    """
    if cfg.get("strip_punctuation", True):
        return strip_punctuation(text)
    if cfg.get("samo_zarezi", False):
        return samo_zarezi(text)
    return text


def tidy(text: str) -> str:
    """Endpoint ne vraca veliko pocetno slovo — bar to doteramo."""
    if not text:
        return text
    return text[0].upper() + text[1:]
