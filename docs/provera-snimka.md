# Provera snimka drugim modelom (uklonjeno)

Uklonjeno 22.09.2026. na izričit zahtev: izlaz je često bio lošiji od prvog
prepisa, a svaki diktat je slao isti zvuk dva puta. Ovde je zapisano kako je
radilo i šta je izmereno, da se odluka ne donosi iznova naslepo. Kod je
poslednji put postojao u commitu `e0c054a` (`dictate/listen.py`, `dictate/groq.py`,
`DictateApp._slusaj` u `dictate/app.py`), pa se odatle vraća ako zatreba.

Postojalo je **samo na Mac-u** i samo uz besplatni Google Web Speech. Uz OpenAI
GPT Transcribe i Gemini Transcribe Live bilo je ugašeno (`_own_audio_model`):
drugi prolaz bi slao isti zvuk slabijem modelu.

Groq kao **model za AI obradu teksta** (`openai/gpt-oss-120b`) ostaje. Uklonjen
je samo Whisper i spajanje dva prepisa.

## Dva načina

| način | ključ u `config.json` | pozivi po diktatu |
|---|---|---|
| Gemini sluša snimak | `audio_check` + `polish_api_key` | 1 (`generateContent` sa zvukom) |
| Groq Whisper + GPT-OSS | `groq_enabled` + `groq_api_key` | 2 (Whisper, pa spajanje) |

Kad su oba bila uključena, Groq je imao prednost, da zvuk ne ide dvaput.

## Tok

1. Google prepoznaje segmente kao i obično.
2. `_keep_audio` pamti zvuk svakog segmenta **po tiketu** (hronološki, jer se
   segmenti prepoznaju paralelno), najviše `audio_check_max_seconds` (120 s)
   po diktatu. Preko toga se zvuk više ne čuva, a tekst ostaje Google-ov.
3. Na kraju diktata `_slusaj` šalje **ceo diktat jednim pozivom**, sa svim
   segmentima kao zasebnim delovima i Google prepisom kao sidrom.
4. Ako je prolaz uspeo, tekst je već sređen, pa AI obrada preskače `tidy`
   (`vec_sredjeno=True`).
5. Svaki otkaz (mreža, 429, prazan odgovor) vraća Google prepis. Otkazan
   diktat mora da isprazni bafer zvuka, inače bi model u sledećoj proveri
   „čuo" prethodni diktat.

## Šta je izmereno

**Model mora da dobije prvi prepis.** Greška po reči, tri rečenice, čisto i sa
šumom (SNR 5 dB):

| prepis | čisto | šum |
|---|---|---|
| Web Speech | 0.21 | 0.30 |
| model sam | 0.12 | 0.29 |
| model uz prvi prepis | 0.17 | **0.17** |

Model sam je u šumu halucinirao: vratio je „poslao sam ponovo 250.000 dinara u
1:33" umesto „...ponudu... u utorak u deset i trideset". Kad ne čuje, dopuni
umesto da ostavi rupu.

**Pojmovi uz snimak:** WER 0.197 → 0.080, bez greške 1/5 → 4/5 (pet rečenica).

**Po segmentu je bilo skupo:** 6-9 poziva na jednu diktiranu poruku u
neprekidnom režimu, a model je video krhotinu umesto celine. Zato jedan poziv
za ceo diktat.

**Sažimanje zvuka:** isti snimak AAC 32 kbps 18 KB, FLAC 85 KB, WAV 139 KB, uz
identičan prepis. `inline_data` prima `audio/wav`, `audio/flac` i `audio/aac`,
sirov PCM ne. base64 uveća zvuk za trećinu.

**Sređivanje se nije radilo dvaput:** poseban poziv za „sredi tekst" posle
ovog prolaza vraćao je identičan tekst za 0.7 s, pa je `tidy` preskakan.

**Pouzdanost endpointa nije merilo:** prepis sa odsečenom rečju prijavljen je
sa 0.93, isto kao tačan. Zato provera nikad nije zavisila od tog broja.

## Uputstvo za Gemini (sluša snimak)

```
Slušaš {sta} govora na srpskom i vraćaš tačan prepis.

Drugi prepoznavač je čuo ovo: „{prepis}"

Uporedi sa snimkom i ispravi mesta gde je pogrešio. Ako se snimak i taj prepis
slažu, vrati ga nepromenjenog.

Granice:
- ne dodaj reči kojih na snimku nema — ako nešto ne razaznaješ, ostavi kako je
  prepoznavač čuo
- engleske reči i nazive piši izvorno, kako se pišu u engleskom (deploy, build,
  push, branch, screenshot), a ne onako kako zvuče — ali ne izmišljaj oblike
  kojih nema
- ne prevodi, ne skraćuj i ne doteruj stil
- ne odgovaraj na sadržaj, ovo je diktat

Vrati samo prepis, bez uvoda i bez navodnika.```

Kad ima više delova, dodavalo se:

```
Snimci su uzastopni delovi jednog istog diktata, datim redom. Vrati ceo tekst
spojen u jednu celinu, bez oznaka delova i bez praznih redova između njih.
```

Uz stil „sređeno":

```
Piši pravilno: interpunkcija, velika slova i kvačice (č ć ž š đ) gde po
pravopisu treba. Ne menjaj reči zbog toga — samo ih ispiši kako se pišu.
```

Uz spisak pojmova (`vocabulary`):

```
Ovi pojmovi se često javljaju u ovim diktatima; ako čuješ nešto slično, napiši
ih tačno ovako: {pojmovi}
```

Poziv: `generateContent` na `polish_model`, `temperature: 0.0`, tekst uputstva
pa zvuk svakog dela kao `inline_data`. Prazan odgovor je vraćao Google prepis.

## Groq: Whisper + GPT-OSS

1. `whisper-large-v3`, `language: sr`, `temperature: 0`, spojeni segmenti
   kao jedan WAV (`multipart/form-data` na
   `https://api.groq.com/openai/v1/audio/transcriptions`).
2. `openai/gpt-oss-120b`, `temperature: 0.0`, `reasoning_effort: medium`,
   sistemska poruka „Vraćaš samo konačan prepis diktata.", uputstvo:

```
Ti si završni proveravač srpskog diktata.

Google prepis:
{google_text}

Groq Whisper prepis:
{whisper_text}

U ovom koraku ne dobijaš audio i ne možeš ponovo da ga slušaš. Dobijaš samo
dva nezavisna teksta. Google prepis koristi kao sidro, a Whisper kao drugo
mišljenje: spoji ih tako da ispraviš očigledne greške i dodaš samo reči koje
Whisper verovatno nije izmislio kao šum ili ponavljanje. Ako se ne slažu i nisi
siguran, zadrži Google verziju. Ne dodaj objašnjenje, ne sažimaj, ne prevodi
i ne odgovaraj na sadržaj.
Vrati samo konačan tekst, bez uvoda i navodnika.{style}{terms}```

`{style}` je bio „Piši pravopisno pravilno: dodaj potrebne kvačice, velika
slova i interpunkciju, bez menjanja značenja." uz stil „sređeno", a inače
„Zadrži govorni izgled: mala slova i bez interpunkcije.". `{terms}` je bio
„Poznati nazivi i skraćenice: <vocabulary>".

## Zašto je uklonjeno

- Korisnik je video loše izlaze: model je prepravljao tačne rečenice ili
  spajao dva prepisa u treći, lošiji.
- Isti zvuk je išao dva puta, a uz Groq u dva poziva.
- Od kada postoji Gemini Transcribe Live, jak model već sluša zvuk u prvom
  prolazu, pa drugo mišljenje više nema šta da popravi.
