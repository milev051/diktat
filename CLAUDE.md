# Napomene za održavanje

Ovaj projekat održavaju modeli, ne ljudi. Ovde su odluke i **razlozi** za njih,
plus greške koje su već napravljene — da se ne ponavljaju.

Dva dela, isti Google Web Speech endpoint (Chromium, javni ključ):
`dictate/` (macOS, Python — desni Option) i `android/` (Kotlin — bočni taster).

---

## Pravila koja se ne smeju prekršiti

**Prozor sa stanjem ne sme da uzme fokus.** Tekst se lepi u polje koje je bilo
aktivno; ako ga naš prozor otme, nema gde da ode.
macOS: `NSWindowStyleMaskNonactivatingPanel`. Android: `FLAG_NOT_FOCUSABLE`.

**Naše sintetičke tastere moramo da prepoznamo kao svoje.** Lepljenje šalje
Cmd+V; bez zastavice `insert.injecting` naš hotkey to vidi kao korisnikovu
prečicu i **otkaže sopstveni diktat**. Ovo je bio najteži bug u projektu.

**Snimanje se ne prekida naglo.** Taster se pušta tačno na kraju poslednje reči,
a PortAudio isporučuje u blokovima — bez `tail_seconds` (0.8s) ta reč se gubi.
Izmereno: 0.3s zvuka bez repa, 1.1s sa njim.

**Redosled ubacivanja se čuva kroz tikete.** Broj se dodeljuje kad se završi
**audio** segmenta, ne kad se završi prepoznavanje. Mikrofon snima jedno po
jedno, pa je taj redosled hronološki — kraći drugi snimak inače stigne pre
dužeg prvog.

**Nivo zvuka za detekciju pauze računa se iz samog komada**, nikad iz
`recorder.level`. To je nivo poslednjeg *uhvaćenog* komada; potrošač kasni, pa
bi detektor gledao jedan zvuk a sekao drugi. Kad zaostajanje pređe
`pause_seconds`, rez padne usred reči i ta reč se izgubi na oba kraja.

**Dužina segmenta meri se po zvuku, ne zidnim satom.** `max_request_seconds` je
granica koliko sekundi *zvuka* endpoint prima — to dvoje mora da bude ista mera.

**Tačka u hiljadama nije isto što i decimalna.** Endpoint vraća „5.000" za
izgovoreno „pet hiljada". Tačka se briše samo ako je prate **tačno tri cifre**
i tu se broj završava — tako `verzija 2.0` i `android 4.4` ostaju celi. Zarez se
ne dira, on je decimalni.

**`segment_after_seconds` i `pause_seconds` nisu isto.** Prvo je najkraći
segment koji sme da se preseče (0 = svaka pauza vredi), drugo je koliko tišine
uopšte broji kao pauza (0.7s). Snižavanje drugog bi seklo između reči i
proizvodilo krhotine koje se loše prepoznaju — menjaj prvo.

**Neprekidni režim ne sme da gomila zvuk u memoriji.** Sat vremena je preko
100 MB. Zato Android `Recorder` izbacuje komade kroz red, a potrošač drži samo
tekući segment i pušta ga čim ga pošalje.

**Snimanje uvek staje na granici.** Slučajno pokrenut diktat bi inače snimao
satima i poslao ogromnu količinu podataka. Posle prekida se **traži nov
pritisak** — a prekidač se mora vratiti u mirovanje (`listener.reset()`), inače
sledeći pritisak radi STOP umesto START i korisnik pritiska dvaput.

**Neuspeo diktat se ne sme izgubiti.** Endpoint može da zakaže bez najave, pa
se snimak čuva na disk i šalje ponovo iz menija. Prolazne greške (mreža, 429,
5xx) se ponavljaju jednom; 400 i 403 nikad — drugi pokušaj bi dao isto.

**Interpunkcija se ne briše slepo.** Endpoint vraća zarez kao decimalni
separator (`3,5`) i dvotačku kao satnicu (`10:00`). Tačka, zarez **i dvotačka**
brišu se **samo kad nisu između cifara**; crtica samo kad stoji sama, da
`crno-beli` ostane celo. Svaki znak koji može da stoji između cifara mora u tu
grupu — inače tiho pokvari brojeve.

---

## Greške koje su već napravljene

