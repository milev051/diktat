# Diktat (Android)

Zadrži **bočni taster**, pričaj, zadrži ga ponovo — tekst se upiše tamo gde ti
je kursor. Bez naloga i bez ključeva, isti Google Web Speech endpoint kao macOS
verzija.

```
00 … 14   snima            (zeleno)
15 … 30   snima             (crveno)
30        obrađuje          (žuto)
```

**Google neprekidno snimanje** prikazuje se neposredno ispod izbora Google
provajdera. Ukida standardnu granicu: seče na pauzama i šalje delove dok
snimanje teče dalje, pa tekst stiže usput. Sigurnosna granica ostaje jedan sat.
Kada se izabere OpenAI, ova opcija nestaje i na njenom mestu se prikazuju
**OpenAI dugi diktat** i izbor pisma.

U običnom režimu staje na 30s — i zato što endpoint odbija duže zahteve, i da slučajno
pokrenut diktat ne snima satima. Nastavak traži nov pritisak.

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

## Koja je verzija instalirana

Piše na vrhu ekrana aplikacije, pored imena — `Diktat v0.4`. Ako se ne poklapa
sa `versionName` u `app/build.gradle.kts`, instalacija je stara.

**Česte fraze su deo builda i prikazuju se samo za čitanje.** Nove или измењене
фразе уносе се у код пре новог builda, па на телефону нема дугмета којим би се
случајно обрисале.

## Instalacija

```bash
./build.sh install     # napravi APK i pošalji na povezan telefon
./build.sh             # samo napravi APK (~1.6 MB, skupljen)
./build.sh debug       # brži build bez skupljanja (~6 MB)
```

Release je skupljen R8-om — bez toga Material biblioteka nadme APK na 6.4 MB.
Potpisuje se debug ključem, pa se instalira preko postojeće instalacije.

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

**Za mikrofon na tastaturi:** *Voice input* → izaberi Diktat.

Da li tastatura zaista zove nas ili Google-a, proverava se za dve sekunde:
reci **„ne znam"**. Ako ispiše `nzm` — naš servis radi. Ako ispiše `Ne znam`
— tastatura koristi svoje prepoznavanje i ignoriše sistemski izbor.

Samsung tastatura pita servis koje jezike podržava (`GET_LANGUAGE_DETAILS`).
Bez odgovora pretpostavi engleski i odbije srpski, pa `LanguageDetailsReceiver`
na to odgovara. Gboard to ne pita.

---

## Ponašanje

| | podrazumevano | |
|---|---|---|
| Snimaj samo kad ima polja za unos | uključeno | bez toga se diktat pokrene i sa početnog ekrana pa završi u prazno |
| Ne ostavljaj tekst u clipboard-u | uključeno | clipboard se posle upisa vrati kakav je bio |

Ako upis **ne prođe**, tekst svejedno ostane u clipboard-u — izgubiti diktat je
gore nego da ostane zapisan. Zato drugi prekidač znači „ne ostavljaj kad ne
moraš", a ne „nikad".

Kartica **Istorija diktata** čuva poslednja 3 uspešna rezultata lokalno na
telefonu. Dodirni bilo koju stavku da ceo tekst kopiraš u clipboard; dugme
**Obriši istoriju** briše samo tu lokalnu listu.

Podrazumevane skraćenice su u `Abbreviations.kt`, lista `DEFAULT`. Na telefonu
se lista može pročitati, ali ne i menjati. Ugrađena pravila obuhvataju i
pretvaranje izgovorenih brojeva: `pet minuta` → `5min`, `petmin` → `5min`,
`dvadeset pet sati` → `25 sati`; iznosi poput `pet evra` ostaju `5 evra`,
bez automatskog pretvaranja u znak valute.

U kartici **Tekst** su odvojena dva prekidača: **Sva slova mala** i **Ukloni
interpunkciju**. Drugi uklanja znakove, ali čuva separatore u brojevima kao
`10:30`, `3,5`, `2.0`, `1/2` i `10-20`; navodnici, crtice, zagrade i simboli se
uklanjaju. Oba prekidača rade i posle AI obrade.

## Ako prepoznavanje zakaže

Prolazne greške (mreža, timeout, 429, 5xx) automatski se pokušavaju do šest puta
ukupno. Ako i šesti pokušaj padne, **snimak se čuva** — sekcija *Sačuvani audio*
pokazuje koliko ih ima i šalje ih ponovo. Pamti se i provajder prvog pokušaja,
pa se snimak ne šalje slučajno drugom servisu ako u međuvremenu promeniš izbor.
Drži se poslednja 3.

