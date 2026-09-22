# Diktat

Diktiranje govora u tekst, bez naloga i bez ključeva. Dva dela:

| | stanje |
|---|---|
| **macOS** (ovaj folder) | radi, u svakodnevnoj upotrebi |
| **[Android](android/)** | radi — bočni taster ili mikrofon na tastaturi |

Oba koriste isti Google Web Speech endpoint — onaj koji koristi Chromium.

Ako menjaš kod, pročitaj prvo **[CLAUDE.md](CLAUDE.md)** — tamo su odluke, razlozi
i greške koje su već napravljene.

---

## macOS

Diktiranje na macOS-u: **drži desni Option**, pričaj, pusti — tekst se pojavi u
aplikaciji u kojoj si trenutno. Bez naloga, bez ključeva, bez podešavanja.

```
00 spremno    01…30 snima (crveno od 15s)    žuto = nešto se obrađuje    ⚠️ greška
```

Prepoznavanje ide preko Google Web Speech endpointa — onog koji koristi Chromium,
istog koji zove `SpeechRecognition.recognize_google()`. Besplatan je i srpski mu
ide vrlo dobro (izmerena pouzdanost 0.93).

> Endpoint je nedokumentovan i koristi javni ključ. Radi godinama, ali ga Google
> može ugasiti bez najave. Ako se to desi, `./run.sh doctor` će to jasno reći.

### Izbor provajdera transkripcije

U **Podešavanja → Snimanje i tekst** biraš jedan od tri izvora; Google je podrazumevan.

| Izbor | Model | Ključ | Granica po zahtevu |
|---|---|---|---|
| **Transkripcija: Google** | Web Speech (Chromium) | ugrađen javni | ~30 s |
| **Transkripcija: OpenAI GPT** | `gpt-transcribe` | OpenAI | do 60 min |
| **Transkripcija: Gemini 3.5 Transcribe Live** | `gemini-3.5-transcribe-live` | Gemini | 120 s podrazumevano |

OpenAI šalje jedan završen snimak tek posle Stop-a na Audio Transcriptions API;
potrebno je da uneseš svoj OpenAI API ključ u **AI → API ključevi → OpenAI API
ključ…**. Ovo je OpenAI Platform API, a ne ChatGPT pretplata.

Gemini Transcribe Live koristi **isti ključ kao AI obrada** (`polish_api_key`) i
na besplatnom nivou nema ni dnevnu ni minutnu granicu. Prednost nad besplatnim
Google endpointom: prima duže snimke, podržava `sr-RS` i dobija nagoveštaj
jezika — a Web Speech najviše greši baš na skraćenicama i stranim nazivima.

**Zvuk se šalje dok pričaš, ne posle Stop-a.** Zato na kraju nema čekanja:

| | zvuk 64.7s | čekanje posle Stop-a |
|---|---|---|
| slanje posle Stop-a | 64.7s | **15.6s** |
| slanje u toku (ovako radi) | 64.7s | **0.0s** |

Ono što je posle toga ostalo bilo je naše: server je gotov 0.5s posle Stop-a bez
obzira na dužinu diktata, a ostatak je bila tempirana pauza kojom se prepoznaje
da je utihnuo. Skraćena je sa 3.0s na 1.0s, uz duži rok kad je celina još u
letu — ukupno čekanje **3.5s → 1.5s**.

Na Mac-u su u **Podešavanja → Snimanje i tekst** dva nezavisna izbora:

- **Prikaži prepis uživo u okviru na ekranu** (podrazumevano uključeno): okvir
  pri dnu ekrana ispisuje prepis dok govoriš, uključujući i međurezultat.
  Okvir nikad ne uzima fokus i propušta klik, pa tekst i dalje ide u polje koje
  je bilo aktivno, a nestaje istog trenutka kad zaustaviš snimanje. Postoji zato što potvrđena celina od Gemini-ja stiže tek na
  pauzi: između dve potvrde inače nema nikakvog znaka da aplikacija čuje.
- **Upisuj tekst tokom snimanja u aktivno polje**: potvrđene celine se odmah
  kucaju u polje, pa raniju reč možeš da klikneš i ispraviš dok govoriš dalje.
  Pre naredne celine kursor se vraća na kraj. Međurezultat se **nikad** ne
  kuca, da Gemini ne bi prebrisao ručnu ispravku; on se vidi samo u okviru.
  Lokalna pravila rade pri svakom upisu, a zasebna AI obrada teksta na kraju se
  u ovom režimu preskače.

