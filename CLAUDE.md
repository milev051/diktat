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

**„Neuspeo" znači i prazan prepis, ne samo izuzetak.** Web Speech ume da vrati
prazan rezultat za uredan govor: izmereno na tri sačuvana snimka (15.7s, 3.5s i
1.8s, vrh amplitude 0.31), svi vraćaju `""` i kao FLAC i kao sirov PCM. Ranije
se takav segment tiho gubio, pa se ostatak diktata zalepi bez njega i izgleda
kao da je stigao samo kraj govora. Sada `_recognize_or_keep` čuva snimak i kad
je prepis prazan, ako je duži od 1.0s i vrh amplitude preko 0.10 (tiha soba je
~0.01, bučna ~0.08). Ispod toga je stvarno tišina i ne čuva se, da se
`~/Diktat-neuspeli` ne puni prazninom.

**Apostrof ide sa ostalim znacima.** Endpoint ga vraća u „je l'", „ć'š", i to u
oba oblika — pravom (`'`) i krivom (`\u2019`). Oba moraju u pravilo, zajedno sa
jednostrukim navodnicima; jedan bez drugog ostavlja pola slučajeva.

**Interpunkcija se ne briše slepo.** Endpoint vraća zarez kao decimalni
separator (`3,5`) i dvotačku kao satnicu (`10:00`). Tačka, zarez **i dvotačka**
brišu se **samo kad nisu između cifara**; crtica i kosa crta samo kad stoje
same, da `crno-beli` i `and/or` ostanu celi. Uslov za crtu je `\w`, ne `\d`:
sa `\d` je pravilo godinama tvrdilo jedno a radilo drugo, jer slovo nije cifra,
pa je `crno-beli` ipak postajao `crnobeli`. Kad dokumentacija i test tvrde
suprotno, **test je taj koji je zabeležio stvarno ponašanje** — proveri koje je
od to dvoje pogrešno pre nego što popraviš. Svaki znak koji može da stoji između cifara mora u tu
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
| Live: zvuk poslat tek posle Stop-a | čekanje raste sa dužinom diktata — 15.6s na 64.7s zvuka | strimuj u toku snimanja; čekanje padne na 0.0s |
| …a strim provučen kroz ponavljanje | komadi sa mikrofona se čitaju jednom, drugi pokušaj šalje prazno | bez ponavljanja; snimak na disk pa u `~/Diktat-neuspeli` |
| Krnji komad poslat kao svoj okvir | mikrofon ne isporučuje na granici od 100ms — prepoznavanje se lomi po sredini reči | nosi ostatak u sledeći prolaz |
| Live API: prekid čitanja na `generationComplete` | ta zastavica stiže posle **svake** izgovorene celine, ne na kraju diktata — od 17s govora stigne samo prva rečenica | čitaj dok ne **utihne** (kratak timeout), skupljaj sve `inputTranscription` |
| …a zvuk poslat bez repa tišine | poslednja celina ostane na međurezultatu i nikad se ne finalizuje — izmereno 2 od 3 | dodaj ~2s tišine pre `audioStreamEnd` |
| `selftest.py` zvao Google ma šta bilo izabrano | `./run.sh test` prolazi dok je pravi izvor pokvaren | alat ide kroz isti izbor izvora kao aplikacija |
| STOP koji stigne dok `_on_start` još čeka mikrofon | `_recorder` je još `None`, pa STOP nema šta da zaustavi — snimanje krene odmah posle njega i **više ne staje**; taster deluje mrtvo | brojač `_starting` i zastavica `_stop_requested`; pokretanje ih pokupi pod istim katancem |

---

## Zašto je nešto tako a ne drugačije

**Google nedosledno vraća valute.** Izmereno: „sto dinara" → `100` (valuta
nestane), „petsto dinara i dvadeset evra" → `500 RSD i 20`. Pravilo `dinara=…`
zato često nema šta da uhvati; hvata se `rsd=…`. Kad Google izostavi valutu,
aplikacija nema šta da vrati.

