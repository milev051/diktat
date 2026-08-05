# Diktat (Android)

Zadrži **bočni taster**, pričaj, zadrži ga ponovo — tekst se upiše tamo gde ti
je kursor. Bez naloga i bez ključeva, isti Google Web Speech endpoint kao macOS
verzija.

```
00 … 14   snima            (zeleno)
15 … 30   snima             (crveno)
30        obrađuje          (žuto)
```

Staje samo na 30s, jer endpoint odbija duže zahteve.

---

## Rezultat probe

Pre pisanja je napravljena probna aplikacija koja se prijavila na četiri mesta u
sistemu i sa svakog vraćala svoj marker. **Sva četiri puta rade** na testiranom
Samsung telefonu:

| | mehanizam | radi | uloga u ovoj aplikaciji |
|---|---|---|---|
| A | `RecognitionService` | ✓ | mikrofon na Samsung tastaturi — **bez Pristupačnosti** |
| B | `InputMethodService` | ✓ | nije korišćen — traži prebacivanje tastature |
| C | `ASSIST` (bočni taster) | ✓ | **glavni okidač** |
| E | Quick Settings pločica | ✓ | rezervni okidač |

Zato aplikacija nudi **dva nezavisna puta**: bočni taster (C) i mikrofon na
postojećoj tastaturi (A). Prvi radi svuda ali traži Pristupačnost, drugi ne
traži ništa osim mikrofona ali radi samo iz tastature.

---

## Instalacija

```bash
./build.sh install     # napravi APK i pošalji na povezan telefon
./build.sh             # samo napravi APK (~830 KB)
```

Bez kabla: prebaci `app/build/outputs/apk/debug/app-debug.apk` kako ti odgovara.
Android traži da dozvoliš instalaciju iz nepoznatog izvora — to se odobrava
aplikaciji kojom otvaraš fajl, ne samom Diktatu.

---

## Podešavanje

Otvori aplikaciju; ekran ima dugmad koja vode na svako od ovih mesta jer su na
Samsungu zakopana.

**Za bočni taster:**

1. **Digitalni asistent** → izaberi Diktat
2. **Prikaz preko drugih aplikacija** → dozvoli (tajmer)
3. **Pristupačnost** → uključi Diktat (upis u polje)

Bez trećeg tekst i dalje radi, ali završi u clipboard-u pa ga lepiš ručno.
Ekran aplikacije jasno kaže da li je Pristupačnost uključena.

**Za mikrofon na tastaturi:** *Voice input* → izaberi Diktat. Radi sa Samsung
tastaturom; Gboard po pravilu ignoriše sistemski izbor i koristi svoje
prepoznavanje.

---

## Obrada teksta

Isto što radi i macOS verzija, sve se menja u aplikaciji:

| | podrazumevano | |
|---|---|---|
| Sve malim slovima | uključeno | |
| Bez interpunkcije | uključeno | brojevi ostaju celi — `3,5` se ne kvari |
| Razmak na kraju | uključeno | da se rečenice nadovezuju |
| Maskiraj psovke | isključeno | `pFilter=0` |
| Bez kvačica | **isključeno** | `č ć ž š đ → c c z s dj` |
| Skraćenice | uključeno | `ne znam → nzm`, `jebi ga → jbg`; lista se menja u aplikaciji |

Skraćenice se poklapaju samo kao **cele reči** — `znamenito` i `poznam` ostaju
netaknuti — a duže fraze idu prve, da pravilo za `znam` ne pojede `ne znam`.

Pravilo za interpunkciju je isto ono provereno na Mac-u: tačka i zarez se brišu
samo kad **nisu između cifara**, jer ih endpoint vraća kao decimalni separator
(`3,5`, `20,5 RSD`). Crtica se briše samo kad stoji sama, da `crno-beli` ostane
celo.

---

## Zašto je ovo jednostavnije od macOS verzije

Polovina onoga što je mučilo Mac ovde ne postoji:

| problem na Mac-u | ovde |
|---|---|
| hvatanje globalnog tastera | sistem sam zove aplikaciju |
| lepljenje preko sintetičkog Cmd+V | `ACTION_SET_TEXT` na fokusiranom polju |
| aplikacija sabotira sopstveni diktat | nema sintetičkih tastera |
| gubljenje poslednje reči (`tail_seconds`) | ti sam završavaš snimanje |
| PortAudio keš uređaja | `AudioRecord` uzima sistemski ulaz |

Ostaje jedan isti problem: **prozorčić sa tajmerom ne sme da uzme fokus**, inače
polje u koje pišemo ostane bez kursora. Rešeno sa `FLAG_NOT_FOCUSABLE`, isto kao
`NSWindowStyleMaskNonactivatingPanel` na Mac-u.

Jedna razlika u ponašanju: bočni taster šalje samo „pokreni", nema događaj za
puštanje. Zato radi kao **prekidač** — prvi pritisak počinje, drugi završava.

---

## Struktura

```
app/src/main/java/studio/room211/diktat/
  MainActivity.kt        podešavanja i prečice do sistemskih ekrana
  AssistActivity.kt      okidač sa bočnog tastera (providan, odmah se zatvara)
  DictationService.kt    snimanje, tajmer preko ekrana, isporuka teksta
  InsertService.kt       upis u polje u kome je kursor (Pristupačnost)
  SttService.kt          put A — mikrofon na postojećoj tastaturi
  TileService.kt         rezervni okidač
  Recorder.kt            mikrofon → 16 kHz PCM
  WebStt.kt              endpoint i parsiranje odgovora
  TextPolish.kt          mala slova, interpunkcija, kvačice
  Config.kt              podešavanja
build.sh                 napravi i instaliraj
```