## Gemini 3.5 Transcribe Live

U kartici *AI* izaberi **Provider transkripcije → Gemini 3.5 Transcribe Live**.
Koristi **isti Gemini ključ** kao AI obrada teksta (`polish_api_key`), pa se ne
unosi drugi.

```text
gemini-3.5-transcribe-live
```

**Zvuk se šalje DOK pričaš, ne posle Stop-a.** Zato posle Stop-a nema čekanja
koje raste sa dužinom diktata. Izmereno na 64.7s zvuka: slanje posle Stop-a
ostavlja 15.6s čekanja, slanje u toku 0.0s; ukupno posle Stop-a ostane ~1.5s.

Zbog toga važe dve stvari kojih kod Google-a nema:

| | |
|---|---|
| **Internet mora da radi celo vreme snimanja** | ranije je trebao tek na kraju; prekid usred diktata sada obara diktat (snimak se čuva za ponovni pokušaj) |
| **Troši ~2,5 MB po minutu** | Live API prima samo sirov PCM, FLAC se ne može poslati — oko dvostruko više nego Google uz FLAC |

Prepis stiže na latinici: endpoint za `sr-RS` vraća ćirilicu, i to nedosledno,
pa se pismo poravnava pre svega ostalog. Tekst se i dalje ubacuje **odjednom na
kraju** — „Live" je ime modela, ne prikaz reč-po-reč.

Obična varijanta `gemini-3.5-transcribe` nije ugrađena: na besplatnom nivou ima
3 zahteva u minuti i 25 dnevno, što za svakodnevni rad ne znači ništa. Live
varijanta nema ni jednu ni drugu granicu.

## OpenAI GPT transkripcija

U kartici *AI* izaberi **Provider transkripcije → OpenAI GPT Transcribe**. Google
Speech-to-Text je podrazumevan i vraća se izborom **Google Speech-to-Text**.
OpenAI režim koristi samo završeni snimak posle Stop-a i model:

```text
gpt-transcribe
```

Pauze u govoru ne prave zasebne OpenAI pozive. Uobičajeni diktat se šalje kao
jedan zahtev posle Stop-a; samo snimak duži od pet minuta deli se na veće
komade zbog ograničenja veličine audio-fajla.

U kartici **API ključevi** dugme **Proveri sve API ključeve** proverava Gemini,
Groq i OpenAI bez slanja audio-snimka i bez trošenja transkripcionih minuta.

Ne koristi `gpt-live-transcribe`, WebSocket, WebRTC ni govor-u-govor tok. Poziv
ide na `POST https://api.openai.com/v1/audio/transcriptions` kao
`multipart/form-data`, sa `file`, `model=gpt-transcribe`, `languages[]=sr`,
srpskim promptom i JSON odgovorom.

Кључ се уноси у посебној секцији **API ključevi**, где постоје одвојена поља
за Gemini, Groq и OpenAI. Кључеви се чувају локално; ниједан није уграђен у
source code или APK. За јавну дистрибуцију препоручује се backend/proxy, јер
директан клијентски позив открива кључ на уређају.

Опција **OpenAI dugi diktat (do 60 min)** заобилази стандардну границу од 30
секунди, али намерно има фиксни сигурносни лимит од 60 минута. Ако микрофон
остане укључен, снимање се зато аутоматски прекида.

Снимак се прво покушава послати као **FLAC** преко постојећег Android енкодера;
ако енкодер није доступан или не успе, шаље се **WAV** са 16 kHz, 16-bit, mono
PCM-ом. Проверавају се празан/прекратак снимак и граница од 25 MB. Мрежне грешке,
timeout, 401/403, 400, 413, 429 и 5xx добијају јасну поруку; timeout, мрежа,
429 и 5xx се једном понове, а неуспео аудио остаје сачуван за поновни покушај.

Подешавање **OpenAI output script** има три вредности:

| избор | понашање |
|---|---|
| Auto | модел бира писмо |
| Ćirilica | моделу се тражи српска ћирилица |
| Latinica | моделу се тражи латиница; ако врати ћирилицу, локално се детерминистички пребацује у латиницу |

Локална конверзија обрађује `љ/њ/џ` пре једнословних мапирања (`lj/nj/dž`) и
не мења интерпункцију, размаке, велика и мала слова, бројеве, URL-ове, енглеске
речи или преломе редова. Google и сви остали режими не пролазе кроз ову
конверзију.