| greška | posledica | ispravno |
|---|---|---|
| Krivi navodnici `" "` u regexu kopirani kao obični | pravilo tiho oslabi | piši `\uXXXX` |
| Lookbehind pre `\s*` kod skraćenica | cifra ispred obori poklapanje, razmak ostane | lookbehind **posle** `\s*` |
| `rumps` `clear()` na još praznom podmeniju | pad pri pokretanju | proveri `_menu != null` |
| Test menja `config.json` bez `try/finally` | ostane `clipboard_only`, lepljenje „ne radi" | uvek `try/finally` |
| Android: upis odmah po zatvaranju aktivnosti | fokus se još nije vratio, tekst padne u clipboard | 12 pokušaja × 120ms |
| Grana koja crta tajmer izlazi pre osvežavanja naslova | ikonica zaglavi u pogrešnom stanju | grana sama postavlja naslov |
| `_settle_phase` i `_on_start` bez zajedničkog katanca | „snima" se prepiše preko „obrađuje" | isti `_session_lock` |
| Slot za mikrofon oslobođen pre zatvaranja strima | sledeći diktat reinicijalizuje PortAudio nad živim strimom | zatvori strim **prvi** |
| Skraćenice: `<` bez `trim()` posle skidanja | `dinara=< RSD` ostavi razmak iz same zamene | `substring(1).trim()` |
| Skraćenice: ista fraza navedena dvaput | stari red iznad novog tiho pojede reč | dedupe, **poslednji pobeđuje** |
| Ime fajla samo od vremena | dva zapisa u istoj sekundi se prepišu | milisekunde **plus brojač** |
| …ali onda sortiranje **po imenu** | brojač razbije azbučni redosled, briše se pogrešan fajl | sortiraj po `st_mtime_ns` |
| `self._pending` iskorišćeno dvaput | brojač i prodavnica se sudarili, pad u `_tick` | `_pending_store` odvojeno |
| Android: `EditText` u `ScrollView` | spoljni skrol pojede pokret, polje se ne skroluje | `requestDisallowInterceptTouchEvent` |
| …ali **bezuslovno** preuzimanje pokreta | veliko polje zaglavi celu stranicu, donje sekcije nedostupne | preuzmi samo ako `layout.height > vidljiva visina` |

---

## Zašto je nešto tako a ne drugačije

**Google nedosledno vraća valute.** Izmereno: „sto dinara" → `100` (valuta
nestane), „petsto dinara i dvadeset evra" → `500 RSD i 20`. Pravilo `dinara=…`
zato često nema šta da uhvati; hvata se `rsd=…`. Kad Google izostavi valutu,
aplikacija nema šta da vrati.

**Google Cloud motor je obrisan.** Davao je prikaz reč-po-reč, ali je tražio
nalog, karticu i `grpcio`. Besplatni endpoint radi za srpski (izmereno 0.93) i
nema podešavanja. Ne vraćaj ga bez izričitog zahteva.

**`pFilter=0` gasi maskiranje psovki.** Ime parametra je **osetljivo na velika
slova** — `pfilter` se tiho ignoriše.

**Android: bočni taster je prekidač, ne držanje.** Sistem šalje samo
„pokreni"; događaj za puštanje ne postoji.

**Android: `LanguageDetailsReceiver` mora da postoji.** Samsung tastatura pita
servis koje jezike zna; bez odgovora pretpostavi engleski i odbije srpski.
Gboard to ne pita.

**Boja u menu baru ide preko `nsstatusitem.button().setAttributedTitle_`**, jer
`rumps.title` ne ume boju. Font mora biti `monospacedDigit` — inače se širina
naslova menja svake sekunde i ostale ikonice poskakuju.

**Podrazumevane skraćenice utiču samo na nove instalacije.** Postojeća ima svoja
pravila sačuvana; pokupi nova tek dugmetom u aplikaciji.

**Regex pravila (`~`) primenjuju se pre prostih.** Inače `dolara=$` pojede reč
pre nego što `~(\d+)\s*dolara={1}` stigne da premesti simbol ispred cifre.

---

## Kako se proverava izmena

**macOS** — posle svake izmene pokreni aplikaciju i **proveri da je proces
živ**, ne samo da nema greške u prevođenju. Dva pada su uhvaćena samo ovako:

```bash
./run.sh doctor          # dozvole, mikrofon, endpoint
./run.sh test 5          # snimi 5s i ispiši šta je čuo
```

**Android** — release je skupljen R8-om, pa komponente iz manifesta moraju
ostati u `proguard-rules.pro`; inače ih R8 preimenuje i sistem ih ne nađe.
Provera: `aapt2 dump xmltree` nad gotovim APK-om mora da pokaže svih pet akcija.

