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

U meniju **AI** biraš jedan od tri izvora; Google je podrazumevan.

| Izbor | Model | Ključ | Granica po zahtevu |
|---|---|---|---|
| **Transkripcija: Google** | Web Speech (Chromium) | ugrađen javni | ~30 s |
| **Transkripcija: OpenAI GPT** | `gpt-transcribe` | OpenAI | do 60 min |
| **Transkripcija: Gemini 3.5 Transcribe Live** | `gemini-3.5-transcribe-live` | Gemini | do 60 min |

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

Cena je ista — naplaćuje se zvuk, a zvuk je isti. Tekst i dalje stiže tek na
kraju, u jednom komadu: „Live" je ime modela, ne prikaz reč-po-reč.

Mana: komadi sa mikrofona se čitaju samo jednom, pa neuspeo poziv nema šta da
ponovi. Snimak se zato čuva u `~/Diktat-neuspeli` i ponavlja se sa
`./run.sh replay`.

> **Obična `gemini-3.5-transcribe` varijanta je isprobana pa uklonjena.** Na
> besplatnom nivou ima 3 zahteva u minuti i **25 dnevno**, što za svakodnevni
> rad ne znači ništa. Live varijanta nema ni jednu ni drugu granicu.

Kada je izabran OpenAI ili Gemini, **provera snimka se gasi** (Google/Gemini
sluša snimak, Groq preciznost): prepoznavanje već radi jak audio model, pa bi
drugi prolaz slao isti zvuk još jednom, slabijem. AI obrada teksta (prevod,
tačke, pasusi) radi normalno.

Prepis stiže na **latinici** — endpoint za `sr-RS` vraća ćirilicu, i to
nedosledno, pa se pismo poravnava pre svega ostalog. Izmereno: snimak od 19s sa
dve pauze prepiše se za ~9s.

### Izbor modela za manipulaciju teksta

U meniju **AI → Model za manipulaciju teksta** biraš **Gemini** ili
**Groq GPT-OSS 120B**. Na Androidu je isti izbor u AI kartici. Ovo je odvojeno
od transkripcije: izbor određuje samo podelu na pasuse, tačke, sređivanje,
ponavljanja i prevod. Groq-ov model koristi `openai/gpt-oss-120b` preko Groq
chat endpointa; postojeća opcija **Groq preciznost** i dalje znači dodatnu
audio-proveru i nije isto što i ovaj izbor.

---

## Instalacija

```bash
./setup.sh          # venv + zavisnosti + config.json
./make_app.sh       # pravi Diktat.app (preporučeno, vidi 'Dozvole')
./run.sh doctor     # provera
```

To je sve. Pokreni `Diktat.app` i radi.

---

## Dozvole

macOS traži dve. Ako si napravio `Diktat.app`, pokreni ga dvoklikom pa odobri:

| Dozvola | Gde | Čemu služi |
|---|---|---|
| **Microphone** | System Settings → Privacy & Security → Microphone | snimanje govora |
| **Accessibility** | System Settings → Privacy & Security → Accessibility | čitanje desnog Option-a i lepljenje |

**Zašto `.app` a ne `./run.sh`:** iz terminala macOS veže dozvole za Terminal,
pa ti hotkey pukne čim promeniš terminal ili ga apdejtuješ. `Diktat.app` je
potpisan i ima svoj identitet, pa dozvole drže.

Autostart: System Settings → General → Login Items → `+` → `Diktat.app`.

---

## Korišćenje

- **Drži desni Option**, pričaj, **pusti** → tekst se zalepi gde ti je kursor.
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
  je nastavljalo bez kraja. Sada se zapamti i izvrši čim snimanje krene. Uz to,
  dok se snima, u meniju stoji **Zaustavi snimanje** kao izlaz u nuždi.

### Provera da li prepoznavanje radi

```bash
./run.sh test 20           # snimi 20s SA PAUZAMA i ispiši šta je čuo
./run.sh replay            # pusti poslednji neuspeo snimak kroz isti put
./run.sh replay ~/x.wav    # ili određen snimak
```

Oba idu kroz **izabrani izvor**, isti koji koristi i aplikacija. Ispis nosi i
broj reči na sekundu zvuka: kratak prepis za dug snimak znači da se nešto
izgubilo usput.

**Testiraj sa pauzama.** Snimak od pet sekundi ima jednu izgovorenu celinu i
prolazi i kad je duži diktat pokvaren — tako je jedan bug (prepis staje na prvoj
pauzi) dugo prolazio neprimećeno.

`replay` ne traži mikrofon: neuspeli diktati se čuvaju u `~/Diktat-neuspeli`, pa
se ista greška ponavlja i posmatra bez slučajnosti.

### Meni

