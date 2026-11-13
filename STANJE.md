# Stanje
_2026-11-13_
- Android 1.87: titl dole, bez Stop dugmeta (APK Diktat-1.87.apk).
- Android 1.86: dugme sa verzijom i proverom ažuriranja na vrhu ekrana. APK u Agent Desk data/prilozi/13f303fb…/Diktat-1.86.apk. Ažuriranje ne radi dok se na GitHub ne objavi novije izdanje od v1.76.
- Android 1.85 i Mac: ista podešavanja (Lowercase, Remove diacritics, Abbreviations, servis, ključ). Mac više nema „Remove punctuation”, interpunkcija se uvek uklanja. Telefon: servis i ključ uokvireni, istorija do 100 od ivice do ivice. APK u Agent Desk data/prilozi/13f303fb…/Diktat-1.85.apk. GitHub izdanje i dalje v1.76.
- Android 1.84: bez probe diktata i prekidača interpunkcije (uvek bez). APK u Agent Desk data/prilozi/13f303fb…/Diktat-1.84.apk. GitHub izdanje je i dalje v1.76, zato provera ažuriranja na telefonu ne nalazi ništa; otvoreno: objava izdanja.
- Traka titla: isti luft gore i dole u svakom redu. Mac instaliran; APK 1.83 u Agent Desk data/prilozi/13f303fb…/Diktat-1.83.apk. Python 386/386, Android 114/114.
- Okvir uživo u izgledu titla (centriran, crna traka 75 % po redu, žuta kad kasni), poslednji red se više ne krije. Mac instaliran `kod`; APK 1.82 u Agent Desk data/prilozi/13f303fb…/Diktat-1.82.apk čeka instalaciju. Python 386/386, Android 114/114.
- Okvir za snimanje doteran (Mac kartica sa crvenom tačkom, narandžasta i brža kad prepis kasni, bez poruke; Android kartica tekst + mali Stop, bez brojača, i za Google). APK 1.80 u data/prilozi/936a1d84…/Diktat-1.80.apk, čeka instalaciju na telefon. Mac instaliran (`kod`).
- Google (macOS): delovi se više ne upisuju usput; prepis stoji u okviru „Listening…” kao kod Gemini i lepi se ceo na Stop. 385/385, instalirano `kod`. Android nije menjan.
- macOS Diktat: prozor 272 px, checkboxovi na vrhu. Dugme miša i Quit na dnu.
- „Remove punctuation” uveden umesto „Punctuation” (negativna logika: uključen = uklanja interpunkciju).
- Pravila nezavisna: Lowercase, Remove punctuation, Remove diacritics, Abbreviations, Start at login.
- Istorija do 100, pet redova, bez klizača, unutrašnji razmak 10 px, levi natpis.
- Nema menu bara, brojača ni oznake verzije. Meni ostaje otvoren do Esc ili X. Ažuriranje automatsko.
- Gemini 3.5 Transcribe Live početni (prepis uživo), Google sa istim okvirom. Toggle, 600 s (otvoreno: ukidanje limita, Gemini sesija ima granicu ~15 min).
- Android: isti prekidači uključujući „Remove punctuation”, APK 1.79 složen.
- Testovi: Python 383/383, Android unit testovi prolaze. Instalirano: `./make_app.sh kod`.
- Sledeći korak / otvoreno: živa provera diktiranja mikrofonom; Android instalacija APK-a na uređaj.
- Izvorni čet: ae5ffb6a-4dfa-45f5-8291-3212e0e1972b.