**Android** — build koji „prođe" ne znači da je izmena unutra. Proveri u dex-u:

```bash
cd android && ./build.sh
unzip -o app/build/outputs/apk/debug/app-debug.apk 'classes*.dex' -d /tmp/dx
strings -a /tmp/dx/classes*.dex | grep 'tvoj-novi-string'
```

Dijakritički stringovi se ne vide (MUTF-8) — traži ASCII delove.
Podigni `versionName` da se na telefonu vidi koja je verzija.

**Logika bez uređaja** — `cd android && ./gradlew test` pokreće 9 JVM testova
nad pravilima za tekst. Koristi ih pre nagađanja: tako je utvrđeno da `<`
ispravno radi, a da je problem bio u sačuvanim pravilima na telefonu.

**Izmena `Abbreviations.DEFAULT` ne stiže na telefon sama** ako je korisnik već
menjao svoja pravila. Uz pravila se pamti snimak podrazumevanih; poklapaju li
se, nova se pokupe tiho.

---

**Formalni režim zove model JEDNOM, na kraju diktata.** Po segmentu bi model
video krhotine i izmišljao krajeve rečenica, a poziva bi za deset minuta bilo
oko sto pedeset umesto jednog. U tom režimu tekst ide modelu **nedirnut** —
skraćenice i skidanje kvačica mu otežavaju čitanje.

Izmereno na istom zadatku: `gemini-flash-lite-latest` ~1.0s i ne dira reči;
`gemini-3.5-flash` isto ali ~12s; `gemma-4-31b-it` prepisuje uputstvo umesto da
ga izvrši. Provera vernosti: doteran tekst sveden na mala slova bez kvačica i
interpunkcije mora da se poklopi sa ulazom.

**Model ne može da ispravi reč koja je gramatički ispravna.** Izmereno: nivo
`correct` sređuje neslaganja (`sa kolega` → `sa kolegom`, `kako sam ocekivali`
→ `očekivao`), ali `ne registrujem` umesto `ne registruje` ostaje — rečenica
nema greške pa model nema po čemu da posumnja. Ne pokušavaj to jačim promptom;
tada počne da prepravlja ono što je bilo tačno.

**Google ne nudi uvid u preostalu kvotu.** Ni jedan endpoint ne vraća koliko je
zahteva ostalo, pa se broji lokalno (`polish_count` + `polish_count_day` na
Mac-u, `polish_count` + `polish_day` u `SharedPreferences` na Androidu). Ne
troši pozive na „proveru stanja" — takve provere nema.

**Svaki otkaz modela mora da završi nedoteranim tekstom.** 404 povlači jedan
pokušaj sa `DEFAULT_MODEL` (model se ukine ili preimenuje), sve ostalo pada na
sirov transkript. Diktat ne sme da propadne zato što je AI dodatak zakazao.

**Filter sadržaja ume da odbije bezazlen tekst.** Izmereno: „deca su otisao u
skolu" → `PROHIBITED_CONTENT`, odgovor bez `parts`. Uvek proveri `finishReason`
i vrati nedoteran tekst — diktat zbog toga ne sme da propadne.

**Gemma nije upotrebljiva za ovo.** `gemma-4-26b-a4b-it` i `-31b-it`: 13–15s i
vrate 200–300 reči objašnjenja umesto obrađenog teksta od 28 reči, i sa
sistemskim uputstvom i bez njega.

**API ključ nikad ne ide u git.** macOS: `config.json` (ignorisan). Android:
`SharedPreferences`. Ni u `config.example.json`, ni u poruci commita.

## Endpoint

```
POST https://www.google.com/speech-api/v2/recognize
     ?client=chromium&lang=sr-RS&key=<javni>&pFilter=0
Content-Type: audio/l16; rate=16000
```

Telo je sirov 16-bit PCM **ili FLAC** uz `audio/x-flac; rate=N` — isključivo taj
zapis tipa, jer bez `rate=` i sa `audio/flac` vraća 400. FLAC štedi 36–42%.
Opus je odbijen. Odgovor je **više JSON linija**, prva obično prazna.
~31 KB po sekundi govora. Praktična granica ~30s po zahtevu. Izmereno: 20/20
uzastopnih i 5/5 paralelnih zahteva prolazi, bez 429.

Nedokumentovan je i ključ je javni — Google ga može ugasiti bez najave. Kod već
hvata 403/429 sa jasnom porukom.
