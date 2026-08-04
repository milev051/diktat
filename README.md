# Diktat

Diktiranje na macOS-u: **drži desni Command**, pričaj, pusti — tekst se pojavi u aplikaciji
u kojoj si trenutno. U menu baru ikonica pokazuje stanje.

```
menu bar:   ⚪ spremno    🟢 snima    🟡 obrađuje    ⚠️ greška
na ekranu:  ( 0:12 ) zeleno = snima     ( 0:12 ) žuto = obrađuje
```

---

## Dva motora

Bira se u meniju (**Motor**) ili u `config.json` (`"engine"`).

| | `web` — besplatni | `cloud` — Google Cloud v2 |
|---|---|---|
| **Podešavanje** | nikakvo, radi odmah | nalog + kartica + ključ (~5 min) |
| **Cena** | besplatno | 60 min/mesec gratis, pa ~$0.016/min |
| **Reč po reč uživo** | ne — tekst tek po puštanju | **da**, dok pričaš |
| **Kašnjenje** | ~1.3s (kratko), ~5s (24s snimak) | ~200-400ms po reči |
| **Interpunkcija** | nema | ima |
| **Srpski** | vrlo dobar (izmereno 0.93) | vrlo dobar |
| **Dužina** | neograničeno (seče se na pauzama) | do 5 min |
| **Rizik** | nedokumentovan endpoint, Google ga može ugasiti | zvanično podržan |

Podrazumevano je **`web`** — nema šta da se podešava.

> `web` je onaj stari Chromium `speech-api/v2` endpoint, isti koji zove
> `SpeechRecognition.recognize_google()`. Radi godinama i danas je proveren, ali
> je nedokumentovan i koristi javni ključ. Zato je `cloud` tu kao rezerva —
> prebacivanje je jedan klik u meniju.

---

## Instalacija

```bash
./setup.sh          # venv + zavisnosti + config.json
./make_app.sh       # pravi Diktat.app (preporučeno, vidi 'Dozvole')
./run.sh doctor     # provera
```

Sa `web` motorom to je sve. Pokreni `Diktat.app` i radi.

---

## Dozvole

macOS traži dve. Ako si napravio `Diktat.app`, pokreni ga dvoklikom pa odobri:

| Dozvola | Gde | Čemu služi |
|---|---|---|
| **Microphone** | System Settings → Privacy & Security → Microphone | snimanje govora |
| **Accessibility** | System Settings → Privacy & Security → Accessibility | čitanje desnog Command-a i lepljenje |

**Zašto `.app` a ne `./run.sh`:** iz terminala macOS veže dozvole za Terminal,
pa ti hotkey pukne čim promeniš terminal ili ga apdejtuješ. `Diktat.app` je
potpisan i ima svoj identitet, pa dozvole drže.

Autostart: System Settings → General → Login Items → `+` → `Diktat.app`.

---

## Korišćenje

- **Drži desni Command**, pričaj, **pusti** → tekst se zalepi gde ti je kursor.
- Gore desno se pojavi mala pilula sa vremenom. **Boja je ceo indikator:**
  zelena dok snima, žuta dok se obrađuje. Vreme se na kraju snimanja zamrzne
  i stoji na žutoj dok tekst ne stigne. **Žuti prsten oko zelene** znači da
  snimaš, a prethodni segment se još obrađuje u pozadini.
  Za prikaz na dnu sredine: `"overlay_position": "bottom"`.
- **Snimanje se ne prekida naglo kad pustiš taster** — nastavlja još `tail_seconds`
  (0.8s), jer se taster pušta tačno na kraju poslednje reči pa bi se ona izgubila.
- **Možeš odmah da kreneš u sledeći diktat dok se prethodni još obrađuje.** Mikrofon
  se oslobađa čim pustiš taster, a prepoznavanje se nastavlja u pozadini. HUD tada
  pokazuje `· obrađujem 1`. Tekst se lepi **po redosledu snimanja**, i kad se kraći
  drugi snimak prepozna pre dužeg prvog.
- **Na dugom diktatu se snimak sam seče na pauzama.** Posle 10s, svaka pauza od
  ~0.7s odseca deo i šalje ga na obradu dok ti nastavljaš da pričaš. Zato više
  **nema granice od 30s** — možeš diktirati koliko hoćeš.
- Zato se isplati diktirati u kraćim celinama — dok pričaš sledeću, prethodna se već obrađuje.
- Ako umesto diktata pritisneš **prečicu** (Cmd+V, Cmd+Tab…), snimanje se otkazuje
  i ništa se ne ubacuje. Desni Command i dalje radi kao normalan Command.
- Kratak tap (ispod `min_seconds`) se takođe ignoriše.

Iz menija: motor, jezik, režim, kopiranje poslednjeg teksta, otvaranje configa.

---

## Google Cloud podešavanje (samo za `engine: "cloud"`)

Treba ti samo ako hoćeš **reč po reč uživo** i interpunkciju.

1. <https://console.cloud.google.com> → novi projekat.
2. Uključi **Cloud Speech-to-Text API**:
   <https://console.cloud.google.com/apis/library/speech.googleapis.com> → *Enable*.
