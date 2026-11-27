# Iteracije

## 2026-11-25 11:30 · okvir uživo
- **Citat korisnika:** „modifikuj diktat app da se ipak vidi pozadina umesto ovako tekstualnog prikaza, neka bude fiksna sirina ona teget kao sto je bilo na verziji 1.7“, pa posle snimka: „to odradi isto i za telefon mada moze biti cela crna pozadina ne mora ovako teget, i objavi na git“.
- **Razlog:** titl sa trakom po redu (1.87) izgledao je kao go tekst preko ekrana.
- **Urađeno:** 1.89 vraća karticu fiksne širine kao u 1.76 (Mac teget #1F2933). 1.90: telefon crna kartica 95 %.
- **Dokaz:** snimci u Agent Desk data/prilozi/59ba6773…/ (mac-okvir-1.89.png, telefon-okvir-1.90.png, približan render; pravi snimak sa telefona nije napravljen jer telefon nije na adb-u).
- **Status:** zadržano (zamenjuje titl iz 1.87).

## 2026-11-27 07:50 · okvir uživo, žuto, interpunkcija
- **Citat korisnika:** „da li mozes i na telefonu staviti onu teget pozadinu takodje ovo zuto se cesto pojavljuje cak i kada ne izgovaram nista malo duze vreme tako da nije uvek da se radi o cekanju vec uvek kada je tisina i to mi nije jasno ali nebitno sto se tice ovih booleana stavi boolean za interpunkcijske znake posto su sada uglavnom iskljuceni a na kompjuteru i na telefonu bi bilo dobro da mogu da selektujem da ih ukljucim ili iskljucim isto kao sto su ovi ostali“
- **Razlog:** teget lepši od crne; žuto u tišini zbunjuje; interpunkcija ponekad potrebna.
- **Urađeno:** telefon teget (zamenjuje crnu iz 1.90); novo pravilo kašnjenja na Macu i telefonu; prekidač „Punctuation” na oba.
- **Dokaz:** data/prilozi/59ba6773…/telefon-okvir-1.91.png (približan render po merama iz koda); testovi test_kasnjenje.py i KasnjenjeTest.kt. Snimak podešavanja nije napravljen: render prozora van ekrana je prazan, a prozor Diktata nije dostupan za snimanje.
- **Status:** zadržano.
