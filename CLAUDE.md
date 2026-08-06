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

**Apostrof ide sa ostalim znacima.** Endpoint ga vraća u „je l'", „ć'š", i to u
oba oblika — pravom (`'`) i krivom (`\u2019`). Oba moraju u pravilo, zajedno sa
jednostrukim navodnicima; jedan bez drugog ostavlja pola slučajeva.

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
| Emoji regex preko para surogata u Kotlinu | `[\uD83C-\uDBFF][\uDC00-\uDFFF]` ne uhvati ništa | Java regex radi nad kodnim tačkama — piši `\x{1F000}` |
| `dict` sa `rumps.MenuItem` kao ključem | `TypeError: unhashable type` pri pokretanju | lista parova |
| Zabrana sređivanja samo u promptu | model svejedno vrati velika slova i interpunkciju kad prepisuje | posle poziva ponovo kroz naša pravila |
| Prekidač koji prikazuje `profanity_filter` kakav jeste | jedini u aplikaciji stoji isključen, deluje kao greška | prikaži obrnuto („Ne maskiraj…"), upis `!it` |
| Završni razmak poslat kao unicode događaj | ostane sam u svom komadu, deo aplikacija ga odbaci — sledeći diktat se zalepi za prethodnu reč | spoji ga sa komadom ispred; **ne** šalji kao zaseban taster |
| …a taster razmaka kao „popravka" toga | pravi taster i unicode idu različitim putem kroz sistem, pa razmak stigne kasno — usred sledeće reči („sto" → „st o") ili udvojen | jedan te isti put za ceo tekst |
| `delovi[-2] += delovi.pop()` | `pop` skrati listu pre upisa, pa `-2` gađa pogrešan element (`IndexError` na dva komada) | prvo `pop` u promenljivu, pa upis |
| `node.text` kao „postojeći tekst" polja | prazno polje vraća svoj **natpis** — „Message" u ćaskanju — pa se on upiše ispred izdiktiranog | tri signala: prazno / `isShowingHintText` / jednako `hintText`; kursor (`textSelection >= 0`) potvrđuje stvaran sadržaj |
| …a kad nijedan signal ne presudi | pogrešna procena ili upiše natpis ispred, ili **obriše** korisnikov tekst | tada se `SET_TEXT` ne koristi uopšte — pada na `PASTE`, koji ne može da promaši |
| Rep u običnom režimu isporučen sa tiketom 0 | raniji diktat u istom servisu je pomerio `expected`, pa nula zauvek čeka red — pilula ostaje sa ciframa | pusti ga kroz `ship()`, koji dodeljuje pravi tiket |
| PASTE kao prvi način upisa na Androidu | Android 13+ prikaže sistemsko „kopirano" pri svakom `setPrimaryClip`, posle svakog diktata | `ACTION_SET_TEXT` prvi (ne dira clipboard), PASTE tek kao rezerva |
| Zastavica „poslednji segment" obrađena po DOLASKU poruke | rep je kratak pa se prepozna pre dužeg segmenta ispred sebe — obrada ne krene, pilula ostane sa ciframa, tekst se nikad ne upiše | zastavica važi za segment koji **izlazi iz reda**, ne za onaj koji stigne |
| `handler.removeCallbacksAndMessages(null)` pri zaustavljanju | briše i `deliver` poruke koje su radne niti već postavile — segment nestane, `expected` stane, pilula zauvek narandžasta | skidaj **samo svoj** Runnable (`removeCallbacks(tickRunnable)`) |
| `handler.postDelayed(::tick, …)` pa `removeCallbacks(::tick)` | `::tick` pravi nov objekat svaki put, pa nema šta da se skine | čuvaj jedan `Runnable` u polju |
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

**„Pošto" ne ide u podrazumevane skraćenice.** Znači i „procenata" i „budući
da", pa bi zamena pokvarila drugu upotrebu. U listi stoji samo `procenata=<%`,
koje je jednoznačno. Isto pravilo važi za svaku reč sa dva značenja.

**Clipboard se ne dira bez potrebe.** Vraćanje starog sadržaja posle lepljenja
ne pomaže: hvatači istorije (Raycast, Maccy, Paste) zabeleže svaku izmenu pre
nego što se stari sadržaj vrati, pa se istorija puni diktatima. Zato macOS
podrazumevano **kuca** tekst (`insert_method: auto`). Izuzetak je tekst sa novim
redom — kucanje ga šalje kao Enter, što u ćaskanju pošalje poruku usred diktata;
takav tekst ide preko clipboard-a. Android isto: `ACTION_SET_TEXT` prvi, PASTE
samo kad se ne zna šta je u polju.

**Skraćenice postoje na obe platforme.** Mac ih je dobio kasno (`dictate/abbrev.py`),
pa se pravila prenose 1:1 iz `Abbreviations.kt` — `<` jede razmak ispred, `~`
je regularni izraz, `{1}` je grupa, poslednji red pobeđuje. Ako se logika menja,
menja se na oba mesta; testovi postoje i tamo i ovde.

**Podrazumevane skraćenice utiču samo na nove instalacije.** Postojeća ima svoja
pravila sačuvana; pokupi nova tek dugmetom u aplikaciji.

**Regex pravila (`~`) primenjuju se pre prostih.** Inače `dolara=$` pojede reč
pre nego što `~(\d+)\s*dolara={1}` stigne da premesti simbol ispred cifre.

---

## Kako se proverava izmena

**macOS** — posle svake izmene pokreni aplikaciju i **proveri da je proces
živ**, ne samo da nema greške u prevođenju. Dva pada su uhvaćena samo ovako:

```bash
./run.sh tests           # 53 testa logike, bez mikrofona i mreze
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

**Glavni prekidač AI obrade se ne ukida.** Bez njega bi gašenje obrade značilo
gašenje svakog alata pojedinačno — i gubitak izbora. Alati su zato podelementi:
uvučeni i zasivljeni dok je glavni isključen. Na macOS-u se sivi **skidanjem
callback-a**, ne sa `setEnabled_`: NSMenu sam uključuje stavke koje imaju akciju,
pa bi `setEnabled_` bio pregažen pri sledećem otvaranju menija.

**Alati AI obrade su nezavisni; uputstvo se sklapa od izabranih.** Sređivanje
(interpunkcija, velika slova, kvačice) je samo jedan od njih. Kad ono nije
izabrano, modelu se **izričito zabranjuje** da dira interpunkciju — inače je
dodaje svejedno, jer mu je to najočekivanija radnja nad sirovim transkriptom.
Isto važi za prelamanje: bez `NE_PASUSI` lomi tekst u redove i kad pasusi nisu
traženi. Nijedan alat izabran = nema poziva; `_formal()` tada mora da bude
`False`, inače diktat visi čekajući prazan poziv.

**Sirov tekst ide modelu samo kad on sređuje.** Ako sređivanje nije izabrano,
naša pravila (skraćenice, kvačice, interpunkcija) moraju da odrade svoje pre
slanja — i **ponovo posle njega**. Model sređuje tekst čim prepisuje rečenice,
makar mu bilo zabranjeno: sažimanje ih vraća pravopisno uredne, sa velikim
slovima i interpunkcijom. Uputstvo to ne rešava pouzdano, pa presuđuju pravila
u kodu. Pravila se tada primenjuju **po pasusu**, jer `strip_punctuation`
skuplja razmake i pojeo bi prazne redove.

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

**Provera snimka ide JEDNIM pozivom za ceo diktat.** Po segmentu je trošila 6–9
poziva na jednu diktiranu poruku (neprekidni režim sa `segment_after_seconds: 0`
seče na svakoj pauzi), a model je video krhotinu umesto celine. Zvuk se drži u
memoriji do kraja diktata, pa postoji granica `audio_check_max_seconds` (120s):
preko nje se više ne čuva — neprekidni režim ume da traje satima. Segmenti se
pamte **po tiketu**, jer se prepoznaju paralelno pa bi redosled inače bio
proizvoljan. Otkazan diktat mora da isprazni taj bafer, inače bi model u
sledećoj proveri „čuo" prethodni diktat.

**Sređivanje se ne radi dvaput.** Prolaz u kome model sluša snimak vraća tekst
sa interpunkcijom, velikim slovima i kvačicama — pa je poseban poziv za „sredi
tekst" bio drugi poziv za isti posao. Izmereno: vraćao je **identičan** tekst za
0.7s. Zato `tools(cfg, vec_sredjeno=True)` izbacuje `tidy`; ako ništa drugo nije
izabrano, drugog poziva uopšte nema. Uz to prvi prolaz sada **izričito** dobija
zadatak da piše pravilno (`SREDI_DEO`), da oblikovanje ne bi zavisilo od sreće.

**Model koji sluša snimak mora da dobije i prvi prepis.** Izmereno (greška po
reči, tri rečenice, SNR 5 dB): Web Speech 0.30, Gemini sam 0.29, Gemini uz
prepis **0.17**. Sam model u šumu **halucinira** — vratio je „poslao sam ponovo
250.000 dinara u 1:33" umesto „...ponudu... u utorak u deset i trideset". Kad ne
čuje, dopuni umesto da ostavi rupu; prvi prepis mu je sidro.

**Skraćenice i strani nazivi su najslabija tačka endpointa.** Izmereno: „AI"
postane „pa" ili „i", „Gemini" postane „gemini", „na Androidu" postane „na and".
Zato uz snimak ide `vocabulary` — spisak pojmova sa uputstvom da se napišu tačno
tako. Merenje na pet rečenica: WER 0.197 → 0.080, bez greške 1/5 → 4/5.

**Endpoint sam piše većinu engleskih reči izvorno.** Izmereno: `deploy`,
`build`, `push`, `screenshot`, `dashboard` prolaze bez pomoći. Greši na
**skraćenicama** (`AI` → `pa`/`i`) i na oblicima koji zvuče srpski (`brenč`).
Zato uputstvo ima i pravilo („engleske reči piši izvorno") pored spiska — samo
pravilo je jednom dalo nepostojeće `repositorijum`, pa idu zajedno.

**Pouzdanost endpointa nije merilo tačnosti.** Izmereno: prepis sa odsečenom
rečju („...sastanak sa kolegama iz kragu") prijavljen sa 0.93, isto koliko i
tačan. Zato je „šalji samo kad je pouzdanost niska" podrazumevano isključeno —
štedi podatke, ali ne hvata greške. Ne gradi logiku koja veruje tom broju.

**FLAC na Mac-u ide preko `ffmpeg`-a, ako ga ima.** Python nema ugrađen enkoder,
a dodavati zavisnost zbog uštede nije vredno. Mereno: 132 KB → 84 KB (36% manje),
isti prepis i ista pouzdanost. Bez `ffmpeg`-a se šalje PCM kao i pre — ušteda ne
sme da obori diktat.

**Modelu ide AAC, endpointu FLAC.** Izmereno na istom snimku: WAV 139 KB, FLAC
85 KB, **AAC 32 kbps 18 KB** — prepis identičan u sva tri. Model gubitno
sažimanje ne primeti, a na telefonskom uplinku je baš ta veličina bila glavni
razlog čekanja. Endpointu se AAC **ne sme** slati: prima samo PCM i FLAC.
Kašnjenje modela je pri tom skoro isto za sve (`flash-lite` 1.9–2.1s,
`2.5-flash-lite` 1.3s), pa se ubrzanje traži u veličini, ne u izboru modela.

**ADTS zaglavlje se piše rukom.** `MediaCodec` vraća sirove AAC okvire bez
kontejnera; ispred svakog ide 7 bajtova zaglavlja, inače je tok neupotrebljiv.
Zato postoji `AacHeaderTest` — ta računica se ne menja bez testa.

**Završna podešavanja se u formalnom režimu primenjuju POSLE modela.** Tekst mu
ide nedirnut (tako bolje čita), pa bi inače potpuno izostala — korisnik to vidi
kao „skraćenice su prestale da rade". Posle njega idu **spoji hiljade,
skraćenice i skidanje kvačica**; mala slova i brisanje interpunkcije **ne** —
to je baš posao koji je model dobio, pa bi jedno gasilo drugo.

**Svaki diktat ima svoju sesiju.** Nov diktat sme da počne dok se prethodni
obrađuje, pa se tekst i zvuk drže **po sesiji**: u zajedničkoj kanti bi dva
diktata završila u jednom pozivu i zalepila se spojena. Završetak se meri po
sesiji (`_pending_by`), ne po tome da li mikrofon radi — čekanje na miran
mikrofon je upravo ono što ih je spajalo.

**Zvuk se modelu šalje u poznatom formatu.** `inline_data` prima `audio/wav` i
`audio/flac` (provereno); sirov PCM ne. base64 uveća zvuk za trećinu, pa provera
snimka udvostručuje saobraćaj — otud odvojen prekidač, a ne stalno ponašanje.

**Izgled teksta ima dva stanja, ne tri prekidača.** „Sredi tekst", „sve malim
slovima" i „bez interpunkcije" su mogli da budu uključeni istovremeno, a ishod
je zavisio od redosleda u kodu. Sada je `text_style`: `spoken` (podrazumevano)
ili `written`, a `lowercase`, `strip_punctuation` i `polish_tidy` se iz njega
**izvode**. `raw` je postojao pa uklonjen — bio je treći ishod za isto pitanje.
Ne vraćaj ih kao zasebna podešavanja.

**Ispravljanje grešaka je deo sređivanja, ne izbor.** Nivo „samo oblikuj"
(`polish_level`) niko nije koristio, a prekidač je stajao siv jer zavisi od
sređivanja. Sve što model radi nad tekstom stoji u jednoj grupi (AI), uključujući
i „bez kvačica" koje se primenjuje posle njega. Naziv prekidača ne pominje
kvačice: njih vraća samo prepoznavanje, a skida ih zaseban prekidač — dva
mesta za istu stvar zbunjuju.

**Zatečena podešavanja se prevode, ne brišu.** `_migrate` (Mac) i `Config.textStyle`
(Android) izvode stil iz starih ključeva pri prvom čitanju. Isto važi za svako
buduće spajanje podešavanja — korisnik ne sme da izgubi ono što je namestio.

**Jezik izlaza je slobodan opis, ne spisak.** Korisnik ume da traži „pola
makedonski pola srpski" — spisak jezika to ne pokriva, a model razume iz opisa.
Prevod mora da uđe u `_sme_da_menja`, inače provera vernosti obori ceo izlaz
(prevod po prirodi menja svaku reč), i isključuje granicu „ne preformuliši".

**AI prepoznavanje i AI obrada su odvojene sekcije.** Prvo šalje ZVUK i traje
~10s na 20s diktata; drugo šalje samo tekst i vraća se za sekundu. Držati ih
zajedno je krilo tu razliku. Obična podešavanja (`Tekst`) idu **posle** AI-ja i
imaju poslednju reč — to mora da piše u samoj kartici, ne samo u dokumentaciji.

**Ono što je model usput sredio ne preskače izbor korisnika.** Prolaz u kome
model sluša snimak vraća tekst sa tačkama i upitnicima; ranije se zbog toga
preskakalo pravilo za stil `spoken`, pa je znak pitanja bio tu kad je provera
snimka uspela, a nestajao kad nije (predugačak diktat, otkaz poziva). Odluku
donosi **samo** `text_style`, nikad „model je već formatirao".

**Meni se posle klika sam zatvara i to se ne može isključiti.** NSMenu nema
javni API za to; jedini način je da se odmah otvori ponovo
(`button.performClick:` sa malim odlaganjem). Otvara se na prvom nivou, pa se u
podmeni ulazi još jednom — to je granica, ne propust.

**Lista mikrofona se osvežava iz delegata podmenija** (`menuNeedsUpdate:`), ne
ručnom stavkom. Sam snimak to nikad nije pogađalo — uređaji se osvežavaju pred
svaki diktat — ali je izbor u meniju lagao dok se slušalice priključe.

**Ono što se ne koristi — izlazi.** Uklonjeni su emotikoni (cela logika, uz
testove), izbor ulaznog jezika, ponavljanje neuspelih diktata iz menija, debug
prekidač, otvaranje `config.json` i stavka sa statusom: menu-bar ikonica već
pokazuje stanje. „Spoji hiljade" i „razmak na kraju" su uvek uključeni, pa nisu
podešavanja nego ponašanje. Podešavanje koje stoji **sivo** je gore od
nepostojećeg: „ispravi greške" se sada ne vidi dok stil nije „Sređeno".

**Meni je grupisan po pitanju na koje odgovaraš**, ne po tome kad je šta
nastalo: Snimanje (kako), Tekst (kako izgleda), AI (šta model radi). Pre toga je
bilo 12 stavki u ravnom spisku i 11 kartica; sada 5 podmenija i 8 kartica.

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