| Stavka | |
|---|---|
| **Zaustavi snimanje** | vidi se **samo dok se snima**; zaustavlja diktat mišem, kad prekidač zakaže |
| **Istorija** | poslednjih `history_size` tekstova; klik kopira u clipboard |
| **Procena koristi (10 dana)** | dnevni diktati, karakteri i sekunde; trošak se unosi ručno |
| **Snimanje / AI / Tekst** | podmeniji; sve ostalo je u `config.json` |
| **Mikrofon** | izbor ulaza; lista se sama osvežava kad otvoriš podmeni |
| **Osveži audio uređaje** | ručno, ako lista zaglavi |
| **Režim** | drži taster / prekidač |
| **AI obrada teksta** | izabrani alat sam uključuje obradu |
| **Transkripcija** | tačno jedan izbor: Google, OpenAI GPT ili Gemini 3.5 Transcribe Live |
| **API ključevi** | odvojeno: Gemini, Groq i OpenAI |
| **Tekst** | nezavisno: sva slova mala i uklanjanje interpunkcije |
| **Jezik** | srpski, engleski, hrvatski |
| **Detaljan log obrade** | uključi/isključi snimanje toka; zatim **Otvori poslednji log…** |

---

## Podešavanja (`config.json`)

| Ključ | Podrazumevano | Objašnjenje |
|---|---|---|
| `language` | `sr-RS` | menja se i iz menija |
| `api_key` | `""` | prazno = ugrađeni javni ključ |
| `transcription_provider` | `google` | `google`, `openai` ili `gemini_live`; međusobno isključivi izbor |
| `openai_api_key` | `""` | OpenAI Platform ključ; ne čuvati ga u repozitorijumu |
| `openai_output_script` | `auto` | `auto`, `cyrillic` ili `latin` |
| `openai_long_recording` | `true` | dugi OpenAI diktat, sa sigurnosnim limitom |
| `openai_max_seconds` | `3600` | gornja granica OpenAI diktata, 60 minuta |
| `recorded_seconds` | `0` | ukupno vreme uhvaćenog zvuka na računaru |
| `lowercase` | `true` | sva slova mala, nezavisno od interpunkcije |
| `strip_punctuation` | `true` | ukloni znakove; separatori `10:30`, `3,5`, `2.0` ostaju |
| `profanity_filter` | `false` | `true` bi maskirao psovke (`sranje` → `s*****`) |
| `compress_audio` | `true` | FLAC ka endpointu, 36% manje; bez `ffmpeg`-a ide PCM |
| `text_style` | `spoken` | stil koji traži AI; lokalni prekidači za mala slova i interpunkciju su odvojeni |
| `abbreviations` | `true` | „ne znam" → „nzm", „je li" → „je l", „svejedno"/„sve jedno" → „svj"; „15 minuta" → „15min" |
| `abbreviation_rules` | `""` | prazno = ugrađena lista; format `fraza=skraćenica`, jedno po redu |
| `ascii_diacritics` | `false` | `č ć ž š đ → c c z s dj`; menja se i iz menija |
| `auto_segment` | `false` | seci dug snimak na pauzama i slati u delovima |
| `segment_after_seconds` | `10` | samo uz `auto_segment` |
| `pause_seconds` | `0.7` | koliko tišine znači „kraj misli" |
| `max_request_seconds` | `30` | **snimanje staje ovde**; servis odbija duže |
| `max_seconds` | `290` | gornja granica jednog pritiska tastera |
| `tail_seconds` | `0.8` | koliko još snima pošto pustiš taster |
| `input_device` | `null` | `null` = sistemski; ili ime uređaja |
| `hotkey` | `alt_r` | desni Option; `cmd_r`, `ctrl_r`, `f13`… |
| `mode` | `toggle` | način aktivacije: `hold` (drži) ili `toggle` (pritisni) |
| `continuous` | `true` | bez granice; seče na svakoj pauzi |
| `continuous_max_seconds` | `3600` | sigurnosna granica i za neprekidni režim |
| `segment_after_seconds` | `0` | `0` = seci na svakoj pauzi, ma koliko kratka celina |
| `min_seconds` | `0.35` | kraći pritisak = obična prečica, ne diktat |
| `insert_method` | `auto` | `auto` = kuca tekst i ne dira clipboard (prelazi na lepljenje samo za tekst sa novim redom); `type` \| `paste` \| `clipboard_only` | `paste`, `type` (znak po znak), `clipboard_only` |
| `restore_clipboard` | `true` | vraća stari clipboard posle lepljenja |
| `history_size` | `3` | koliko poslednjih tekstova čuvati za kopiranje |
| `show_overlay` | `false` | pilula sa vremenom preko ekrana |
| `overlay_position` | `top-right` | `top-right` ili `bottom` |
| `text_model` | `gemini` | model za manipulaciju teksta: `gemini` ili `groq` |
| `groq_enabled` | `false` | Groq Whisper + GPT-OSS drugo mišljenje |
| `groq_api_key` | `""` | Groq ključ; ne čuvati ga u repozitorijumu |

