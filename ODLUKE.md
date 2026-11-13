# Odluke

## 2026-10-23, live prepis se ne odbacuje
- Odluka: tekst koji je live prikaz već pokazao upisuje se u polje i kada Gemini tok ne završi. Posle 8 sekundi od Stop-a veza se seče. Drugi dodir na „Završi” radi to odmah. Ako proces padne, sledeće otvaranje stavlja prepis u clipboard. Dugme „Ponovo pokreni aplikaciju” je na vrhu ekrana.
- Razlog: korisnik javlja da posle diktata brojač nastavi, a tekst sa prikaza ne uđe u polje.
- Izvor: čet 2cd8423d-3987-4a40-ad07-e46f24861f6c, 2026-10-23.
- Zamenjeno tumačenje 2026-10-24: korisnik je rekao da je zahtev bio za desktop. Android kod ostaje, ali nije bio tražen.

## 2026-10-24, isto važi za desktop
- Odluka: restart i čuvanje live prikaza idu u macOS aplikaciju `dictate/`. Stavka „Ponovo pokreni” je u meniju Diktat dok su Podešavanja otvorena. Na Stop se upisuje tekst koji je prikaz već pokazao. Sat u traci staje čim se pusti taster.
- Razlog: korisnik ne vidi restart jer je prethodna izmena otišla u mobilnu aplikaciju.
- Izvor: čet 2cd8423d-3987-4a40-ad07-e46f24861f6c, 2026-10-23.

## 2026-10-24, jezik je uvek sr-RS
- Odluka: desktop Diktat ne nudi izbor jezika. `config.JEZIK` je `sr-RS`, a Gemini Live setup šalje tačno taj jedan kod. Prazan spisak se ne šalje, jer po dokumentaciji (26.08.2026) prazno uključuje automatsko mešanje jezika.
- Razlog: korisnik čuje da prepis ode na engleski i srpski, ili na engleski i ruski, a u prozoru nema jezika.
- Granica: `languageCodes` je nagoveštaj. Istog dana ruski snimak ostaje ruski i uz `sr-RS`, i uz prazan spisak, i uz `systemInstruction`. `languageHints` server prihvati, ali ishod ne promeni. Web Speech sa `lang=sr-RS` ruski snimak vrati prazan, a srpski na latinici. Servis nije prebačen, jer to menja kvalitet i seče na pauzama.
- Izvor: čet e5a7631d-ae69-46f1-b476-4d0e0e1ef3cf, 2026-10-24.

## 2026-10-28, istorija i rezerva pre lepljenja na Mac-u
- Odluka: svaki prepis se trajno čuva pre prikaza; Stop odmah čuva i kopira ceo diktat pre skrivanja okvira.
- Nezavisan JSONL dnevnik čuva sve verzije i obnavlja istoriju posle pada ili oštećenja glavnog fajla. Rezerve teksta se ne brišu automatski.
- Stanje prepisa pripada recorder-u sesije; završetak starog diktata ne briše stanje novog.
- Razlog: korisnik gubi već prikazan tekst pri stopiranju diktata od minut ili dva i traži istoriju pre lepljenja i dodatnu rezervu.
- Izvor: čet 9b0fb1ff-fa79-4e27-8bf8-bd4c7703136d, zahtev 28.10.2026. u 13:39 UTC; putanja projekta ispravljena u 13:45 UTC.
- Opseg Mac dela je izveden iz postojeće instalacije i ranijih odluka projekta; dodatno pitanje Mac/Android poslato je korisniku.

## 2026-10-28, način upisa u Agent Deskov WKWebView
- Odluka: Diktat za aktivni bundle local.agent-desk.launcher koristi standardno lepljenje u auto režimu i za potvrđene live delove.
- Privremeni AX prepis u Agent Deskovom polju je isključen; prepis ostaje u okviru i trajnoj istoriji. Kursor se ne šalje Cmd+Down na kraj polja.
- Razlog: korisnik u 16:03 UTC prijavljuje da diktiranje ne radi unutar Agent Deska. Kompatibilnost lepljenja je implementacioni izbor; konkretan unos kroz UI nije potvrđen zbog timeout-a alata.
- Zatečena instalacija bila je starija od projekta i bez prethodne zaštite istorije; uzrok zamene nije utvrđen. Postavlja se aktuelni kod i proširuje njegov boot otisak.
- Izvor: čet 9b0fb1ff-fa79-4e27-8bf8-bd4c7703136d, 2026-10-28T16:03:15.755Z.