Провера без телефона:

```bash
cd android && ./gradlew test
```

Тестови покривају модел/endpoint, prompt за оба писма, WAV заглавље и
ћирилица→латиница конверзију. На телефону треба пробати исти снимак у Google,
OpenAI Auto, OpenAI Ćirilica и OpenAI Latinica режимима, затим убацивање у
различита поља и слање текста у чат.

## AI obrada teksta

Kartica *AI* (bez glavnog prekidača — izabran alat znači da se AI koristi):
избори алата су одвојени од секције **API ključevi**, где се уносе Gemini,
Groq и OpenAI кључ. Ceo diktat se sačeka pa jednim pozivom ode modelu. Dok se čeka, pilula
pokazuje plavo **AI**.

U istoj kartici postoji izbor **Model za manipulaciju teksta**: Gemini ili
Groq GPT-OSS 120B. On važi za sređivanje, pasuse, tačke, ponavljanja i prevod,
dok **Provider transkripcije** ostaje zaseban izbor. Gemini i Groq dobijaju
samo već transkribovan tekst; audio иде искључиво изабраном Google или OpenAI
провајдеру транскрипције.

Alati su **nezavisni** — uputstvo se sklapa od izabranih. Ako је изабран бар
један алат и постоји одговарајући кључ, обрада се аутоматски користи.

| alat | podrazumevano | šta radi |
|---|---|---|
| Sredi tekst | isključeno | tačke i velika slova; usput i gramatička neslaganja |
| Dodaj samo zareze | isključeno | model analizira tekst i dodaje samo zareze, bez tačaka i ostalih znakova |
| Sažmi u tačke | isključeno | preuredi tekst u spisak tačaka |
| Podeli na pasuse | uključeno | prazan red između smisaonih celina |
| Jezik izlaza | prazno | slobodan opis: „makedonski", „pola makedonski pola srpski" |

Bez sređivanja model **ne dira** interpunkciju i kvačice — tako se dobija samo
kraći tekst ili samo pasusi. Ako nijedan alat nije izabran, poziva nema.

Kada su uključeni **Dodaj samo zareze**, **Podeli na pasuse**, **Sva slova
mala** i **Ukloni interpunkciju**, izabrani Gemini ili Groq model određuje mesta
za zareze i smisaone pasuse. Lokalna završna obrada uklanja sve остале знакове,
ali чува зарезе и двоструке нове редове између пасуса.
Зарез се додатно уклања непосредно пре или после самосталног везника `i`, као и
на крају пасуса.

Kad nijedan izabrani alat ne sme da menja reči, izlaz se poredi sa ulazom reč
po reč; ako se razlikuje, upisuje se naš tekst.

Bez *Sredi tekst* izlaz modela ide **ponovo kroz podešavanja iz sekcije Obrada
teksta** — velika slova, interpunkcija i kvačice se skidaju kako je tamo
izabrano. Model naime sređuje tekst čim prepisuje rečenice, koliko god mu se to
zabranilo u uputstvu; pasusi i emotikoni ostaju.

Ispod prekidača stoji **Poziva modelu danas: N** — Google ne nudi način da se
vidi preostala kvota, pa aplikacija broji sama; brojač se resetuje u ponoć. Ako
podešeni model nestane (404), automatski se pokušava sa
`gemini-flash-lite-latest`; ako i to padne, lepi se **nedoteran** tekst. Ključ ostaje sačuvan i posle nadogradnje aplikacije — `SharedPreferences`
preživljava instalaciju preko postojeće dok su paket i potpis isti.

## Potrošnja podataka

Aplikacija broji koliko je poslato i primljeno, a posebno meri ukupno trajanje
svih uhvaćenih snimaka. Na ekranu se prikazuju ukupno snimljene sekunde i
sekunde koje su ušle u uspešne upload-e; ta dva broja mogu malo da se razlikuju
ako zahtev ne uspe ili se snimak otkaže.
Sažimanje zvuka je uvek uključeno; ako ne uspe, šalje se sirov zvuk kao i pre.

Zvuk se šalje kao **FLAC** — oko 40% manje od sirovog PCM-a, uz identičan
transkript. Potvrđeno na telefonu. Ako sažimanje ne uspe (Android stariji od 10, ili greška enkodera),
šalje se kao pre; ušteda nikad ne obara diktat.