Posle izmene fajla treba restart (jezik i režim rade odmah iz menija).

### Procena koristi diktiranja

U meniju **Procena koristi (10 dana)** pokreni novi period. Aplikacija lokalno
beleži broj uspešnih rezultata, karaktere i sekunde snimanja za svaki dan.
Potrošnju API-ja uneseš ručno kada je vidiš, a brzina kucanja služi samo za
grubu procenu koliko bi vremena trebalo da se isti broj karaktera otkuca.
Izveštaj prikazuje prosek po danu, cenu po diktatu, cenu na 1.000 karaktera i
procenu vremena kucanja. Podaci su lokalni i ne šalju se nigde.
Izveštaj beleži i uspešne pozive po provajderu/modelu — posebno Google ili
OpenAI transkripciju, Gemini/Groq obradu i Groq Whisper proveru — da posle
deset dana možeš da uporediš šta je stvarno korišćeno.

---

## AI obrada teksta

Meni → **AI**. Nema posebnog prekidača: izabran alat sam po sebi znači da se AI
koristi. Ceo diktat se sačeka, pa se **jednim pozivom**
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
| Jezik izlaza | prazno | slobodan opis: `makedonski`, `engleski formalno`, `pola makedonski pola srpski` |

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
| `output_language` | `""` | jezik izlaza, slobodan opis; prazno = bez prevoda |
| `polish_count` / `polish_count_day` | — | brojač poziva za tekući dan, upisuje ga aplikacija |

Zašto jednim pozivom na kraju a ne po segmentu: model bi inače video krhotine i
izmišljao krajeve rečenica, a broj poziva bi za deset minuta diktata skočio sa
jednog na oko sto pedeset.

Ako model zakaže, lepi se **nedoteran** tekst — model je dodatak, ne uslov.

Kod prolazne greške transkripcije (mreža, timeout, 429 ili 5xx) Google i OpenAI
automatski pokušavaju još **5 puta** pre nego što se audio sačuva za ručni
ponovni pokušaj. Nevažeći ključ i neispravan zahtev se ne ponavljaju.

Ako je *AI sluša snimak* uključeno, taj prolaz već vraća sređen tekst, pa se
poseban poziv za *sredi tekst* **preskače** — isti posao se ne radi dvaput
(izmereno: vraćao je identičan tekst za 0.7s). Ostali alati (pasusi, sažimanje,
emotikoni) se i dalje traže drugim pozivom.

Kad je *sredi tekst* uključeno, posle modela se i dalje primenjuju lokalni
prekidači `lowercase`, `strip_punctuation`, `join_thousands` i
`ascii_diacritics`. Tako se željeni oblik izlaza može zadati nezavisno od toga
šta je model vratio.

### Kvota i rezervni plan

Google **ne nudi** način da se vidi koliko je zahteva preostalo — ni u API-ju ni
u AI Studio-u. Zato aplikacija sama broji: stavka *Poziva modelu danas: N* u meniju,
brojač se resetuje u ponoć. `gemini-flash-lite-latest` na besplatnom ključu ima
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

## AI sluša snimak (preciznije prepoznavanje)

Meni → **AI sluša snimak**. Snimak ide i jezičkom modelu, zajedno sa onim što je
Web Speech čuo; model sluša zvuk i ispravlja greške. Traži isti API ključ i
broji se u isti dnevni brojač.

Izmereno na tri rečenice, čiste i sa šumom (SNR 5 dB) — greška po reči:

| | čist | sa šumom |
|---|---|---|
| Web Speech sam | 0.21 | 0.30 |
| model sam | **0.12** | 0.29 |
| model + prepis kao oslonac | 0.17 | **0.17** |

Model **sam** nije zamena: u šumu je vratio `poslao sam ponovo 250.000 dinara u
1:33` umesto `...ponudu... u utorak u deset i trideset`. Kad ne čuje, dopuni
umesto da ostavi rupu — zato mu se uvek šalje i prvi prepis kao sidro.

Ceo diktat ide **jednim pozivom**, sa svim segmentima kao odvojenim delovima —
provera po segmentu je trošila 6–9 poziva na jednu diktiranu poruku, a model je
uz to video krhotinu umesto celine. Zato tekst, kad je ovo uključeno, stiže
**tek na kraju diktata** (kao i u AI obradi), a ne deo po deo.