Ponovljeno 04.09.2026. preko `say -v Lana` (hrvatski glas je fonetski dovoljno
blizak) pravo na endpoint, `lang=sr-RS`:

| izgovoreno | endpoint vrati |
|---|---|
| sto dolara | `100` (valuta nestane) |
| petsto dinara i dvadeset evra | `500 RSD i 20` (samo prva valuta) |
| tri hiljade petsto dinara | `3.500 r` (valuta odsečena) |
| dvadeset procenata | `20%` |
| petnaest minuta | `15 minuta` |
| dvadeset kilometara | `20 km` |
| deset kilograma | `10 kg` |
| deset i trideset | `10:30` |
| dve hiljade dvadeset šeste godine | `2026 godine` (bez tačke) |

Obrazac je jasan: **jedinice i vreme endpoint pogađa pouzdano, valute ne.**
Zato se logika ne sme graditi na tome da valuta stigne; `%`, `km` i `kg` su
pouzdani, `dinara`/`dolara`/`evra` nisu. Redni broj i godina stižu bez tačke,
pa je dodaje model (`gemini-3.5-flash` nad „bilo je 2026 godine" vraća
„Bilo je 2026. godine").

**Google Cloud motor je obrisan.** Davao je prikaz reč-po-reč, ali je tražio
nalog, karticu i `grpcio`. Besplatni endpoint radi za srpski (izmereno 0.93) i
nema podešavanja. Ne vraćaj ga bez izričitog zahteva.

**`gemini-3.5-transcribe-live` je treći izvor transkripcije.** Live API preko
WebSocket-a, isti ključ kao AI obrada (`polish_api_key`), podržava `sr-RS`.

**Obična varijanta `gemini-3.5-transcribe` je isprobana pa uklonjena.**
Besplatne kvote (AI Studio → Rate Limit, 28.08.2026):

| model | RPM | TPM | RPD |
|---|---|---|---|
| `gemini-3.5-transcribe` | 3 | 10K | **25** |
| `gemini-3.5-transcribe-live` | bez granice | 20K | **bez granice** |

Dvadeset pet zahteva dnevno ne znači ništa za svakodnevni rad, a 3 u minuti bi
davilo i bez toga. Live nema ni jednu ni drugu granicu; 20K tokena u minuti je
oko 800s zvuka (25 tokena po sekundi), što diktat ne može da dostigne. Ne
vraćaj običnu varijantu bez izričitog zahteva — `_migrate` zatečeno `"gemini"`
obara na `"google"`.

**Obrada ide POSLE snimanja, ne u toku.** Cela sesija je jedan WebSocket poziv
nad gotovim snimkom (`_transcribe_whole`): poveži se, pošalji zvuk, uzmi prepis,
zatvori. Model tako vidi ceo diktat umesto krhotina odsečenih na pauzama — isti
razlog iz kog formalni režim zove model jednom, na kraju. „Live" je ime modela,
ne prikaz reč-po-reč; taj bi tražio da se ceo tok snimanja preokrene u streaming.

Uz njega se **gasi druga provera snimka** (`_own_audio_model`): `audio_check` i
Groq postoje zato što besplatni Web Speech greši, a slati isti zvuk još jednom
slabijem modelu je dupli saobraćaj za lošiji rezultat. AI obrada teksta (prevod,
tačke, pasusi) ostaje netaknuta.

**Zvuk se strimuje DOK snimanje traje, ne posle Stop-a.** Izmereno na 64.7s
zvuka: slanje posle Stop-a ostavlja **15.6s** čekanja, slanje u toku **0.0s** —
server stiže u realnom vremenu, pa je prepis gotov u trenutku kad pustiš taster.
Broj prepoznatih celina je isti (11). Čekanje kod „sve odjednom" raste sa
dužinom diktata, pa je na dugom diktatu to jedina stvar koja se oseti.

**Cena je pri tom ista, jer se naplaćuje zvuk, a zvuk je isti.** Izmereno na
22.7s: u oba slučaja ~568 audio tokena i **4 konačna prepisa od 203 znaka**.
Razlika je samo u međurezultatima: 6 poruka (84 znaka) naspram 28 poruka
(869 znakova). Strim traje duže pa ih pošalje više. Da li se oni uopšte
naplaćuju nije objavljeno; i ako jesu, uz besplatan nivo (bez granice RPM/RPD)
to ništa ne menja.

**Strimovanje traži internet DOK snimanje traje, i troši 2,5 MB po minutu.**
Izračunato: 16 kHz × 16 bita = 31 KB/s sirovog zvuka, base64 ga uveća za
trećinu, plus JSON omot — 42 KB/s odlaznog saobraćaja. Live API prima **samo
sirov PCM** (`audio/pcm;rate=16000`), FLAC se ne može poslati, pa je to
dvostruko više nego Google Web Speech uz FLAC (~1,1 MB/min). Ukupna količina je
ista bilo da se šalje u toku ili posle Stop-a — razlika je samo u trenutku.
Ovo je bitno na telefonu: prekid veze usred diktata sada obara diktat, dok je
ranije mreža trebala tek na kraju.

**Mana strimovanja: nema drugog pokušaja.** Komadi sa mikrofona se čitaju samo
jednom, pa `recognize_live_stream` namerno NE ide kroz `_sa_ponavljanjem` —
drugi pokušaj nema šta da pošalje. Zato `_transcribe_live` usput piše zvuk na
privremeni disk (ne u listu — sat vremena je preko 100 MB) i pri otkazu ga
sačuva u `~/Diktat-neuspeli`, odakle se ponavlja rukom (`./run.sh replay`).

**Posle strimovanja, sve što se još čeka je NAŠA pauza.** Izmereno na snimcima
koji staju usred govora (8.5s i 26.6s): poslednji prepis stigne **0.5s** posle
Stop-a, i to **ne zavisi od dužine diktata**. Sve preko toga bio je
`LIVE_IDLE_SECONDS`. Ni na 0.8s se ne izgubi nijedna celina — server je stigao
dok se šalje rep tišine.

Zato dva roka umesto jednog:

| rok | kada važi | zašto |
|---|---|---|
| `LIVE_QUIET_SECONDS` (1.0s) | poslednja celina finalizovana | tišina tada stvarno znači kraj |
| `LIVE_IDLE_SECONDS` (3.0s) | međurezultat bez svog finala | celina je u letu, prekid bi je odsekao |

Ukupno čekanje posle Stop-a: **3.5s → 1.5s**, mereno kroz `recognize_live_stream`.

**Najveći razmak između poruka je 0.47s u strim režimu**, a 1.4s u batch režimu
— tamo server pacira sam sebe kroz nagomilan zvuk. Zato se rok sme skratiti tek
uz strimovanje. Tok se uvek završava obrascem
`… FINAL → generationComplete → prazno →` tišina; **`turnComplete` ne postoji**,
pa čistog signala za kraj nema i tišina ostaje jedini.

**`generationComplete` NIJE kraj diktata.** Izmereno na snimku od 19s sa dve
pauze: stigao je **tri puta**, posle svake izgovorene celine. Prekid na njemu je
odbacivao sve posle prve pauze — od 17 sekundi govora stizala je samo prva
rečenica. Čitanje se zato završava **tišinom**: posle zvuka server ne zatvara
vezu nego šalje prazne `serverContent` poruke dok radi, pa stane. Izmereni
razmaci između poruka dok radi su do 0.9s, otud `LIVE_IDLE_SECONDS = 3.0`.

**Bez repa tišine poslednja celina se ne finalizuje.** Izmereno na istom snimku:
bez repa stignu **2 od 3** konačna prepisa, sa 2s tišine sva tri. Zato se pred
`audioStreamEnd` doda `LIVE_TAIL_SILENCE` (2s) nula. Ako i pored toga poslednja
celina ostane samo na međurezultatu, uzima se on — pola prepisa je bolje nego
ništa.

**Zvuk se šalje punom brzinom, ne u realnom tempu.** Izmereno: isti rezultat,
11.5s naspram 28.7s. Ne usporavaj slanje „da bi ličilo na stream".

**Live vraća ćirilicu za `sr-RS`, i to nedosledno** — u istom diktatu i
„тест тест" i „Test test". Projekat je latinični (Android isto), pa
`post_process` prvo poravna pismo kroz `openai.to_latin`.

**Razlog otkaza stiže u CLOSE okviru i mora da se pročita.** Izmereno na živom
endpointu: mrtav ključ se javlja kao `CLOSE 1007: API key not valid`, a ne kao
greška pri rukovanju. Bez čitanja tog okvira korisnik vidi „veza zatvorena" i
nema pojma gde je problem. 1007 se **ne ponavlja** — nosi i pogrešan ključ i
pogrešan `setup`, oba su naša greška.

**Sve je provereno na živom endpointu** (28.08.2026, sa važećim ključem):
rukovanje, `setupComplete` na naš `_live_setup`, prepis kroz `inputTranscription`,
čitanje CLOSE razloga. Snimak od 19s se prepiše za ~9s.

**WebSocket klijent je pisan rukom** (`dictate/wsock.py`), bez `websockets`.
Ceo projekat priča sa mrežom preko `urllib`, a Live API nam treba samo za jedan
tok: pošalji JSON okvire, čitaj JSON okvire, zatvori. `websockets` bi uvukao
asyncio u kod koji je ceo sinhron i nitima vođen.

**GUID iz RFC 6455 je `258EAFA5-E914-47DA-95CA-C5AB0DC85B11`.** Prekucan je
pogrešno iz glave (`…-95CA-5AB0DC85B11D`, slovo `C` odlutalo) i to je prošlo
kroz sve testove okvira — greška se videla tek kao „Pogrešan Sec-WebSocket-Accept"
nad savršeno ispravnim 101 odgovorom. Zato se konstanta proverava **vektorom iz
samog RFC-a** (`dGhlIHNhbXBsZSBub25jZQ==` → `s3pPLMBiTxaQ9kYGzzhZRbK+xOo=`), ne
nasumičnim ključem. Isto pravilo kao za ADTS zaglavlje: što se sklapa bit po bit,
ima test sa poznatim odgovorom.

**`gemini-3.5-live-translate-preview` ne može da zameni naš prevod.** Provereno
28.08.2026. u zvaničnoj dokumentaciji: prima **samo zvuk** („Text input is not
supported"), radi isključivo preko WebSocket Live API-ja, i uvek vraća zvuk —
prepis je samo dodatak (`outputAudioTranscription`). Naš prevod radi nad **već
gotovim transkriptom**, pa mu taj model nema šta da ponudi. Uz to: nema
besplatnog nivoa (ulaz 3,50 $ / izlaz 21,00 $ po milionu tokena, ~0,037 $ po
minutu) i ne prima ni `vocabulary` ni naše uputstvo. Srpski jeste na spisku,
kao `sr` (ne `sr-RS`). Ne pokušavaj ponovo bez
izričitog zahteva — jedini smislen oblik bio bi zaseban režim „diktiram na
jednom jeziku, ubacuje se na drugom" koji zaobilazi ceo postojeći put.

**`pFilter=0` gasi maskiranje psovki.** Ime parametra je **osetljivo na velika
slova** — `pfilter` se tiho ignoriše.

**Gemini Transcribe Live postoji na OBE platforme.** `GeminiStt.kt` i
`WSock.kt` su prevod `dictate/geministt.py` i `dictate/wsock.py` — iste
konstante, isti redosled poruka, isti razlozi. Ako se logika menja, menja se na
oba mesta; testovi postoje i tamo i ovde.

**WebSocket na Androidu je isto pisan rukom**, bez OkHttp. Aplikacija nema
nijednu mrežnu zavisnost (sve ide preko `HttpURLConnection`), a APK je ceo
1,7 MB — biblioteka od par stotina kilobajta zbog jednog toka se ne isplati.

**`org.json` u JVM testovima je prazan kalup.** `unitTests.isReturnDefaultValues`
znači da `JSONObject` vraća podrazumevane vrednosti umesto da parsira, pa je
svaki test nad JSON odgovorom tiho prolazio na praznom. Zato
`testImplementation("org.json:json")` — bez toga provera imena polja ne vredi
ništa.

**Android: bočni taster je prekidač, ne držanje.** Sistem šalje samo
„pokreni"; događaj za puštanje ne postoji.

**Android: `LanguageDetailsReceiver` mora da postoji.** Samsung tastatura pita
servis koje jezike zna; bez odgovora pretpostavi engleski i odbije srpski.
Gboard to ne pita.

**Boja u menu baru ide preko `nsstatusitem.button().setAttributedTitle_`**, jer
`rumps.title` ne ume boju. Font mora biti `monospacedDigit` — inače se širina
naslova menja svake sekunde i ostale ikonice poskakuju.

**`da li` se ne skraćuje.** „da l" izgleda krnje bez „i"; „je l" je ustaljeno i
ostaje. Skraćenica mora da bude oblik koji se i tako piše, ne samo kraći niz.

**Prepoznavanje `svejedno` vraća i rastavljeno**, pa su u spisku oba oblika
(`svejedno` i `sve jedno`). Isto proveri za svaku novu složenicu — jedan oblik
u spisku hvata pola slučajeva.

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
./run.sh tests           # testovi logike, bez mikrofona i mreze
./run.sh doctor          # dozvole, mikrofon, endpoint
./run.sh test 20         # snimi 20s SA PAUZAMA i ispiši šta je čuo
./run.sh replay          # pusti poslednji neuspeo snimak kroz isti put
./run.sh replay ~/x.wav  # ili odredjen snimak
```

**`test` i `replay` idu kroz IZABRANI izvor**, isti izbor koji radi i
`DictateApp._recognize`. Ranije je `selftest.py` uvek zvao Google, pa je greška
u drugom izvoru prolazila neprimećeno — tako je bug „stane na prvoj pauzi" i
preživeo.

**Dug diktat se testira samo pauzama.** Greška je bila u tome što se prekidalo
posle prve izgovorene celine, a snimak od 5s ima samo jednu — prolazio je uredno.
Zato `./run.sh test 20` izričito traži da praviš pauze, a ispis nosi i **broj
reči na sekundu zvuka**: kratak prepis za dug snimak znači da se nešto izgubilo.

**`replay` je najbrži put do ponovljene greške.** Neuspeli diktati se ionako
čuvaju u `~/Diktat-neuspeli`, pa se ista greška posmatra bez mikrofona i bez
slučajnosti. Snimci se mogu i spajati sa tišinom između, da se dobije diktat sa
više celina.

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

**Glavnog prekidača AI obrade više nema.** Izabran alat sam po sebi znači da se
AI koristi; prekidač je bio korak koji ništa nije odlučivao, a umeo je da stoji
isključen dok su alati izabrani. Bez ključa nema ničega — to je jedini uslov.
Zatečeno `polish: false` pri prvom čitanju **gasi i alate**, da se AI nikom ne
upali sam od sebe.

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

**`gemini-3.5-flash` primetno bolje sređuje od `flash-lite`.** Izmereno na istim
ulazima (04.09.2026):

| ulaz | `gemini-3.5-flash` | `gemini-flash-lite-latest` |
|---|---|---|
| `da li je ovo tačno nzm još` | `Da li je ovo tačno? Ne znam još.` | `Da li je ovo tačno, nzm još.` |
| `popusti je 20%` | `Popust je 20%.` | `Popusti je 20%.` |
| `ovo je 3500 r` | `Ovo je 3500 RSD.` | `Ovo je 3500 r.` |

Flash ispravlja i ono što lite propušta, ali na besplatnom nivou lako udari u
429 (izmereno: tri uzastopna poziva prolaze, četvrti pada). Zato podrazumevani
ostaje `flash-lite`; flash je izbor kad je tačnost preča od kvote.

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

**Ni kao „podrazumevana vrednost".** Ugrađeni ključ je duže vreme stajao u
`dictate/config.py` i `Config.kt`, uz obrazloženje da nova instalacija odmah
radi. To je dvostruka greška: svaka kopija aplikacije troši tuđi nalog, a
korisnik nema po čemu da primeti da mu ključ fali, pa svoj nikad i ne unese.
Uz to ključ ostaje u istoriji commita zauvek, i brisanje iz fajlova ga ne
uklanja. Podrazumevana vrednost je `""` na obe platforme; zatečen ključ u
`config.json` i `SharedPreferences` se ne dira.

**Javni Chromium ključ u `webstt.py` i `WebStt.kt` je izuzetak.** On nije ničiji
nalog, isti je u svakoj Chromium instalaciji i bez njega besplatni Web Speech
endpoint ne radi. Zato u oba fajla stoji komentar da se ne obriše u nekoj
budućoj čistki ključeva.

**Provera snimka ide JEDNIM pozivom za ceo diktat.** Po segmentu je trošila 6–9
poziva na jednu diktiranu poruku (neprekidni režim sa `segment_after_seconds: 0`
seče na svakoj pauzi), a model je video krhotinu umesto celine. Zvuk se drži u
memoriji do kraja diktata, pa postoji granica `audio_check_max_seconds` (120s):
preko nje se više ne čuva — neprekidni režim ume da traje satima. Segmenti se
pamte **po tiketu**, jer se prepoznaju paralelno pa bi redosled inače bio
proizvoljan. Otkazan diktat mora da isprazni taj bafer, inače bi model u
sledećoj proveri „čuo" prethodni diktat.

**Groq je zasebna alternativa za proveru snimka.** `groq_enabled` +
`groq_api_key` uključuju dva poziva za ceo diktat: WAV ide na Whisper, a
`openai/gpt-oss-120b` dobija Google i Whisper prepis i vraća konačan tekst.
Kada je Groq uključen, ima prednost nad Gemini `audio_check` prolazom da se
audio ne šalje dvaput. Mac i Android moraju imati istu logiku i podrazumevane
modele (`whisper-large-v3`, `openai/gpt-oss-120b`). Ako bilo koji Groq poziv
padne, zadržava se Google prepis; brojač AI poziva tada ne sme da spreči diktat.
API ključ se nikad ne upisuje u git.

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

**„Pravilno" je prečica nad četiri prekidača, ne peto podešavanje.** Mala
slova, brisanje interpunkcije, skidanje kvačica i skraćenice — svaki od njih
udaljava tekst od pravopisa, pa „pravilno" znači: sva četiri ugašena. Četiri
klika za prelazak između dva stanja su četiri prilike da se jedan zaboravi, pa
tekst izađe na pola puta. Kvačica se **izvodi** iz ta četiri, nikad ne pamti
zasebno: inače bi ručno gašenje jednog ostavilo nad-prekidač da laže.

**Gašenje vraća ono što je bilo, ne podrazumevano.** `ascii_diacritics` je
podrazumevano isključen, pa bi povratak na podrazumevano tiho ukinuo izbor
onome ko ga drži upaljenog. Zapamti se samo pri **prelasku**; drugi poziv nad
već pravilnim stanjem ne pamti ništa, jer bi zapamtio sve ugašeno i povratak ne
bi vratio ništa. Odluke stoje u `Pravilno.kt` i `config.pravilno` /
`config.postavi_pravilno`, odvojene od `SharedPreferences` i `config.json` baš
zato što `Context` u JVM testovima vraća podrazumevane vrednosti, pa bi test
nad `Config`-om tiho prolazio na praznom.

**Dugme na piluli sme da se klikne jer prozor nije fokusabilan.** Pilula je
`FLAG_NOT_FOCUSABLE`, pa dodir stiže dugmetu a fokus ostaje u polju u koje
tekst treba da se upiše. To je ista zastavica zbog koje pilula uopšte postoji u
tom obliku; da je nema, klik na dugme bi oduzeo fokus i prepoznat tekst ne bi
imao gde da ode. Natpis nosi stanje (`Aa` pravopisno, `aa` kako si izgovorio):
pilula se gleda krajičkom oka usred diktata, gde dva slova kažu više nego bilo
koji simbol. Cena je što dugme širi prozor, a prozor guta dodire ispod sebe —
zato je usko (46dp) i stoji levo od brojača, uz samu ivicu.

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

**„Sažmi u tačke" i „podeli na pasuse" se isključuju.** Oba odgovaraju na isto
pitanje — kako je tekst prelomljen — pa tačke pobeđuju kad su izabrane. Alat
prepisuje rečenice, zato mora u `_sme_da_menja` i isključuje granicu „ne
preformuliši"; uz njega tekst završava **novim redom** umesto razmakom, da
sledeći diktat počne svoju tačku.

**Uz broj napisan REČIMA jedinica mora imati bar dva slova.** „jednom" je po
spiskovima „jedno" + „m", pa ga je `_SLEPLJENA_JEDINICA` lomila u „jedno m".
Isto „stos" („sto" + „s"), „stom" i „trim". Prekidač za skraćenice tu ne pomaže:
`normalize_spoken_numbers` radi i kad su skraćenice isključene, jer prekidač
gasi samo korisnička pravila zamene. Jednoslovne oznake (`m`, `h`, `s`) su zato
izbačene iz tog pravila; uz CIFRU ostaju, jer cifra ne može da napravi reč.
Ništa se ne gubi: prepoznavanje nikad ne vrati „petm" ni „trih", nego „pet
metara" ili „5 m". Mereno nad 2752 različite reči iz `CLAUDE.md` i `README.md`:
pre popravke su se lomile tri (`jednom`, `JEDNOM`, `trim`), posle nijedna, a
jedina preostala izmena je namerna (`minuta` → `min`). Isti test pokreni za
svaku buduću jedinicu na spisku, jer se sudar sa običnom rečju ne vidi drugačije.

**Uz cifru se lepi samo kratka oznaka, nikad cela reč.** „100dolara" i
„500dinara" izgledaju kao greška. Ranije je `_CIFRA_UZ_JEDINICU` lepio svaku
jedinicu sa spiska, pa je `normalize_spoken_numbers` razdvajala „100dolara" u
„100 dolara", a isti prolaz bi ih odmah zalepio nazad. Sada lepe samo `min`,
`sek`, `din`, `km`, `kg`, `m`, `h`, `s`. Troslovne oznake valuta (`eur`, `usd`)
ostaju sa razmakom, isto kao „5000 RSD" iz korisničkog pravila bez „<".
Provereno i da model to ionako poništava: `gemini-3.5-flash` nad „15min" vraća
„15 minuta", nad „20km" vraća „20 km".

**`%` se ne briše.** Izmereno na živom endpointu: „popust je dvadeset procenata"
vraća se kao „popusti je 20%", pa je brisanje `%` jelo jedini trag jedinice.
Model to ne može da nadoknadi, jer u tekstu koji dobije procenta više nema.
`$` i `€` nikad nisu ni bili u spisku za brisanje; sada je i `%` van njega.
Ostali simboli (`# & * + < = > @ ^ _ | ~`) se i dalje brišu.

**Znak između dva slova postaje razmak, ne ništa.** Uz stil „izgovoreno" se
interpunkcija briše, pa je „gotovo je.sada" postajalo „gotovo jesada". Zato
`strip_punctuation` prvo pretvori `.` `,` `:` `;` `!` `?` `…` koji stoji između
dva slova u razmak, pa tek onda briše ostatak. Apostrof i navodnici namerno
NISU u tom pravilu: „ć'š" mora da ostane jedna reč, ne „ć š". Ovo je isti kvar
koji uz pisani stil rešava `capitalize_sentences`, samo na drugom kraju: tamo se
znak zadržava, ovde nestaje, a razmak treba u oba slučaja.

**Veliko slovo posle tačke je naš posao, ne modelov.** Uz pisani stil model
propusti granicu rečenice, a ume i da slepi dve („prethodnu.Četvrta"), pa
`capitalize_sentences` dodaje razmak i podiže slovo. Tačka NE završava rečenicu
kad iza nje stoji cifra (godina `2026.`, redni broj `5.`, verzija `3.5`), kad je
reč pred njom skraćenica sa spiska (`npr.`, `itd.`, `tzv.`) ili inicijal (`M.`).
Razmak se ubacuje samo ispred VELIKOG slova: malo slovo posle tačke je po
pravilu ime fajla ili domen (`config.json`, `google.com`) koji ne sme da se
raskine. Upitnik i uzvičnik nemaju te izuzetke, u imenima fajlova ne postoje.
Prvo slovo komada se ne dira: diktat se seče na pauzama, pa sledeći komad ume
da bude nastavak rečenice. Pravilo postoji na obe platforme
(`webstt.capitalize_sentences`, `TextPolish.capitalizeSentences`), sa istim
spiskom skraćenica i istim testovima.

**Naša pravila ne smeju da spajaju redove.** `strip_punctuation` skuplja
razmake, pa je spisak tačaka završavao u jednom redu — a crtica, koja se tada
nađe između dva razmaka, i sama nestane. Pravila idu **red po red**
(`text.split("\n")`), ne po pasusima. Ovo se vidi samo uz stil „izgovoreno":
uz „sređeno" se pravila ne primenjuju, pa je greška dugo bila nevidljiva.

**„Podeli kad je jasnije" model ne posluša.** Izmereno na istom tekstu: meko
uputstvo daje 4–5 tačaka sa najdužom od 20–21 reči; izričita granica
(„dvanaest reči") uz spisak veznika daje 8 tačaka sa najdužom od 10–11. Kratak
diktat se pri tom ne cepa — jedna rečenica ostaje jedna tačka. Kad model treba
nešto da deli ili broji, mora da dobije **broj**, ne opis.

**Svaki alat koji skida ili prepisuje reči mora u `_sme_da_menja`.** Tačke,
prevod i izbacivanje ponavljanja tu spadaju — inače provera vernosti obori ceo
izlaz jer se reči razlikuju od ulaza. Isti alati isključuju granicu „ne
preformuliši", koja bi im protivrečila.

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

**Ono što radi naš kod ne stoji u AI grupi.** „Bez kvačica" i skraćenice ne
traže model ni ključ i rade i kad je AI isključen — zato imaju svoj podmeni
`Tekst`. U AI grupi ostaje samo ono što model zaista radi. Isti test za svaku
buduću stavku: da li radi bez ključa?

**Objašnjenja stoje iza dugmeta „i", ne ispod svake stavke.** Ekran je inače
dvostruko duži nego što treba, a opisi se čitaju jednom pa nikad više.

**Podešavanje koje uvek stoji isto nije podešavanje.** Maskiranje psovki,
sažimanje zvuka, „snimaj samo kad ima polja za unos" i vraćanje clipboard-a su
postali konstante — svaki je imao jednu razumnu vrednost i nikad drugu. Isto
važi i za polja koja se popune jednom (`vocabulary`, `polish_model`): ostaju u
`config.json` odnosno `SharedPreferences`, ali ne i na ekranu.

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