Na Androidu je isti prikaz uživo zaseban izbor **Prikazuj prepis uživo tokom
snimanja**; tekst stoji uz tajmer, a u polje se ubacuje konačan rezultat po
zaustavljanju.

Mana: komadi sa mikrofona se čitaju samo jednom, pa neuspeo poziv nema šta da
ponovi. Na telefonu takav diktat propada. Mac zato usput čuva zvuk dok prepis
ne uspe (vidi **Sačuvani snimci** ispod).

> **Obična `gemini-3.5-transcribe` varijanta je isprobana pa uklonjena.** Na
> besplatnom nivou ima 3 zahteva u minuti i **25 dnevno**, što za svakodnevni
> rad ne znači ništa. Live varijanta nema ni jednu ni drugu granicu.

Prepis stiže na **latinici** — endpoint za `sr-RS` vraća ćirilicu, i to
nedosledno, pa se pismo poravnava pre svega ostalog. Izmereno: snimak od 19s sa
dve pauze prepiše se za ~9s.

### Izbor modela za manipulaciju teksta

U **Podešavanja → Snimanje i tekst → AI obrada teksta** biraš **Gemini** ili
**Groq GPT-OSS 120B**. Na Androidu je isti izbor u AI kartici. Ovo je odvojeno
od transkripcije: izbor određuje samo podelu na pasuse, tačke, sređivanje i
ponavljanja. Groq-ov model koristi `openai/gpt-oss-120b` preko Groq
chat endpointa. Zvuk se Groq-u ne šalje.

---

## Instalacija

```bash
./setup.sh              # venv + zavisnosti + config.json
./make_app.sh install   # ikona u Launchpad-u, pokretanje bez terminala
./run.sh doctor         # provera
```