### Dopuna 28.10.2026, potvrđeno prepisivanje ažuriranjem
- Dnevnik pri ponovnoj instalaciji pokazuje: učitan novi lokalni kod, zatim „azurirano na v1.76“ i ponovno pokretanje starijih modula bez istorija.py.
- Lokalna instalacija iz radnog foldera sa izmenjenim kodom dobija oznaku LOKALNA-POPRAVKA. Updater ne sme prepisati tu kopiju izdanjem; dugme to prikazuje, a ažuriranje ide kroz make_app.sh kod.
- Ova potvrda zamenjuje prethodnu neizvesnost o razlogu vraćanja starog koda.

### Dopuna 28.10.2026, lažni poziv na ažuriranje
- Dok postoji LOKALNA-POPRAVKA, strelica u traci i tekst „Dostupna je nova verzija“ se ne prikazuju. Dugme ostaje „Lokalna popravka“ i ne preuzima izdanje.
- Razlog: instalirana oznaka je v1.74, GitHub ima v1.76, pa je strelica i dalje zvala na ažuriranje koje zaštita odbija. Korisnik je to prijavio 2026-10-28T22:32:30Z.
- Izvor: čet 9b0fb1ff-fa79-4e27-8bf8-bd4c7703136d.
- Zamenjeno 2026-10-28T22:37:37Z: korisnik je rekao da preuzimanje mora da prođe. Dugme preuzima izdanje. Lokalni `dictate/` se vrati preko arhive, a oznaka verzije postane oznaka izdanja.

## 2026-10-29, clipboard je izbor nezavisan od istorije
- Odluka: automatski unos se pokušava i kada Accessibility ne može da pročita polje. Nepostojanje AX sadržaja ne preusmerava diktat samo u clipboard.
- Odluka: prekidač „Čuvaj diktat i u clipboard-u“ je početno isključen. Istorija i rezervne kopije ostaju automatske; sistemsko lepljenje privremeno koristi clipboard i vraća prethodni sadržaj.
- Razlog: korisnik često mora ručno da nalepi prepis i traži automatski unos uz izbor da li da ostane kopija u clipboard-u.
- Granica: nema slepog ponavljanja unosa bez potvrde, zbog mogućeg dupliranja. Stvarni unos kroz UI još nije potvrđen, alat vraća timeout.
- Zamenjuje ranije obavezno kopiranje pri Stop-u i kopiranje neuspelog unosa kada je novi prekidač isključen.
- Izvor: čet 1a9ba27d-b069-44bd-9849-bcd1a0cc57b5, korisnik 2026-10-29T12:37:22.447Z.

## 2026-10-31, istorija do 100 prepiski
- Odluka: Mac i Android čuvaju do 100 prepiski. U podešavanjima se vide pet redova sa rednim brojem, starije se skroluju nadole. Nema posebnog dugmeta za otvaranje liste. Broj 1 je najnoviji.
- Razlog: korisnik traži dužu istoriju od pet, skrol umesto dugmeta, i iste brojeve na telefonu i računaru.
- Izvor: čet 8489ff51-c480-4ee0-9396-fa87ddab0e52, 31.10.2026. u 23:06 UTC.


## 2026-11-04, kompaktan engleski desktop meni
- Korisnik traži isti princip kao Touchpad Switcher: jedna kolona, bez objašnjenja i jedan kontrolni taster za prečicu miša. Esc tokom njenog snimanja briše prethodni izbor.
- Gemini Live je početni izbor, uz zadržavanje Google Speech-to-Text. Oba imaju neprekidno snimanje, toggle i automatski prekid na 10 minuta; Gemini prepis uživo ne može da se isključi.
- Tražene opcije za AI obradu, OpenAI/Groq, zvuk i medije, clipboard, dijagnostiku i rezervni audio uklonjene su iz aktivnog macOS menija i ugašene kroz migraciju konfiguracije. Postojeći audio fajlovi nisu brisani.
- Ova odluka zamenjuje prethodne macOS izbore kratkog Live limita, izbora aktivacije i navedenih opcionih funkcija. Android nije deo ove izmene.
- Izvor: korisnička poruka 2026-11-04T00:17:39.077Z, čet ae5ffb6a-4dfa-45f5-8291-3212e0e1972b.


