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

### Meni

| Stavka | |
|---|---|
| **Istorija** | poslednjih `history_size` tekstova; klik kopira u clipboard |
| **Snimanje / AI** | podmeniji; sve ostalo je u `config.json` |
| **Mikrofon** | izbor ulaza, ili sistemski podrazumevani |
| **Osveži audio uređaje** | ručno, ako lista zaglavi |
| **Režim** | drži taster / prekidač |
| **AI obrada teksta** | glavni prekidač; alati su uvučeni ispod njega i sivi dok je isključen |
| **Jezik** | srpski, engleski, hrvatski |
| **Snimaj za debug** | vidi „Ako se ne prepozna sve" |

---

## Podešavanja (`config.json`)

| Ključ | Podrazumevano | Objašnjenje |
|---|---|---|
| `language` | `sr-RS` | menja se i iz menija |
| `api_key` | `""` | prazno = ugrađeni javni ključ |
| `profanity_filter` | `false` | `true` bi maskirao psovke (`sranje` → `s*****`) |
| `compress_audio` | `true` | FLAC ka endpointu, 36% manje; bez `ffmpeg`-a ide PCM |
| `text_style` | `spoken` | `spoken` = mala slova bez interpunkcije (podrazumevano), `written` = AI sređuje |
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
| `insert_method` | `paste` | `paste`, `type` (znak po znak), `clipboard_only` |
| `restore_clipboard` | `true` | vraća stari clipboard posle lepljenja |
| `history_size` | `10` | koliko poslednjih tekstova čuvati za kopiranje |
| `show_overlay` | `false` | pilula sa vremenom preko ekrana |
| `overlay_position` | `top-right` | `top-right` ili `bottom` |

Posle izmene fajla treba restart (jezik i režim rade odmah iz menija).

---

## AI obrada teksta

Meni → **AI obrada teksta**. Ceo diktat se sačeka, pa se **jednim pozivom**
pošalje jezičkom modelu. Dok se čeka odgovor, u menu baru stoji plavo **AI**.

Traži ključ sa Google AI Studio u `polish_api_key`. Bez ključa stavka piše da
ključa nema i obrada se ne može uključiti.

Alati ispod su **nezavisni** — uputstvo se sklapa od izabranih. Sređivanje je
samo jedan od njih, pa možeš tražiti kraći tekst ili emotikon, a da model
interpunkciju i kvačice **ne dira**:

| alat | podrazumevano | šta radi |
|---|---|---|
| Sredi tekst | isključeno | interpunkcija, velika slova, kvačice; usput i gramatička neslaganja |
| Bez kvačica | isključeno | `č ć ž š đ → c c z s dj`, primenjuje se na kraju |
| …podeli na pasuse | uključeno | prazan red između smisaonih celina |
| …skrati i pojednostavi | isključeno | izbaci poštapalice, razbij duge rečenice; činjenice ostaju |
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
| `polish` | `false` | uključuje se iz menija |
| `polish_api_key` | `""` | bez njega režim ne radi |
| `polish_model` | `""` | prazno = `gemini-flash-lite-latest` |
| `polish_prompt` | `""` | prazno = ugrađeno uputstvo |
| `polish_paragraphs` | `true` | deli tekst na pasuse, prazan red između |
| `polish_concise` | `false` | skrati i pojednostavi |
| `output_language` | `""` | jezik izlaza, slobodan opis; prazno = bez prevoda |
| `polish_count` / `polish_count_day` | — | brojač poziva za tekući dan, upisuje ga aplikacija |

Zašto jednim pozivom na kraju a ne po segmentu: model bi inače video krhotine i
izmišljao krajeve rečenica, a broj poziva bi za deset minuta diktata skočio sa
jednog na oko sto pedeset.

Ako model zakaže, lepi se **nedoteran** tekst — model je dodatak, ne uslov.

Ako je *AI sluša snimak* uključeno, taj prolaz već vraća sređen tekst, pa se
poseban poziv za *sredi tekst* **preskače** — isti posao se ne radi dvaput
(izmereno: vraćao je identičan tekst za 0.7s). Ostali alati (pasusi, sažimanje,
emotikoni) se i dalje traže drugim pozivom.

Kad je *sredi tekst* uključeno, posle modela se primenjuju još samo `join_thousands`
i `ascii_diacritics`. `lowercase` i `strip_punctuation` se preskaču: to je baš
ono što je model dobio da uradi.

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

## Testovi

```bash
./run.sh tests     # 53 testa: pravila nad tekstom, uputstva modelu, tok diktata
```

Ne traže ni mikrofon ni mrežu ni ključ. Android ima svojih 24: `cd android && ./gradlew test`.

## Ako se ne prepozna sve što si rekao

Uključi **Snimaj za debug** iz menija. Svaki diktat se tada snima u `~/Diktat-debug`:

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