3. Uključi billing (Billing → Link a billing account).
4. *IAM & Admin → Service Accounts → Create* → ime `diktat` → rola
   **Cloud Speech Client** → *Done*. Pa *Keys → Add Key → Create new key → JSON*.
5. Skloni ključ i podesi:

```bash
mkdir -p ~/.config/diktat
mv ~/Downloads/tvoj-kljuc.json ~/.config/diktat/google-key.json
chmod 600 ~/.config/diktat/google-key.json
```

6. U `config.json` stavi `"engine": "cloud"`, pa `./run.sh doctor`.

Doktor testira nekoliko kombinacija regiona i modela i **sam upiše onu koja radi**
za tvoj jezik — dostupnost za `sr-RS` nije ista u svim regionima.

> Ključ je lozinka za naplativ servis. `.gitignore` već isključuje `config.json`.

---

## Podešavanja (`config.json`)

| Ključ | Podrazumevano | Objašnjenje |
|---|---|---|
| `engine` | `web` | `web` (besplatno) ili `cloud` (reč po reč) |
| `web_api_key` | `""` | prazno = ugrađeni javni ključ |
| `capitalize_first` | `true` | web motor ne vraća veliko početno slovo |
| `profanity_filter` | `false` | `true` bi maskirao psovke (`sranje` → `s*****`) |
| `language_codes` | `["sr-RS"]` | menja se i iz menija |
| `hotkey` | `cmd_r` | `cmd_l`, `alt_r`, `ctrl_r`, `f13`… |
| `mode` | `hold` | `hold` = drži taster, `toggle` = pritisni/pritisni |
| `min_seconds` | `0.35` | kraći pritisak = obična prečica, ne diktat |
| `insert_method` | `paste` | `paste`, `type` (znak po znak), `clipboard_only` |
| `restore_clipboard` | `true` | vraća stari clipboard posle lepljenja |
| `show_overlay` | `true` | prikaz stanja preko ekrana |
| `overlay_position` | `top-right` | `top-right` (kao notifikacija) ili `bottom` |
| `trailing_space` | `true` | razmak na kraju, da se rečenice nadovezuju |
| `input_device` | `null` | `null` = sistemski mikrofon |
| `auto_segment` | `true` | seci dug snimak na pauzama i slati u delovima |
| `segment_after_seconds` | `10` | pre ovoga se nikad ne seče |
| `pause_seconds` | `0.7` | koliko tišine znači „kraj misli" |
| `web_max_seconds` | `30` | najduži pojedinačni zahtev ka endpointu |
| `max_seconds` | `290` | granica za `cloud` motor |
| `tail_seconds` | `0.8` | koliko još snima pošto pustiš taster |
| `credentials_json` / `location` / `model` / `punctuation` | — | samo za `cloud` |

Posle izmene fajla treba restart (motor, jezik i režim rade odmah iz menija).

---

## Ako se ne prepozna sve što si rekao

Uključi **Snimaj za debug** iz menija (ili `"debug": true`). Svaki diktat se
tada snima u `~/Diktat-debug`:

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
- **Pokrivaju ga, ali ima praznih** → Google nije prepoznao taj deo; pusti
  taj `.wav` i čuj šta je unutra.
- **Nema ga ni u `full.wav`** → gubi se u snimanju, ne u prepoznavanju.

Ne zaboravi da isključiš — snima svaki diktat na disk.

## Ako nešto ne radi

Prvo uvek `./run.sh doctor`.

**Hotkey ne reaguje** → nema Accessibility dozvole. Ako si već dodao aplikaciju,
izbaci je iz liste (`−`) pa dodaj ponovo — macOS ume da zapamti stari potpis.

**Tekst se ne lepi** → probaj `"insert_method": "type"`. Neki terminali i Java
programi ne primaju sintetički Cmd+V. Tekst je uvek i u clipboard-u, plus u meniju
stoji „Kopiraj poslednji tekst".

**Web motor vraća 403 ili prazno** → Google je verovatno stegao endpoint.
Prebaci na `cloud` u meniju.

**Duži diktat na `web` motoru zakaže** → granica je `web_max_seconds` (30s). HUD
u poslednjih 10s prelazi u odbrojavanje (`još 8s`) i tačka požuti. Snimanje se
samo prekida na granici i tekst se svejedno ubaci. Diktiraj u kraćim celinama —
ionako je brže jer se obrađuju paralelno.

**Loše prepoznaje srpski na `cloud`** → probaj `"model": "chirp_2"` uz
`"location": "europe-west4"`.

---

## Struktura

```
dictate/
  app.py       menu bar, stanja, orkestracija (UI samo iz glavne niti)
  hotkey.py    detekcija desnog Command-a + otkazivanje na prečice
  audio.py     mikrofon → 16 kHz PCM komadi
  stt.py       Google Cloud v2 streaming (motor "cloud")
  webstt.py    besplatni Chromium endpoint (motor "web")
  overlay.py   HUD koji ne krade fokus
  insert.py    lepljenje/kucanje u aktivnu aplikaciju
  config.py    config.json
doctor.py      dijagnostika, po motoru
run.py         ulazna tačka
make_app.sh    pravi Diktat.app
```