## 2026-11-04, nezavisna pravila i oznaka provere ključa
- Korisnik traži uklanjanje izbora § i `: § ostaje stalno uključen, ` isključen. Prikaz ukupno snimljenog vremena uklonjen je sa dna.
- Lokalna pravila se podešavaju pojedinačno; zajednički prekidač je uklonjen. Punctuation je on/off za svu interpunkciju ili njeno uklanjanje; raniji režim samo zareza i upitnika više nije dostupan.
- Gemini ključ ima malo dugme uz unos sa stanjem provere, zelenom štiklicom za uspeh i crvenim znakom za neuspeh; provera ide pri otvaranju, završetku izmene i kliku. Nema modalnog izveštaja. Provera pristupa ne potvrđuje kvotu ni audio transkripciju.
- Snimljena prečica miša uvek ima prefiks Mouse: da se zna na šta se odnosi.
- Izvor: korisnička poruka 2026-11-04T00:30:57.142Z, čet ae5ffb6a-4dfa-45f5-8291-3212e0e1972b. Dopunjuje raniju odluku o kompaktnom meniju.


## 2026-11-04, meni bez naslova grupa i polja
- Korisnik traži uklanjanje svih naslova nad kontrolama, uključujući Microphone, Service, Gemini API key, History i Local rules. Ostaje jedna kolona; uklonjeni su dodatni razmaci grupa, a razmak kontrola je 4 px.
- Pristupačni nazivi polja ostaju za čitače ekrana, bez prikazivanja naslova u meniju.
- Izvor: čet ae5ffb6a-4dfa-45f5-8291-3212e0e1972b, poruka 2026-11-04T00:35:42.870Z.


## 2026-11-04, meni bez prekidanja diktata i raspored istorije
- Klik na oznaku aplikacije otvara/sklanja podešavanja čak i tokom pokretanja ili aktivnog snimanja. Više ne poziva Stop. Ponovno pokretanje aplikacije zadržava zaustavljanje stare instance.
- Checkboxovi su prebačeni na vrh. Istorija se skroluje bez vidljivog klizača, sa 10 px unutrašnjeg razmaka.
- Razlog i izvor: korisnik traži da ulazak u meni ne prekida audio i traži uredniji raspored, čet ae5ffb6a-4dfa-45f5-8291-3212e0e1972b, 2026-11-04T00:39:39.742Z.


## 2026-11-04, uklonjen menu bar i brojač snimanja
- Korisnik traži uklanjanje brojača trajanja i cele statusne stavke iz menu bara. Pilula sa vremenom je ugašena; žuto upozorenje posle sedmog minuta nije dodato. Limit od 600 s ostaje za oba servisa.
- Podešavanja se zato otvaraju pri pokretanju aplikacije. Ovo zamenjuje ranije odluke o otvaranju kroz statusnu stavku, ne menja zaustavljanje stare instance pri ponovnom pokretanju.
- Dugme za prečicu miša ima levo poravnat natpis.
- Svaka instalacija kroz make_app.sh bira postojeći Gemini Live i čuva njegov ključ. Model nije proizvoljno preimenovan u 3.0: projekat koristi Gemini 3.5 Transcribe Live.
- Izvor: čet ae5ffb6a-4dfa-45f5-8291-3212e0e1972b, korisnik 2026-11-04T00:45:19.937Z.


## 2026-11-04, levo poravnanje, redosled i automatsko ažuriranje
- Istorija i dugme miša drže levu ivicu natpisa i kad je tekst kratak. Samo `setAlignment` nije dovoljno: `setTitle` na NSButton-u i dalje crta natpis po sredini. Dugme miša stoji iznad mikrofona.
- Meni pokazuje samo `Version`. Nema dugmeta za proveru ni instalaciju. Novo GitHub izdanje se preuzima samo kada nema snimanja ni teksta koji čeka upis. Ovo dopunjuje odluku o uklonjenom menu baru.
- Android ekran prati isti skup: engleski, bez naslova grupa, Gemini Live ili Google, nezavisna pravila, Punctuation kao sve ili ništa, istorija levo, limit 600 s, samo verzija i automatsko preuzimanje. Sistem i dalje traži potvrdu instalacije APK-a.
- Izvor: čet ae5ffb6a-4dfa-45f5-8291-3212e0e1972b, korisnik 2026-11-04T00:48:23.472Z. Nastavak posle prekida: 2026-11-04T01:01:33.369Z.