Endpoint prima isključivo `audio/x-flac; rate=N`. Bez `rate=` ili sa
`audio/flac` vraća 400. Opus je odbijen.

Sirovi PCM je 16 kHz × 16 bita = **31 KB po sekundi govora**; sa FLAC-om oko
19 KB. Izmereno na pravim zahtevima:

| govor | poslato | primljeno |
|---|---|---|
| 4.9s | 152 KB → **97 KB** | 186 B |
| 23.7s | 742 KB → **433 KB** | 440 B |

Za osećaj koliko je to — tipične vrednosti:

| | |
|---|---|
| **10s diktata** | **320 KB** |
| minut telefonskog poziva | 400 KB |
| jedna fotografija u poruci | 800 KB |
| minut Spotify-a | 1.1 MB |
| učitavanje jedne veb stranice | 2.2 MB |

## Procena koristi — 10 dana

U kartici **Procena koristi — 10 dana** pokreni novi period kada želiš da meriš
stvarnu vrednost diktiranja. Aplikacija lokalno beleži broj rezultata,
karaktere i sekunde snimanja po danima. Potrošnju API-ja unosiš ručno, a brzina
kucanja služi za približan proračun koliko bi ti vremena trebalo da isti tekst
otkucaš. Izveštaj prikazuje prosek po danu, cenu po diktatu, cenu na 1.000
karaktera i procenjeno vreme kucanja. Dodatno prikazuje broj poziva i vreme
zvuka po svakom korišćenom provajderu/modelu, da se Google i OpenAI mogu
uporediti na istom desetodnevnom uzorku. Podaci ostaju na telefonu.

## Tekst

Kartica *Tekst* drži ono što radi sam kod, bez modela i bez ključa: nezavisno
uključivanje malih slova i uklanjanja interpunkcije, bez kvačica, skraćenice
(uz pravila i probu) i maskiranje psovki. Radi i kad je AI isključen —
zato je odvojeno od AI kartice.

## Obrada teksta

Isto što radi i macOS verzija, sve se menja u aplikaciji:

| | podrazumevano | |
|---|---|---|
| Bez kvačica | **isključeno** | `č ć ž š đ → c c z s dj` |
| Skraćenice | uključeno | `ne znam → nzm`, `je li/jeli → je l`, `da li → da l`; lista je ugrađena i samo za čitanje |

Честе фразе су уграђене у build. Бројеви се претварају у цифре, а јединица се
раздваја ако се слепи са бројем:

```
„pet minuta"       → „5min"
„petmin"           → „5min"
„sto dvadeset i pet minuta" → „125min"
„pet dinara"       → „5 dinara"
```

Поставка **Скраћивање честих фраза** и даље може да се искључи; претварање
изговорених бројева остаје укључено и тада.

Правила за честе фразе нису корисничко подешавање на телефону:
приказују се само за читање, док се њихова листа мења у `Abbreviations.kt`
пре builda. Поље *Proba pravila* остаје доступно да провериш резултат без
диктирања.


U sekciji *Skraćenice* postoji polje **Proba** — upišeš rečenicu i odmah vidiš
šta pravila urade, bez diktiranja.

Isti spisak služi i kao **ispravljač**: ako prepoznavanje stalno greši istu reč,
dodaj `pogrešno=ispravno`. To je praktičniji od pravopisne provere, jer
prepoznavanje ne pravi slovne greške nego zamenjuje reč drugom ispravnom rečju —
a nju rečnik ne bi ni prijavio.

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

## Testovi

Pravila za tekst su čist string→string, pa se testiraju na JVM-u bez telefona:

```bash
cd android && ./gradlew test
```

Devet testova pokriva `<`, duplirana pravila, cele reči, hiljade, interpunkciju
i kvačice. Ovo je uhvatilo da `<` **radi** onda kad je izgledalo da ne radi —
problem je bio u sačuvanim pravilima na telefonu, ne u kodu.

## Izgled

Material 3 sa **dinamičkim bojama** — aplikacija preuzima paletu sa pozadine
telefona. Prati **tamni režim** sistema; ranije je bila prisilno svetla, što je
na tamnom telefonu bilo najuočljivije. Podešavanja su grupisana u kartice.

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
  OpenAiTranscription.kt završeni upload na OpenAI gpt-transcribe endpoint
  TextPolish.kt          mala slova, interpunkcija, kvačice
  Config.kt              podešavanja
build.sh                 napravi i instaliraj
```