Cena: snimak ide drugi put, kao **AAC 32 kbps** (uz `ffmpeg`; bez njega FLAC pa
WAV) — oko 4 KB po sekundi govora umesto 19, uz identičan prepis. Odgovor čeka
nekoliko sekundi. Podstavka **…samo kad je pouzdanost niska** to smanjuje, ali je
podrazumevano isključena: endpoint prijavljuje 0.93 i za prepis sa odsečenom
rečju, pa filter štedi podatke a propušta greške.

Merenje na pet rečenica (sintetizovan govor, bez šuma) — greška po reči:

| | web sam | web + AI sluša |
|---|---|---|
| prosek | 0.197 | **0.080** |
| bez ijedne greške | 1/5 | **4/5** |

Šta je popravio: `precizno i model` → `precizno **AI** model`, `za gemini model
na and` → `za **Gemini** model na **Androidu**`. Preostalo odstupanje je samo
zapis brojeva (`250.000 RSD` umesto „dvesta pedeset hiljada dinara"), što nije
greška u prepoznavanju.

Skraćenice i strani nazivi su najslabija tačka endpointa — zato postoji
`vocabulary`, spisak pojmova koji ide modelu uz snimak.

| ključ | podrazumevano | |
|---|---|---|
| `audio_check` | `false` | uključuje se iz menija |
| `vocabulary` | `AI, API, Gemini, …` | pojmovi koje endpoint stalno greši |
| `audio_check_max_seconds` | `120` | koliko zvuka najviše čuvamo za grupnu proveru |
| `compress_audio` | `true` | FLAC preko `ffmpeg`-a; bez njega ide PCM/WAV |
| `audio_check_threshold` | `0.85` | prag pouzdanosti |

### Groq: Whisper + GPT-OSS

Na macOS-u se podešava iz menija **AI → Groq preciznost**, a na Androidu
u kartici **AI**. Opcija **Google/Gemini sluša snimak** je zasebna; može biti
isključena dok Groq ostaje uključen. Groq Whisper tada i dalje dobija kompletan
audio jednog diktata, zatim
`openai/gpt-oss-120b` dobija Google i Whisper prepis i vraća samo konačan tekst.
Ako Groq poziv ne uspe, aplikacija zadržava Google prepis. Ugrađeni modeli
su `whisper-large-v3` i `openai/gpt-oss-120b`; Groq dokumentacija navodi da je
Whisper dostupan na transkripcijskom endpointu, a GPT-OSS na chat endpointu.

Ključ se unosi lokalno u podešavanja (`config.json` na macOS-u ili Android
SharedPreferences) i nikad ne treba slati kroz GitHub. Pošto je API ključ iz
prethodne poruke već izložen, opozovi ga u Groq konzoli i napravi novi pre
testiranja.

## Testovi

```bash
./run.sh tests     # 53 testa: pravila nad tekstom, uputstva modelu, tok diktata
```

Ne traže ni mikrofon ni mrežu ni ključ. Android ima svojih 24: `cd android && ./gradlew test`.

## Ako se ne prepozna sve što si rekao

Uključi **Detaljan log obrade** iz menija. Zatim se pojavljuje
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

Kada je Groq uključen, isti `.txt` sadrži i:

```text
[AI PROLAZ] Groq Whisper + GPT-OSS
     Google prepis: '...'
     Whisper prepis: '...'
     Prompt:
     ...
     Rezultat modela: '...'

[FINALNI OUTPUT] '...'
```

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
programi ne primaju sintetički Cmd+V. Tekst je uvek i u **Istoriji** u meniju.

**Vađenje/vraćanje slušalica** → lista uređaja se osvežava sama pred svaki diktat
(~2ms). Meni **Osveži audio uređaje** postoji za slučaj da ipak zaglavi.

**Servis vraća 403 ili prazno** → Google je verovatno stegao endpoint. Snimak
nije izgubljen: čuva se u `~/Diktat-neuspeli` i šalje ponovo stavkom
**Ponovi neuspele** u meniju.

---

## Struktura

```
android/       probna Android aplikacija (vidi android/README.md)
dictate/
  app.py       menu bar, stanja, orkestracija (UI samo iz glavne niti)
  hotkey.py    detekcija desnog Command-a + otkazivanje na prečice
  audio.py     mikrofon → 16 kHz PCM komadi + detekcija pauze
  webstt.py    Google Web Speech endpoint
  insert.py    lepljenje/kucanje u aktivnu aplikaciju
  overlay.py   pilula sa vremenom (podrazumevano isključena)
  debugdump.py snimanje zvuka i teksta radi poređenja
  config.py    config.json
doctor.py      dijagnostika
selftest.py    snimi 5s i ispiši šta je čuo
run.py         ulazna tačka
make_app.sh    pravi Diktat.app
```