Posle toga se Diktat otvara kao i svaka druga aplikacija: iz **Launchpad-a**,
iz **Spotlight-a** (cmd+razmak pa „Diktat") ili iz Finder-a, folder
**Applications**. Terminal više nije potreban ni za pokretanje ni za rad.
Ikonica je u traci menija, bez prozora i bez stavke u Dock-u.

`./make_app.sh` bez `install` pravi samo `Diktat.app` u ovom folderu, za rad
na kodu.

### Šta radi `install`

Kopira kod i Python okruženje u `~/Library/Application Support/Diktat` i pravi
`/Applications/Diktat.app` koji ih pokreće.

**Zašto kopija, a ne pokretanje odavde:** macOS aplikaciji pokrenutoj iz
Launchpad-a tiho zabranjuje čitanje foldera Desktop, Documents i Downloads.
Projekat stoji na Desktopu, pa je aplikacija pucala na prvom redu, bez ijednog
pitanja korisniku, i bez ičega u logu osim `PermissionError` na
`.venv/pyvenv.cfg`. U Application Support te zabrane ne važe.

Zbog toga **posle svake izmene koda ide `./make_app.sh install` ponovo**,
inače instalirana aplikacija ostaje na starom. Podešavanja i ključevi
(`config.json`) se pri tome prenose i ne gube se.

Ako nešto krene naopako, aplikacija javi prozorčićem, a ceo ispis stoji u
`~/Library/Logs/Diktat.log`.

Ikona se crta iz koda (`ikona.py`), pa u repozitorijumu ne stoji binarni fajl.

**Ponovni klik na Diktat ga pokreće iznova.** Ako je snimanje zaglavljeno,
dovoljno je da ponovo otvoriš Diktat iz Launchpad-a ili Spotlight-a: stara
instanca se ugasi (posle 2s i silom), a nova krene. Za to je glavni program
bundle-a mali Swift pokretač (`swiftc`, dolazi sa `xcode-select --install`),
jer macOS pokrenutoj aplikaciji na novi klik ne pokreće ništa iznova, samo joj
pošalje poruku, a bash skripta tu poruku ne ume da primi.

### Ažuriranje

Na drugom računaru se ništa ne povlači ručno. Aplikacija pri pokretanju i
jednom dnevno tiho pita GitHub koje je poslednje izdanje (isto koje koristi i
telefon). Kad je novije od instaliranog:

- u traci menija pored cifara stoji **↑**,
- u zaglavlju Podešavanja, između „Zaustavi snimanje" i „Zatvori Diktat",
  dugme pozeleni i piše
  „Ažuriraj v1.66 → v1.67". Inače piše „Proveri ažuriranje (v1.66)", sa
  instaliranom verzijom u zagradi, i radi i ručno. Pun ishod provere je u
  opisu koji iskoči kad se miš zadrži nad dugmetom.

Klik preuzme kod tog izdanja, zameni instaliranu kopiju, doinstalira
biblioteke ako se `requirements.txt` promenio i ponovo pokrene Diktat.
`config.json` sa ključevima ostaje. Ako diktat traje, ažuriranje čeka da se
završi. Automatska provera se gasi sa `"update_check": false` u `config.json`.

Menja se samo kod u `~/Library/Application Support/Diktat/app`, a
`/Applications/Diktat.app` ostaje isti. Svaki novi potpis bundle-a poništava
dozvole za Accessibility i Mikrofon, pa bi se posle svakog ažuriranja morale
davati iznova. Izmena samog pokretača (`make_app.sh`) zato i dalje traži ručno
`./make_app.sh install`.

Razvojna kopija (pokrenuta iz foldera projekta) se ne ažurira sama: tu važe
`git pull` pa `./make_app.sh install`.

**Objavljivanje nove verzije.** Mac i telefon čitaju isto izdanje, pa jedno
izdanje pokriva oba. Izdanje mora da nosi APK (telefon uzima prvi `.apk`), a
oznaka mora biti veća od prethodne i od `versionName` u
`android/app/build.gradle.kts`:

```bash
git push                                  # kod mora biti na main pre izdanja
cd android && ./build.sh
gh release create v1.67 app/build/outputs/apk/release/app-release.apk \
  -R milev051/diktat -t "Diktat 1.67" --target main
```

Mac iz izdanja uzima kod sa `main` u trenutku objave, telefon APK.

---

## Dozvole

macOS traži dve. Pokreni Diktat jednom, pa odobri:

| Dozvola | Gde | Čemu služi |
|---|---|---|
| **Microphone** | System Settings → Privacy & Security → Microphone | snimanje govora |
| **Accessibility** | System Settings → Privacy & Security → Accessibility | čitanje desnog Option-a i lepljenje |

Posle instalacije se dozvole traže za **Diktat**, ne za Terminal. Ako je
aplikacija ranije bila odobrena kao Terminal, obe stavke treba dodati iznova,
sada na ime Diktat.

**Zašto `.app` a ne `./run.sh`:** iz terminala macOS veže dozvole za Terminal,
pa ti hotkey pukne čim promeniš terminal ili ga apdejtuješ. `Diktat.app` je
potpisan i ima svoj identitet, pa dozvole drže. Pošto se bundle pri ponovnoj
instalaciji ne menja (kod stoji izvan njega), jednom date dozvole ostaju.

Autostart: System Settings → General → Login Items → `+` → `Diktat.app`
(uzmi onaj iz foldera Applications).

---

## Korišćenje

- **Drži desni Option**, pričaj, **pusti** → tekst se zalepi gde ti je kursor.
- **Taster `§`** (levo od jedinice) radi isto, ako je uključen u Podešavanjima.
  Dok je uključen, taj znak se **ne upisuje** nigde; uz modifikator (Shift+§ za
  „±", Cmd+§) taster radi kao i pre.
- **Taster `` ` ``** (levo od Z, pored levog Shift-a) isto, uz zaseban prekidač u
  Podešavanjima, podrazumevano isključen. I on se tada ne upisuje; Shift+` i
  dalje daje „~".

Dva nezavisna podešavanja:

- **Režim** — *Drži taster* ili *Prekidač* (podrazumevano prekidač: pritisneš da
  počneš, pritisneš da završiš)
- **Neprekidno** (podrazumevano uključeno) — ukida granicu od 30s, seče na
  **svakoj pauzi** i šalje delove dok pričaš dalje, pa tekst stiže usput.
  Ostatak ide kad zaustaviš.

- **U običnom režimu snimanje staje na 30 sekundi** i tekst ide na obradu; nastavak traži
  nov pritisak. Tako slučajno pokrenut diktat ne može da snima satima. Do tada se ne seče —
  ceo diktat se prepoznaje odjednom. Brojač u menu baru postaje crven na 15s, a žut dok se prethodni tekst obrađuje.
- **Možeš odmah da kreneš u sledeći diktat dok se prethodni još obrađuje.**
  Mikrofon se oslobađa čim pustiš taster. Tekst se lepi **po redosledu snimanja**,
  i kad se kraći drugi snimak prepozna pre dužeg prvog.
- **Snimanje se ne prekida naglo kad pustiš taster** — nastavlja još `tail_seconds`
  (0.8s), jer se taster pušta tačno na kraju poslednje reči pa bi se ona izgubila.
- Ako umesto diktata pritisneš **prečicu** (Option+E i slično), snimanje se otkazuje
  i ništa se ne ubacuje. Desni Option i dalje kuca specijalne znake normalno.
- **Brz start pa odmah stop** se više ne gubi. Pokretanje čeka da se mikrofon
  oslobodi (do ~1.5s), pa je STOP u tom prozoru ranije padao u prazno i snimanje
  je nastavljalo bez kraja. Sada se zapamti i izvrši čim snimanje krene. Dok
  se snima, klik na ikonicu služi kao rezervno **Zaustavi snimanje**.

### Provera da li prepoznavanje radi

```bash
./run.sh test 20           # snimi 20s SA PAUZAMA i ispiši šta je čuo
./run.sh replay ~/x.wav    # pusti postojeći WAV kroz isti put
```

Oba idu kroz **izabrani izvor**, isti koji koristi i aplikacija. Ispis nosi i
broj reči na sekundu zvuka: kratak prepis za dug snimak znači da se nešto
izgubilo usput.

**Testiraj sa pauzama.** Snimak od pet sekundi ima jednu izgovorenu celinu i
prolazi i kad je duži diktat pokvaren — tako je jedan bug (prepis staje na prvoj
pauzi) dugo prolazio neprimećeno.

`replay` ne traži mikrofon: nad istim WAV fajlom se ista greška ponavlja i
posmatra bez slučajnosti. Putanja se navodi ručno. Sačuvan snimak neuspelog
diktata (`~/Library/Application Support/Diktat/snimci/*.wav`) radi i ovde.

### Sačuvani snimci

Dok diktat traje, Mac usput upisuje zvuk u WAV fajl. Kad prepis uspe, fajl se
odmah briše. Kad ne uspe (pala mreža, zaglavljen servis, pad aplikacije), fajl
ostaje i vidi se u Podešavanjima pod **Sačuvani snimci**, sa dugmadima
**Prepiši** i **Obriši**. Prepis ide u clipboard i u istoriju, pa ga nalepiš
sa ⌘V gde treba. Ako je snimak ostao od pre pokretanja, Podešavanja se otvore
sama. Neiskorišćen snimak se briše posle 24 h. Isključuje se prekidačem
„Čuvaj snimak dok se ne prepiše".

Klik na ikonicu otvara **Podešavanja**, a drugi klik ih sklanja; tokom snimanja
isti klik zaustavlja diktat. Istorija, mikrofon, izbor
izvora, tekstualna pravila i ostale opcije nalaze se u prozoru Podešavanja.

---

## Podešavanja (`config.json`)

| Ključ | Podrazumevano | Objašnjenje |
|---|---|---|
| `language` | `sr-RS` | jezik prepoznavanja |
| `api_key` | `""` | prazno = ugrađeni javni ključ |
| `transcription_provider` | `google` | `google`, `openai` ili `gemini_live`; međusobno isključivi izbor |
| `openai_api_key` | `""` | OpenAI Platform ključ; ne čuvati ga u repozitorijumu |
| `openai_output_script` | `auto` | `auto`, `cyrillic` ili `latin` |
| `openai_long_recording` | `true` | dugi OpenAI diktat, sa sigurnosnim limitom |
| `openai_max_seconds` | `3600` | gornja granica OpenAI diktata, 60 minuta |
| `gemini_live_insert` | `false` | potvrđene Gemini celine odmah u aktivno polje na Mac-u |
| `recorded_seconds` | `0` | ukupno vreme uhvaćenog zvuka na računaru |
| `lowercase` | `true` | sva slova mala, nezavisno od interpunkcije |
| `strip_punctuation` | `true` | ukloni znakove; separatori `10:30`, `3,5`, `2.0` ostaju |
| `profanity_filter` | `false` | `true` bi maskirao psovke (`sranje` → `s*****`) |
| `compress_audio` | `true` | FLAC ka endpointu, 36% manje; bez `ffmpeg`-a ide PCM |
| `text_style` | `spoken` | stil koji traži AI; lokalni prekidači za mala slova i interpunkciju su odvojeni |
| `abbreviations` | `true` | „ne znam" → „nzm", „je li" → „je l", „svejedno"/„sve jedno" → „svj"; „15 minuta" → „15min" |
| `abbreviation_rules` | `""` | prazno = ugrađena lista; format `fraza=skraćenica`, jedno po redu |
| `ascii_diacritics` | `false` | `č ć ž š đ → c c z s dj`; menja se i u Podešavanjima |
| `auto_segment` | `false` | seci dug snimak na pauzama i slati u delovima |
| `segment_after_seconds` | `10` | samo uz `auto_segment` |
| `pause_seconds` | `0.7` | koliko tišine znači „kraj misli" |
| `max_request_seconds` | `30` | **snimanje staje ovde**; servis odbija duže |
| `max_seconds` | `290` | gornja granica jednog pritiska tastera |
| `tail_seconds` | `0.8` | koliko još snima pošto pustiš taster |
| `input_device` | `null` | `null` = sistemski; ili ime uređaja |
| `hotkey` | `alt_r` | desni Option; `cmd_r`, `ctrl_r`, `f13`… |
| `hotkey_section` | `true` | i taster `§` pokreće diktat; znak se tada guta |
| `hotkey_grave` | `false` | i taster `` ` `` pokreće diktat; znak se tada guta |
| `mode` | `toggle` | način aktivacije: `hold` (drži) ili `toggle` (pritisni) |
| `continuous` | `true` | bez granice; seče na svakoj pauzi |
| `continuous_max_seconds` | `3600` | sigurnosna granica i za neprekidni režim |
| `segment_after_seconds` | `0` | `0` = seci na svakoj pauzi, ma koliko kratka celina |
| `min_seconds` | `0.35` | kraći pritisak = obična prečica, ne diktat |
| `insert_method` | `auto` | `auto` = kuca tekst i ne dira clipboard (prelazi na lepljenje samo za tekst sa novim redom); `type` \| `paste` \| `clipboard_only` | `paste`, `type` (znak po znak), `clipboard_only` |
| `restore_clipboard` | `true` | vraća stari clipboard posle lepljenja |
| `history_size` | `3` | koliko poslednjih tekstova čuvati za kopiranje |
| `show_overlay` | `false` | pilula sa vremenom preko ekrana |
| `live_preview` | `true` | okvir sa prepisom uživo (Gemini Live) |
| `overlay_position` | `top-right` | `top-right` ili `bottom` |
| `text_model` | `gemini` | model za manipulaciju teksta: `gemini` ili `groq` |
| `groq_api_key` | `""` | Groq ključ; ne čuvati ga u repozitorijumu |

Posle ručne izmene fajla treba restart; izmene iz Podešavanja rade odmah.

---

## AI obrada teksta

**Podešavanja → Snimanje i tekst**. Prekidač *Uključi AI obradu* je prečica nad alatima
ispod: gašenje pamti zatečen izbor i sklanja ih sa ekrana, paljenje ih vraća.
Izabran alat sam po sebi znači da se AI koristi. Ceo diktat se sačeka, pa se **jednim pozivom**
pošalje jezičkom modelu. Dok se čeka odgovor, u menu baru stoji plavo **AI**.

Traži ključ za trenutno izabrani model: Gemini koristi `polish_api_key`, a Groq
koristi `groq_api_key`. Bez odgovarajućeg ključa obrada se ne može uključiti.

Alati ispod su **nezavisni** — uputstvo se sklapa od izabranih. Sređivanje je
samo jedan od njih, pa možeš tražiti kraći tekst ili emotikon, a da model
interpunkciju i kvačice **ne dira**:

| alat | podrazumevano | šta radi |
|---|---|---|
| Sredi tekst | isključeno | tačke i velika slova; usput i gramatička neslaganja |
| Bez kvačica | isključeno | `č ć ž š đ → c c z s dj`, primenjuje se na kraju |
| …podeli na pasuse | uključeno | prazan red između smisaonih celina |
| Sažmi u tačke | isključeno | spisak tačaka; isključuje pasuse |
| Izbaci ponavljanja | isključeno | udvojena reč ili fraza ostaje jednom |

Ako nijedan alat nije izabran, poziva nema — tekst se lepi kao i inače.

Kad nijedan izabrani alat **ne sme** da menja reči (npr. samo emotikon), izlaz
se poredi sa ulazom reč po reč; ako se razlikuje, lepi se naš tekst. Izmišljena
reč je gora od izostalog emotikona.

Bez *sredi tekst* izlaz modela ide **ponovo kroz tvoja podešavanja** — velika
slova, interpunkcija i kvačice se skidaju po `lowercase`, `strip_punctuation` i
`ascii_diacritics`. Model naime sređuje tekst čim prepisuje rečenice, koliko god
mu se to zabranilo u uputstvu; pasusi i emotikoni pri tom ostaju.

| ključ | podrazumevano | |
|---|---|---|
| `polish_api_key` | `""` | Gemini ključ; potreban samo ako je izabran Gemini |
| `text_model` | `gemini` | `gemini` ili `groq` za manipulaciju teksta |
| `polish_model` | `""` | prazno = `gemini-flash-lite-latest` |
| `polish_prompt` | `""` | prazno = ugrađeno uputstvo |
| `polish_bullets` | `false` | sažmi u spisak tačaka; isključuje pasuse |
| `polish_dedupe` | `false` | izbaci slučajno udvojene reči i fraze |
| `polish_paragraphs` | `true` | deli tekst na pasuse, prazan red između |
| `polish_count` / `polish_count_day` | — | brojač poziva za tekući dan, upisuje ga aplikacija |

Zašto jednim pozivom na kraju a ne po segmentu: model bi inače video krhotine i
izmišljao krajeve rečenica, a broj poziva bi za deset minuta diktata skočio sa
jednog na oko sto pedeset.

Ako model zakaže, lepi se **nedoteran** tekst — model je dodatak, ne uslov.

Kod prolazne greške transkripcije (mreža, timeout, 429 ili 5xx) Google i OpenAI
automatski pokušavaju još **5 puta**. Nevažeći ključ i neispravan zahtev se ne
ponavljaju. Posle poslednjeg pokušaja na telefonu diktat propada, a Mac
zadrži zvuk pod **Sačuvani snimci** (vidi niže).

Kad je *sredi tekst* uključeno, posle modela se i dalje primenjuju lokalni
prekidači `lowercase`, `strip_punctuation`, `join_thousands` i
`ascii_diacritics`. Tako se željeni oblik izlaza može zadati nezavisno od toga
šta je model vratio.

### Kvota i rezervni plan

Google **ne nudi** način da se vidi koliko je zahteva preostalo — ni u API-ju ni
u AI Studio-u. Zato aplikacija sama broji pozive; brojač se resetuje u ponoć.
`gemini-flash-lite-latest` na besplatnom ključu ima
red veličine 500 poziva dnevno, a jedan diktat je jedan poziv.

Šta se dešava kad nešto pukne:

| slučaj | ponašanje |
|---|---|
| potrošena kvota (429) | lepi se nedoteran tekst, poruka kaže zašto |
| podešeni model ukinut ili preimenovan (404) | automatski se ponovo pokušava sa `gemini-flash-lite-latest` |
| i podrazumevani nestao | isključi formalni režim; diktat radi kao pre, model je samo dodatak |
| filter odbije tekst | lepi se nedoteran tekst |

Prepoznavanje govora ne zavisi od ovog ključa — formalni režim može da otkaže u
celini, a diktat i dalje radi.

## Provera snimka drugim modelom (uklonjeno)

Mac je ranije mogao da pošalje isti snimak još jednom (Gemini sluša snimak,
odnosno Groq Whisper uz spajanje preko GPT-OSS) i da ispravi prvi prepis.
Uklonjeno je 22.09.2026: izlaz je često bio lošiji od prvog prepisa, a zvuk je
išao dva puta. Kako je radilo, uputstva modelima i merenja su u
[docs/provera-snimka.md](docs/provera-snimka.md).

Ostala su dva ključa koja su služila i tome:

| ključ | podrazumevano | |
|---|---|---|
| `vocabulary` | `AI, API, Gemini, …` | pojmovi koje Gemini Live dobija kao pomoć pri prepoznavanju |
| `compress_audio` | `true` | FLAC preko `ffmpeg`-a za OpenAI; bez njega ide WAV |

## Testovi

```bash
./run.sh tests     # pravila nad tekstom, uputstva modelu, tok diktata
```

Ne traže ni mikrofon ni mrežu ni ključ. Android testovi: `cd android && ./gradlew testDebugUnitTest`.

## Ako se ne prepozna sve što si rekao

Uključi **Detaljan log obrade** u Podešavanjima. Zatim se pojavljuje
**Otvori poslednji log…**. Svaki diktat se čuva u `~/Diktat-debug`:

```
2026-08-04_15-31-07.txt        izveštaj
2026-08-04_15-31-07-full.wav   ceo diktat, neisečen
2026-08-04_15-31-07-01.wav     prvi segment
```

Izveštaj sam presuđuje gde se gubi:

```
[02] segment    2.3s  ...-02.wav
     ''   <-- PRAZNO, tekst se izgubio

[CEO DIKTAT]   5.6s
     segmenti pokrivaju 5.6s od 5.6s -> sav zvuk je poslat
     praznih segmenata: 1
```

- **Segmenti ne pokrivaju ceo diktat** → zvuk se gubi pri sečenju.
- **Pokrivaju ga, ali ima praznih** → servis nije prepoznao taj deo; pusti taj
  `.wav` i čuj šta je unutra.
- **Nema ga ni u `full.wav`** → gubi se u snimanju, ne u prepoznavanju.


Ne upisuju se API ključevi ni sirovi HTTP zahtevi. Ako je uključen i postojeći
Gemini tekstualni prolaz, i njegov prompt i rezultat se zapisuju kao poseban
`[AI PROLAZ]`.

Ne zaboravi da isključiš — snima svaki diktat na disk.

---

## Ako nešto ne radi

Prvo uvek `./run.sh doctor`. Za proveru samo mikrofona i prepoznavanja, bez
hotkey-a i lepljenja: `./run.sh test 5`.

**Hotkey ne reaguje** → nema Accessibility dozvole. Ako si već dodao aplikaciju,
izbaci je iz liste (`−`) pa dodaj ponovo — macOS ume da zapamti stari potpis.

**Tekst se lepi dvaput** → verovatno ti rade dve instance. `pkill -f run.py` pa
pokreni jednu.

**Tekst se ne lepi** → probaj `"insert_method": "type"`. Neki terminali i Java
programi ne primaju sintetički Cmd+V. Tekst je uvek i u **Istoriji** u Podešavanjima.

**Vađenje/vraćanje slušalica** → lista uređaja se osvežava sama pred svaki diktat
(~2ms). Spisak mikrofona se osvežava i kada otvoriš Podešavanja.

**Servis vraća 403 ili prazno** → Google je verovatno stegao endpoint. Snimak
se ne čuva, pa taj diktat treba ponoviti; u logu stoji koliko je sekundi govora
ostalo bez prepisa.

---

## Struktura

```
android/       probna Android aplikacija (vidi android/README.md)
dictate/
  app.py       pokretanje, stanje, traka menija (AppKit samo iz glavne niti)
  snimanje.py  start, stop, osigurač, sesija diktata, izbor servisa
  tok_google.py  Google: sečenje na pauzama, segmenti
  tok_openai.py  OpenAI: ceo snimak posle Stop-a
  tok_gemini.py  Gemini Live: strim dok snimaš, pregled uživo
  upis.py      redosled i upis teksta, istorija
  obrada.py    lokalna pravila i AI obrada
  prozor_akcije.py  šta rade dugmad i prekidači u Podešavanjima
  prepis_sacuvanog.py  Prepiši / Obriši za sačuvane snimke
  azuriranje_ui.py  dugme i provera ažuriranja
  rezerva.py   rezervni snimak diktata na disku
  azuriranje.py  preuzimanje i instalacija izdanja sa GitHub-a
  hotkey.py    detekcija desnog Command-a + otkazivanje na prečice
  audio.py     mikrofon → 16 kHz PCM komadi + detekcija pauze
  webstt.py    Google Web Speech endpoint
  insert.py    lepljenje/kucanje u aktivnu aplikaciju
  overlay.py   pilula sa vremenom (podrazumevano isključena)
  settings_window.py  prozor Podešavanja (tri kolone na jednom ekranu)
  azuriranje.py  provera i instalacija novog izdanja sa GitHub-a
  debugdump.py snimanje zvuka i teksta radi poređenja (samo uz `debug: true`)
  config.py    config.json
doctor.py      dijagnostika
selftest.py    snimi 5s i ispiši šta je čuo
run.py         ulazna tačka
ikona.py       crta ikonu aplikacije (poziva je make_app.sh)
make_app.sh    pravi Diktat.app; `install` ga stavlja u /Applications
```