## 2026-11-04, prozor ostaje, dugme miša i bez verzije
- Klik u drugu aplikaciju više ne zatvara podešavanja. Zatvaraju ih Esc i dugme X. Ovo zamenjuje ranije zatvaranje pri gubitku fokusa.
- Kontrola prečice miša je dugme sa okvirom. Natpis ostaje unutra i levo. Raniji izgled bez okvira je uklonjen.
- Natpis verzije je uklonjen na macOS-u i na Androidu. Automatsko preuzimanje ostaje, i dalje čeka kraj snimanja i upisa. Ovo zamenjuje odluku da meni pokazuje samo `Version`.
- Izvor: čet ae5ffb6a-4dfa-45f5-8291-3212e0e1972b, korisnik 2026-11-04T01:11:02.782Z.


## 2026-11-04, uži prozor i dugmad na dnu
- Korisnik traži uži prozor i da Record mouse button i Quit stoje jedno pored drugog na dnu. Ovo zamenjuje raniji redosled u kome je dugme miša stajalo iznad mikrofona.
- Kolona sadržaja je 248 px, prozor sa marginama 272 px. Nazivi servisa nisu skraćeni: Gemini 3.5 Transcribe Live i dalje staje u popup.
- Izvor: čet ae5ffb6a-4dfa-45f5-8291-3212e0e1972b, korisnik 2026-11-04T01:18:33.446Z.


## 2026-11-04, negativna opcija Remove punctuation
- Prekidač je promenjen iz „Punctuation” u „Remove punctuation” kako bi opcija bila negativna, usklađena sa „Remove diacritics” i internim parametrom `strip_punctuation`.
- Kada je prekidač uključen, interpunkcija se uklanja. Kada je isključen, interpunkcija ostaje.
- Primenjeno na macOS i Android ekrane podešavanja.
- Izvor: čet ae5ffb6a-4dfa-45f5-8291-3212e0e1972b, korisnik 2026-11-04T01:26:02.915Z.


## 2026-11-05, Google prepis u okviru, upis na Stop
- Korisnik traži da Google ne unosi tekst direktno u polje, nego da ga prikazuje u okviru kao Gemini 3.5 („Listening…”), a da ga nalepi tek pritiskom tastera za kraj.
- macOS: delovi sečeni na pauzi idu u okvir (samo neprekinut početak, bez rupa), na Stop se čekaju delovi u obradi i ceo tekst se upisuje. Zamenjuje odluku „Google bez okvira”. Android nije menjan.
- Izvor: čet 641bffc8-244c-4322-926e-631d7ebf8be4, korisnik 2026-11-05T02:09:03Z.

## 2026-11-13, okvir uživo bez tačke, stakleni
- Crvena tačka uklonjena na Macu i Androidu (uvlačila je tekst). Okvir je staklen: crn dok radi, žut sa tamnim tekstom kad prepis kasni. Zamenjuje odluku o crvenoj/narandžastoj tački iz četa 936a1d84.
- Izvor: čet 13f303fb-29d7-48a4-acfb-a19027ad71aa, korisnik 2026-11-13T18:19Z.
- Dopuna 2026-11-13T18:29Z: stakleni izgled zamenjen izgledom titla: centriran tekst, crna četvrtasta traka 75 % iza svakog reda, žuta kad prepis kasni. Razlog: korisniku staklo nije izgledalo kao staklo.

## 2026-11-13, kraći ekran na telefonu
- Uklonjeni proba diktata i prekidač „Remove punctuation” sa Android ekrana. Interpunkcija se na telefonu uvek uklanja. Ovo zamenjuje Android deo odluke o prekidaču „Remove punctuation”; Mac ostaje sa prekidačem.
- Izvor: čet 13f303fb-29d7-48a4-acfb-a19027ad71aa, korisnik 2026-11-13T18:38Z.

## 2026-11-13, ista podešavanja na Macu i telefonu
- Korisnik traži identična podešavanja na oba uređaja. Mac gubi prekidač „Remove punctuation”; interpunkcija se uvek uklanja (`strip_punctuation` uvek True pri učitavanju). Zamenjuje Mac deo odluke o prekidaču „Remove punctuation”. Start at login, mikrofon i dugme miša ostaju samo na Macu jer nemaju smisla na telefonu.
- Telefon: istorija od ivice do ivice kao spisak, svih do 100 u stranici; servis i polje ključa uokvireni.
- Izvor: čet 13f303fb-29d7-48a4-acfb-a19027ad71aa, korisnik 2026-11-13T18:43Z.
