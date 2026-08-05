# Diktat proba (Android)

Probna aplikacija. **Ništa ne prepoznaje** — prijavljena je na četiri mesta u
sistemu i sa svakog vraća svoj marker, pa se po tekstu koji stigne tačno zna
koji mehanizam na ovom telefonu radi.

Poenta: pre nego što se napiše prava aplikacija, treba znati kako tekst uopšte
može da uđe u polje. Na Androidu za to postoji više puteva i svaki zavisi od
proizvođača i verzije, pa nagađanje ne vredi.

---

## Instalacija

```bash
./build.sh install     # napravi APK i pošalji na povezan telefon
./build.sh             # samo napravi APK
```

Za `install` treba uključen USB debugging (*Podešavanja → Opcije za programere*).
Ako `adb devices` ne vidi telefon, prebaci APK ručno — nalazi se u
`app/build/outputs/apk/debug/app-debug.apk` i ima oko 790 KB.

Traži samo dozvolu za mikrofon; ništa ne šalje na internet.

---

## Šta se proverava

Aplikacija ima ekran koji vodi kroz sve četiri probe i dugmad koja otvaraju
odgovarajuća podešavanja — na Samsungu su zakopana.

### A — mikrofon na postojećoj tastaturi (`RecognitionService`)

Ovo je **najbolji ishod**. „Samsung voice input" i „Google voice input" su
implementacije istog Android API-ja; ako se i mi pojavimo u tom biraču, mikrofon
na tastaturi koju već koristiš zove nas, mi vratimo tekst kakav hoćemo, a
tastatura ga sama ubaci.

Bez nove tastature, bez Accessibility dozvole, bez plutajućih dugmadi.

**Kako proveriti:** izaberi „Diktat proba (A)" kao Voice input, pa u polju u
aplikaciji pritisni mikrofon na tastaturi. Treba da upiše `proba a`.

**Nepoznanica:** Gboard po pravilu ignoriše sistemski izbor i koristi svoje
prepoznavanje. Samsung tastatura ga poštuje — zato birač i postoji.

### B — zasebna tastatura (`InputMethodService`)

Rezervna varijanta, **sigurno radi**. Tastatura koja ima samo dugme za diktat.
Mana je trenje: moraš da se prebaciš na nju i nazad.

**Kako proveriti:** uključi „Diktat proba (B)" u listi tastatura, prebaci se na
nju, pritisni dugme. Treba da upiše `proba b`.

### C — bočni taster (digitalni asistent)

Radi svuda, ne samo kad je tastatura otvorena. Ali obična aktivnost otima fokus
polju u koje bi tekst trebalo da uđe, pa bi pravo rešenje tražilo
`VoiceInteractionSession` plus Accessibility dozvolu za unos.

**Kako proveriti:** postavi „Diktat proba" kao digitalnog asistenta i zadrži
bočni taster. Treba da iskoči `proba c`. **Obrati pažnju:** da li se pri tome
zatvorila tastatura i izgubio kursor iz polja.

### E — pločica u brzim podešavanjima

Najkraći put do nečega što radi: nula posebnih dozvola, radi svuda, ali tekst
završi u clipboard-u pa se lepi ručno.

**Kako proveriti:** dodaj „Diktat proba (E)" među pločice i tapni je. Treba da
spusti `proba e` u clipboard.

---

## Šta javiti

Za svako od **A, B, C, E** samo dve stvari:

1. Radi ili ne radi
2. Ako ne radi — da li se aplikacija uopšte **pojavljuje** u odgovarajućem spisku

Za **C** još i: da li je pritisak bočnog tastera izbacio kursor iz polja.

Na osnovu toga se bira koji put se dovršava.

---

## Šta dolazi posle

Sve teško znanje iz macOS verzije prenosi se mehanički:

| | |
|---|---|
| `pFilter=0` | isključuje maskiranje psovki zvezdicama |
| `audio/l16; rate=16000` | format koji endpoint prima |
| oblik odgovora | više JSON linija, prva obično prazna |
| mala slova | `text.lower()` |
| interpunkcija | briše se, ali ne unutar brojeva (`3,5` ostaje celo) |
| granica | ~30s po zahtevu |

A polovina onoga što je mučilo macOS verziju ovde **ne postoji**: nema
sintetičkih tastera pa nema samosabotaže, nema PortAudio keša uređaja, i ne
treba `tail_seconds` jer korisnik sam pušta dugme.

---

## Struktura

```
app/src/main/
  AndroidManifest.xml              prijave na sva četiri mesta
  java/studio/room211/diktatproba/
    MainActivity.kt                ekran sa uputstvom i prečicama do podešavanja
    ProbeRecognitionService.kt     A — voice input slot
    ProbeInputMethodService.kt     B — tastatura sa jednim dugmetom
    AssistActivity.kt              C — bočni taster
    ProbeTileService.kt            E — pločica
  res/xml/
    recognition_service.xml        prati A
    method.xml                     prati B
build.sh                           napravi i instaliraj
```
