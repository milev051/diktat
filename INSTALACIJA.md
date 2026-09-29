# Instalacija Diktata (uputstvo za agenta)

Ovo je uputstvo za AI agenta kome je korisnik dao link
`https://github.com/milev051/diktat` i rekao da instalira Diktat. Radi redom,
korak po korak. Posle instalacije ništa ne treba održavati ručno: ažuriranja
stižu kroz samu aplikaciju, i na Mac-u i na telefonu.

Ako korisnik traži izmenu koda, a ne instalaciju, ovo nije tvoje uputstvo:
pročitaj `CLAUDE.md`.

---

## Šta korisnik dobija

- **Mac:** aplikacija u traci menija. Desni Option (ili taster `§`) pokreće i
  zaustavlja diktat, a tekst se upisuje tamo gde je kursor.
- **Telefon (Android):** bočni taster ili mikrofon na Gboard tastaturi.
- Osnovno prepoznavanje radi **bez naloga i bez ključeva**. Ključevi za AI
  obradu (Gemini, Groq, OpenAI) su opcioni i korisnik ih unosi sam, kasnije.

---

## Mac

### 1. Proveri uslove

```bash
sw_vers -productVersion     # macOS 12 ili noviji
uname -m                    # mora biti arm64 (Apple Silicon, M1 i noviji)
command -v brew             # Homebrew
xcode-select -p             # alati za komandnu liniju (za swiftc)
```

- `uname -m` vraća `x86_64` (Intel Mac): stani i javi korisniku. `setup.sh`
  traži Homebrew na `/opt/homebrew`, koji Intel Mac nema.
- Nema Homebrew-a: pitaj korisnika da ga instalira sa https://brew.sh (traži
  lozinku računara, pa to ne radiš umesto njega).
- Nema alata za komandnu liniju: pokreni `xcode-select --install` i reci
  korisniku da potvrdi prozor koji iskoči, pa sačekaj da se završi.

```bash
brew install python@3.13 portaudio
brew install ffmpeg          # opciono: manji snimci (FLAC)
```

### 2. Kloniraj u `~/Diktat`

```bash
git clone https://github.com/milev051/diktat.git ~/Diktat
cd ~/Diktat
```

**Ne na Desktop, Documents ni Downloads.** macOS aplikaciji pokrenutoj iz
Launchpad-a tiho zabranjuje pristup tim folderima, pa dugme za ažuriranje ne bi
moglo da osveži i ovaj folder (vidi „Ažuriranje").

### 3. Napravi okruženje i proveri kod

```bash
./setup.sh          # .venv, biblioteke, config.json
./run.sh tests      # mora da prođe; ne traži mikrofon ni mrežu
```

### 4. Instaliraj aplikaciju

```bash
./Instaliraj.command
```

Napravi `/Applications/Diktat.app`, kopira kod u
`~/Library/Application Support/Diktat` i pokrene Diktat. U traci menija se
pojavi ikonica. Ista komanda kasnije služi i za ažuriranje iz ovog foldera, a
dozvole pri tome ostaju.

### 5. Dozvole (radi ih korisnik)

Diktatu trebaju **Mikrofon** i **Accessibility**. Agent ih ne može odobriti,
jer macOS to dozvoljava samo korisniku. Otvori mu oba ekrana:

```bash
open "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"
open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
```

i reci mu: „U oba spiska uključi **Diktat**. Ako ga nema u Accessibility,
klikni `+` i izaberi `/Applications/Diktat.app`.“ Mikrofon macOS obično sam
zatraži pri prvom diktatu.

Posle odobrenja pokreni Diktat iznova, da pokupi dozvole:

```bash
open /Applications/Diktat.app
```

### 6. Proba

Zamoli korisnika da klikne u neko polje za tekst, pritisne **desni Option**,
kaže rečenicu i ponovo pritisne desni Option. Tekst treba da se upiše u polje.

Ako ne radi, pogledaj log:

```bash
tail -30 ~/Library/Logs/Diktat.log
```

„This process is not trusted“ u logu znači da Accessibility nije odobren.

### 7. Ključevi (opciono, radi ih korisnik)

Ključevi se unose u aplikaciji: klik na ikonicu u traci menija, pa treća kolona
**Ključevi**. **Nikad ne traži vrednost ključa u razgovoru** i ne upisuj ga u
fajlove repozitorijuma. `config.json` sa ključevima je u `.gitignore` i ostaje
samo na tom računaru.

---

## Telefon (Android)

APK poslednjeg izdanja je uvek na istoj adresi:

```
https://github.com/milev051/diktat/releases/latest/download/app-release.apk
```

**Telefon povezan kablom, sa uključenim USB debugging-om:**

```bash
curl -L -o /tmp/diktat.apk https://github.com/milev051/diktat/releases/latest/download/app-release.apk
adb install -r /tmp/diktat.apk
```

**Bez kabla:** pošalji korisniku gornju adresu. Otvori je na telefonu,
preuzme APK i instalira ga. Android pita da dozvoli instalaciju iz nepoznatog
izvora, i to se odobrava pregledaču kojim se fajl otvara.

**Podešavanje** radi korisnik, u samoj aplikaciji. Kartica **Nedostaju
dozvole** na vrhu ekrana ima dugme za svaku stavku i nestaje kad je sve
odobreno. Za bočni taster: Digitalni asistent → Diktat, Prikaz preko drugih
aplikacija, Pristupačnost → Diktat. Detalji: `android/README.md`, odeljci
„Dozvole" i „Podešavanje".

---

## Ažuriranje

Posle instalacije se ništa ne radi ručno.

- **Mac:** aplikacija pri pokretanju i jednom dnevno pita GitHub za novo
  izdanje. Kad postoji, u traci menija stoji **↑**, a u Podešavanjima zeleno
  dugme „Ažuriraj". Jedan klik zameni kod aplikacije i pokrene je iznova, pa
  dozvole ostaju. Posle toga osveži i folder iz koga je instalirana
  (`~/Diktat`) sa `git pull`, ali samo ako je folder na grani `main` i nema
  izmena koje nisu uvedene. Inače ga ne dira, a razlog upiše u log.
- **Telefon:** kartica **Verzija i ažuriranje** javi novu verziju, a jedan
  pritisak preuzme i instalira APK. Podešavanja i ključevi ostaju.

Ručno ažuriranje iz foldera, kad treba:

```bash
cd ~/Diktat && git pull && ./Instaliraj.command
```

---

## Kad nešto ne ide

| simptom | uzrok | šta uraditi |
|---|---|---|
| `setup.sh`: „Nedostaje Python 3.13" | nema Homebrew Python-a | `brew install python@3.13` |
| „swiftc nije uspeo" pri instalaciji | nema alata za komandnu liniju | `xcode-select --install`, pa ponovo `./Instaliraj.command` |
| taster ne radi, u logu „not trusted" | Accessibility nije odobren | korak 5 |
| diktat radi, a tekst ne stiže u polje | Accessibility odobren staroj verziji | u Accessibility ukloni Diktat (`-`), dodaj ga ponovo, pa `open /Applications/Diktat.app` |
| posle `make_app.sh install` dozvole ne rade | pun `install` pravi novi potpis | to je očekivano; odobri ponovo. Za obične izmene koristi `./Instaliraj.command`, koji dozvole čuva |
| prepoznavanje ne odgovara | Google servis je nedokumentovan | `./run.sh doctor` pokazuje gde je problem |
