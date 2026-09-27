package studio.room211.diktat

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Pravila za tekst su cist string->string, pa se testiraju na JVM-u, bez
 * telefona. Pokretanje: ./gradlew test
 */
class TextRulesTest {

    private fun rules(text: String) = Abbreviations.parse(text)
    private fun apply(text: String, rulesText: String) =
        Abbreviations.apply(text, rules(rulesText))

    @Test
    fun `znak manje lepi za prethodnu rec`() {
        assertEquals("imam 5000RSD", apply("imam 5000 dinara", "dinara=<RSD"))
        assertEquals("plati 20€", apply("plati 20 evra", "evra=<€"))
        assertEquals("traje 15min", apply("traje 15 minuta", "minuta=<min"))
    }

    @Test
    fun `bez znaka manje razmak ostaje`() {
        assertEquals("imam 5000 RSD", apply("imam 5000 dinara", "dinara=RSD"))
    }

    @Test
    fun `razmak posle znaka manje se ne racuna`() {
        assertEquals("imam 5000RSD", apply("imam 5000 dinara", "dinara=< RSD"))
    }

    @Test
    fun `ista fraza dvaput - poslednji red pobedjuje`() {
        assertEquals("imam 5000RSD", apply("imam 5000 dinara", "dinara=RSD\ndinara=<RSD"))
        assertEquals("imam 5000 RSD", apply("imam 5000 dinara", "dinara=<RSD\ndinara=RSD"))
    }

    @Test
    fun `podrazumevana pravila rade`() {
        // Sadrzaj liste je korisnikov izbor; ovde se proverava samo da se
        // primenjuje, ne koje su tacno skracenice.
        val d = Abbreviations.DEFAULT
        assertEquals("nzm koliko", Abbreviations.apply("ne znam koliko", d))
        assertEquals("jbm li ga stvarno", Abbreviations.apply("jebem li ga stvarno", d))
        // "da li" se NE skracuje: "da l" izgleda krnje. "je l" je ostalo.
        assertEquals("je l ovo je l da li", Abbreviations.apply("je li ovo jeli da li", d))
        // Prepoznavanje "svejedno" vraca i rastavljeno, pa oba oblika rade.
        assertEquals("svj mi je", Abbreviations.apply("svejedno mi je", d))
        assertEquals("svj mi je", Abbreviations.apply("sve jedno mi je", d))
        assertEquals("traje 15min", Abbreviations.apply("traje 15 minuta", d))
        // Cela rec se NE lepi uz cifru: "100dolara" izgleda kao greska.
        assertEquals("kosta 100 dolara", Abbreviations.apply("kosta 100 dolara", d))
        assertEquals("kosta 500 dinara", Abbreviations.apply("kosta 500 dinara", d))
        assertEquals("placa 20 evra", Abbreviations.apply("placa 20 evra", d))
        assertEquals("stigao za 3 sata", Abbreviations.apply("stigao za 3 sata", d))
        // Kratka oznaka se i dalje lepi, trocifrena oznaka valute ne.
        assertEquals("ceka 30min", Abbreviations.apply("ceka 30 min", d))
        assertEquals("presao 20km", Abbreviations.apply("presao 20 km", d))
        assertEquals("tezi 10kg", Abbreviations.apply("tezi 10 kg", d))
        assertEquals("placa 20 eur", Abbreviations.apply("placa 20 eur", d))
    }

    @Test
    fun tekstualniBrojeviOstajuTekstualniAJediniceSeSredjuju() {
        val d = Abbreviations.DEFAULT
        assertEquals("pet min", Abbreviations.apply("pet minuta", d))
        assertEquals("pet min", Abbreviations.apply("petmin", d))
        assertEquals("dvadeset pet sati", Abbreviations.apply("dvadeset pet sati", d))
        assertEquals("pet dinara", Abbreviations.apply("pet dinara", d))
        assertEquals("sto dvadeset i pet min", Abbreviations.apply("sto dvadeset i pet minuta", d))
        assertEquals("dve hiljade trista dinara", Abbreviations.apply("dve hiljade trista dinara", d))
        assertEquals("zato što je kasno", Abbreviations.apply("zato sto je kasno", d))
        assertEquals("sto dinara", Abbreviations.apply("sto dinara", d))
        assertEquals("pet min", Abbreviations.apply("pet minuta", emptyList()))
        assertEquals(
            "pet min pet min 5min",
            Abbreviations.apply("pet minuta petmin 5min", d),
        )
    }

    @Test
    fun `svi oblici minuta postaju min`() {
        assertEquals(
            "1min 2min 3min",
            Abbreviations.apply("1 minut 2 minute 3 minuta", Abbreviations.DEFAULT),
        )
        assertEquals("jedan min dve min tri min", Abbreviations.apply("jedan minut dve minute tri minuta", Abbreviations.DEFAULT))
    }

    @Test
    fun `poklapaju se samo cele reci`() {
        val d = Abbreviations.DEFAULT
        assertEquals("znamenito ostaje", Abbreviations.apply("znamenito ostaje", d))
        assertEquals("prominuta ostaje", Abbreviations.apply("prominuta ostaje", d))
    }

    @Test
    fun `tacka u hiljadama se brise a decimalna ostaje`() {
        assertEquals("5000", TextPolish.joinThousands("5.000"))
        assertEquals("1500000", TextPolish.joinThousands("1.500.000"))
        assertEquals("1500,25", TextPolish.joinThousands("1.500,25"))
        assertEquals("verzija 2.0", TextPolish.joinThousands("verzija 2.0"))
        assertEquals("android 4.4", TextPolish.joinThousands("android 4.4"))
    }

    @Test
    fun `interpunkcija ne kvari brojeve`() {
        assertEquals("Cena je 1.500,25 dinara",
            TextPolish.stripPunctuation("Cena je 1.500,25 dinara."))
        assertEquals("Danas je lep dan zar ne",
            TextPolish.stripPunctuation("Danas je lep dan, zar ne?"))
        // Crtica koja SPAJA dve reci prezivljava; sama nestaje.
        assertEquals("crno-beli film bez crtice",
            TextPolish.stripPunctuation("crno-beli film — bez crtice"))
        assertEquals("srpsko-hrvatski i e-mail",
            TextPolish.stripPunctuation("srpsko-hrvatski i e-mail"))
        assertEquals("ovo ono", TextPolish.stripPunctuation("ovo - ono"))
    }

    @Test
    fun `opcija samo zarezi cuva zareze a uklanja ostale znake`() {
        assertEquals(
            "danas je lep dan, zar ne",
            TextPolish.stripPunctuation("danas je lep dan, zar ne?", keepCommas = true),
        )
        assertEquals(
            "sastanak je u 10:30, ponesi verziju 2.0",
            TextPolish.stripPunctuation(
                "sastanak je u 10:30, ponesi verziju 2.0.",
                keepCommas = true,
            ),
        )
    }

    @Test
    fun `opcija samo zarezi ne ostavlja zarez uz veznik i`() {
        assertEquals(
            "uzeo sam hleb i mleko, pa sam otišao",
            TextPolish.stripPunctuation(
                "uzeo sam hleb, i mleko, pa sam otišao.",
                keepCommas = true,
            ),
        )
        assertEquals(
            "želim ovo i ono",
            TextPolish.stripPunctuation("želim ovo i, ono,", keepCommas = true),
        )
    }

    @Test
    fun `dvotacka u satnici ostaje`() {
        assertEquals("sastanak u 10:00 h",
            TextPolish.stripPunctuation("sastanak u 10:00 h"))
        assertEquals("tajmer 01:02:03", TextPolish.stripPunctuation("tajmer 01:02:03"))
        assertEquals("odnos je 2:1", TextPolish.stripPunctuation("odnos je 2:1"))
        assertEquals("Rekao je zdravo", TextPolish.stripPunctuation("Rekao je: zdravo!"))
        assertEquals("napomena ovako", TextPolish.stripPunctuation("napomena : ovako"))
    }

    @Test
    fun `apostrof ostaje a navodnici odlaze`() {
        // Apostrof je deo reci („je l'", „ć'š"); isto kao Apostrof u tests/test_text.py.
        assertEquals("je l' tako", TextPolish.stripPunctuation("je l' tako?"))
        assertEquals("je l\u2019 tako", TextPolish.stripPunctuation("je l\u2019 tako"))
        assertEquals("'ajde idemo", TextPolish.stripPunctuation("'ajde idemo"))
        assertEquals("rekao ovako", TextPolish.stripPunctuation("rekao \u2018ovako\u2019"))
        assertEquals("rekao ovako sad", TextPolish.stripPunctuation("rekao 'ovako' sad"))
        assertEquals("ovo ono", TextPolish.stripPunctuation("ovo ' ono"))
        assertEquals("Je l' tako, Ć'š doći?", TextPolish.samoZarezi("Je l' tako. Ć'š doći?"))
    }

    @Test
    fun `kvacice`() {
        assertEquals("Cacak zuti djak", TextPolish.toAscii("Čačak žuti đak"))
    }
}

class PauseDetectorTest {

    private fun run(plan: List<Pair<Double, Double>>, pause: Double = 0.7): List<Double> {
        val d = PauseDetector(pauseSeconds = pause)
        val hits = mutableListOf<Double>()
        var t = 0.0
        for ((level, seconds) in plan) {
            repeat((seconds / 0.1).toInt()) {
                t += 0.1
                if (d.feed(level, 0.1)) {
                    hits.add(Math.round(t * 10) / 10.0)
                    d.reset()
                }
            }
        }
        return hits
    }

    private val tiho = 0.012
    private val bucno = 0.075
    private val govor = 0.45

    @Test
    fun `tiha soba - jedna pauza`() {
        assertEquals(listOf(4.7), run(listOf(tiho to 1.0, govor to 3.0, tiho to 1.0, govor to 2.0)))
    }

    @Test
    fun `bucna soba - pozadina se ne broji kao govor`() {
        assertEquals(listOf(4.7), run(listOf(bucno to 1.0, govor to 3.0, bucno to 1.0, govor to 2.0)))
    }

    @Test
    fun `snimanje pocinje usred govora`() {
        assertEquals(
            listOf(2.2, 4.7),
            run(listOf(govor to 1.5, tiho to 1.0, govor to 1.5, tiho to 1.0, govor to 1.0)),
        )
    }

    @Test
    fun `kratki predasi izmedju reci ne seku`() {
        val plan = mutableListOf(tiho to 1.0)
        repeat(6) { plan.add(govor to 0.8); plan.add(tiho to 0.3) }
        assertEquals(emptyList<Double>(), run(plan))
    }

    @Test
    fun `neprekidan govor ne sece`() {
        assertEquals(emptyList<Double>(), run(listOf(tiho to 1.0, govor to 10.0)))
    }

    @Test
    fun `duga tisina ne okida u nedogled`() {
        assertEquals(
            listOf(3.7, 8.2),
            run(listOf(tiho to 1.0, govor to 2.0, tiho to 2.5, govor to 2.0, tiho to 1.0)),
        )
    }

    @Test
    fun `sama tisina bez govora ne sece`() {
        assertEquals(emptyList<Double>(), run(listOf(tiho to 5.0)))
    }
}

/**
 * Veliko slovo posle tacke. Prevod `webstt.capitalize_sentences` iz macOS
 * verzije; slucajevi su isti kao u tests/test_text.py, da se dve platforme ne
 * raziđu.
 */
class VelikoSlovoTest {

    private fun sredi(text: String) = TextPolish.capitalizeSentences(text)

    @Test
    fun `malo slovo posle tacke se podize`() {
        assertEquals("Okej. Sto se tice toga.", sredi("Okej. sto se tice toga."))
    }

    @Test
    fun `slepljena recenica dobija razmak`() {
        assertEquals("prethodnu. Cetvrta recenica", sredi("prethodnu.Cetvrta recenica"))
    }

    @Test
    fun `upitnik i uzvicnik`() {
        assertEquals("Sta je ovo? Ne znam! Probaj", sredi("Sta je ovo?ne znam!probaj"))
    }

    @Test
    fun `godina i redni broj ostaju malim slovom`() {
        assertEquals("Bilo je 2026. godine u julu.", sredi("Bilo je 2026. godine u julu."))
        assertEquals("Zauzeo je 5. mesto danas.", sredi("Zauzeo je 5. mesto danas."))
    }

    @Test
    fun `skracenica i inicijal ostaju malim slovom`() {
        assertEquals("Koristi npr. ovaj pristup.", sredi("Koristi npr. ovaj pristup."))
        assertEquals("Jabuke, kruske itd. sve je tu.", sredi("Jabuke, kruske itd. sve je tu."))
        assertEquals("Potpisao je M. petrovic juce.", sredi("Potpisao je M. petrovic juce."))
    }

    @Test
    fun `ime fajla i domen ostaju celi`() {
        assertEquals("Otvori config.json pa nastavi.", sredi("Otvori config.json pa nastavi."))
        assertEquals("Idi na google.com i vidi.", sredi("Idi na google.com i vidi."))
    }

    @Test
    fun `decimala i hiljade se ne diraju`() {
        assertEquals("Verzija 3.5 kosta 5.000 dinara.", sredi("Verzija 3.5 kosta 5.000 dinara."))
    }

    @Test
    fun `prvo slovo komada se ne dira`() {
        // Diktat se secka na pauzama; sledeci komad ume da bude nastavak
        // recenice, pa bi veliko slovo tu bilo greska.
        assertEquals("nastavak iste recenice", sredi("nastavak iste recenice"))
    }

    @Test
    fun `kvacice se podizu`() {
        assertEquals("Gotovo je. Često se desi.", sredi("Gotovo je. često se desi."))
    }

    @Test
    fun `novi red prezivljava`() {
        assertEquals("Prva.\ndruga tacka", sredi("Prva.\ndruga tacka"))
    }

    @Test
    fun `prazan tekst`() {
        assertEquals("", sredi(""))
    }
}


/**
 * Stil „izgovoreno" brise interpunkciju, pa znak izmedju dve reci ne sme prosto
 * da nestane. Isti slucajevi kao u tests/test_text.py.
 */
class SlepljeneReciTest {

    private fun sredi(text: String) = TextPolish.stripPunctuation(text)

    @Test
    fun `tacka izmedju reci postaje razmak`() {
        assertEquals("gotovo je sada nastavljam", sredi("gotovo je.sada nastavljam"))
        assertEquals("prethodnu Cetvrta recenica", sredi("prethodnu.Cetvrta recenica"))
    }

    @Test
    fun `upitnik uzvicnik zarez dvotacka`() {
        assertEquals("sta je ovo ne znam", sredi("sta je ovo?ne znam"))
        assertEquals("ne moze probaj", sredi("ne moze!probaj"))
        assertEquals("prvo drugo", sredi("prvo,drugo"))
        assertEquals("evo ovako", sredi("evo:ovako"))
    }

    @Test
    fun `brojevi se ne diraju`() {
        assertEquals("cena je 3,5 dinara", sredi("cena je 3,5 dinara"))
        assertEquals("u 10:30 krecem", sredi("u 10:30 krecem"))
        assertEquals("Cena je 1.500,25 dinara", sredi("Cena je 1.500,25 dinara."))
    }

    @Test
    fun `apostrof ostaje u reci`() {
        assertEquals("ć'š ti", sredi("ć'š ti"))
    }

    @Test
    fun `uz zadrzane zareze slepljen zarez dobija razmak posle sebe`() {
        assertEquals("prvo, drugo", TextPolish.stripPunctuation("prvo,drugo", keepCommas = true))
    }
}


/**
 * Endpoint vrati „20%" za izgovoreno „dvadeset procenata"; brisanje `%` je
 * pojelo jedini trag jedinice, a model to ne moze da vrati.
 */
class ProcenatTest {

    @Test
    fun `procenat i valutni znaci ostaju`() {
        assertEquals("popusti je 20%", TextPolish.stripPunctuation("popusti je 20%."))
        assertEquals("kosta 100$ i 20\u20AC", TextPolish.stripPunctuation("kosta 100$ i 20\u20AC"))
    }

    @Test
    fun `procenat ostaje i uz zadrzane zareze`() {
        assertEquals(
            "popust je 20%, kaze",
            TextPolish.stripPunctuation("popust je 20%, kaze", keepCommas = true),
        )
    }

    @Test
    fun `ostali simboli se i dalje brisu`() {
        assertEquals("ovo je test jos", TextPolish.stripPunctuation("ovo je #test & jos"))
    }
}


/**
 * „jednom" je „jedno" + „m" po spisku brojeva i jedinica, pa se lomilo u
 * „jedno m". Isti slucajevi kao u tests/test_text.py.
 */
class ObicneReciTest {

    private fun primeni(text: String) = Abbreviations.apply(text, emptyList())

    @Test
    fun `jednom ostaje celo`() {
        assertEquals("uradio sam to jednom", primeni("uradio sam to jednom"))
        assertEquals("u jednom trenutku", primeni("u jednom trenutku"))
    }

    @Test
    fun `ostale reci sa jednoslovnom oznakom`() {
        for (rec in listOf("stos", "stom", "trim", "dvas", "deseth")) {
            assertEquals("ovo je $rec ovde", primeni("ovo je $rec ovde"))
        }
    }

    @Test
    fun `razdvajanje uz duzu jedinicu ostaje`() {
        assertEquals("pet min", primeni("petminuta"))
        assertEquals("sto dinara", primeni("stodinara"))
        assertEquals("tri metara", primeni("trimetara"))
        assertEquals("pet sati", primeni("petsati"))
    }

    @Test
    fun `cifra uz jednoslovnu oznaku i dalje radi`() {
        assertEquals("traje 3h", primeni("traje 3 h"))
        assertEquals("dugacko 5m", primeni("dugacko 5 m"))
    }
}

/**
 * Tacke postaju zarezi, ostaju samo zarezi i upitnici. Isti slucajevi kao
 * `SamoZareziIUpitnici` u tests/test_text.py na Mac strani.
 */
class SamoZareziTest {

    private fun z(tekst: String) = TextPolish.samoZarezi(tekst)

    @Test
    fun `tacka usred postaje zarez na kraju nestaje`() {
        assertEquals(
            "Sutra idem u grad, Da li dolaziš? Javi mi",
            z("Sutra idem u grad. Da li dolaziš? Javi mi."),
        )
    }

    @Test
    fun `upitnik ostaje i na kraju`() {
        assertEquals("Zar ne?", z("Zar ne?"))
        assertEquals("Stvarno? Ne verujem", z("Stvarno!? Ne verujem"))
    }

    @Test
    fun `uzvicnik tri tacke dvotacka postaju zarez`() {
        assertEquals("Bravo, Ne znam, Prvo, ovo, pa ono", z("Bravo! Ne znam... Prvo: ovo; pa ono."))
    }

    @Test
    fun `tacka koja nije kraj recenice ostaje`() {
        assertEquals("Rođen je 2026. godine, npr. ovako", z("Rođen je 2026. godine, npr. ovako."))
    }

    @Test
    fun `brojevi i domeni ostaju celi`() {
        assertEquals(
            "Cena je 3,5 u 10:30, Verzija 2.0 radi",
            z("Cena je 3,5 u 10:30. Verzija 2.0 radi."),
        )
        assertEquals("Otvori google.com sada", z("Otvori google.com sada"))
    }

    @Test
    fun `slepljeno se razdvaja`() {
        assertEquals("Idem, Sutra, ne znam", z("Idem.Sutra,ne znam"))
    }

    @Test
    fun `navodnici zagrade i crte nestaju`() {
        assertEquals("Rekao je idemo sutra ok", z("Rekao je \"idemo\" (sutra) - ok."))
    }

    @Test
    fun `bez udvojenih zareza i zareza na pocetku`() {
        assertEquals("Idemo, dalje", z(". Idemo, , dalje."))
    }
}

/** „novi red" i „novi pasus". Isti slucajevi kao GlasovneKomande u tests/test_text.py. */
class GlasovneKomandeTest {

    private fun k(tekst: String) = TextPolish.glasovneKomande(tekst)

    @Test
    fun `novi red i pasus`() {
        assertEquals("Sutra idem u grad\nkupim mleko", k("Sutra idem u grad novi red kupim mleko"))
        assertEquals("zdravo Marko\n\nJavi mi", k("zdravo Marko novi pasus Javi mi"))
    }

    @Test
    fun `zarez oko komande nestaje tacka i upitnik ostaju`() {
        assertEquals("grad\nkupi", k("grad, novi red, kupi"))
        assertEquals("grad.\nKupi", k("grad. Novi red. Kupi"))
        assertEquals("dolaziš?\njavi", k("dolaziš? novi red javi"))
    }

    @Test
    fun `komanda kao zaseban deo diktata`() {
        assertEquals("\n", k("novi red "))
    }

    @Test
    fun `slicne reci se ne diraju`() {
        assertEquals("imam novi redovni posao", k("imam novi redovni posao"))
        assertEquals("ovo je nov redosled", k("ovo je nov redosled"))
    }
}

/**
 * „Pravilno" je precica nad prekidacima pravila, ne jos jedno podesavanje.
 * Isti slucajevi kao u tests/test_text.py na Mac strani.
 */
class PravilnoTest {

    private val sveUkljuceno = Pravilno.Stanje(
        malaSlova = true, bezInterpunkcije = true,
        bezKvacica = true, skracenice = true,
    )

    @Test
    fun `sve ukljuceno nije pravilno`() {
        assertEquals(false, sveUkljuceno.pravilno)
    }

    @Test
    fun `sve iskljuceno jeste pravilno`() {
        assertEquals(true, Pravilno.SVE_UGASENO.pravilno)
    }

    @Test
    fun `jedan ukljucen vise nije pravilno`() {
        // Nad-prekidac se IZVODI iz prekidaca; rucno paljenje jednog ga mora
        // oboriti, inace bi prekidac u podesavanjima lagao.
        assertEquals(false, Pravilno.SVE_UGASENO.copy(malaSlova = true).pravilno)
        assertEquals(false, Pravilno.SVE_UGASENO.copy(bezInterpunkcije = true).pravilno)
        assertEquals(false, Pravilno.SVE_UGASENO.copy(bezKvacica = true).pravilno)
        assertEquals(false, Pravilno.SVE_UGASENO.copy(skracenice = true).pravilno)
        assertEquals(false, Pravilno.SVE_UGASENO.copy(samoZarezi = true).pravilno)
    }

    @Test
    fun `ukljucivanje pamti zatecen izbor`() {
        val zapamceno = Pravilno.priUkljucivanju(sveUkljuceno)
        assertEquals(sveUkljuceno, zapamceno)
    }

    @Test
    fun `ukljucivanje nad vec pravilnim ne pamti nista`() {
        // Pamti se samo pri PRELASKU; inace bi drugi poziv zapamtio vec ugasena
        // stanja i povratak ne bi vratio nista.
        assertEquals(null, Pravilno.priUkljucivanju(Pravilno.SVE_UGASENO))
    }

    @Test
    fun `gasenje vraca ono sto je bilo`() {
        // Ne podrazumevano: `bezKvacica` je podrazumevano iskljucen, pa bi
        // povratak na podrazumevano tiho ukinuo izbor onome ko ga drzi upaljenog.
        val bilo = Pravilno.Stanje(
            malaSlova = true, bezInterpunkcije = false,
            bezKvacica = true, skracenice = false,
        )
        assertEquals(bilo, Pravilno.priGasenju(bilo))
    }

    @Test
    fun `gasenje bez pamcenja vraca podrazumevano`() {
        val vraceno = Pravilno.priGasenju(null)
        assertEquals(Pravilno.PODRAZUMEVANO, vraceno)
        assertEquals(true, vraceno.malaSlova)
        assertEquals(true, vraceno.bezInterpunkcije)
        assertEquals(false, vraceno.bezKvacica)
        assertEquals(true, vraceno.skracenice)
    }

    @Test
    fun `pun krug ukljuci pa iskljuci vraca isto`() {
        val pocetno = Pravilno.Stanje(
            malaSlova = true, bezInterpunkcije = true,
            bezKvacica = true, skracenice = true,
        )
        val zapamceno = Pravilno.priUkljucivanju(pocetno)
        assertEquals(true, Pravilno.SVE_UGASENO.pravilno)
        assertEquals(pocetno, Pravilno.priGasenju(zapamceno))
    }
}

/**
 * Granica trajanja po izvoru. Isti slucajevi kao `_limit_seconds` u
 * tests/test_pipeline.py na Mac strani.
 */
class GranicaTest {

    private fun sekundi(provider: String, dugo: Boolean = true) = Granica.sekundi(
        provider = provider, dugoSnimanje = dugo,
        geminiLive = 120, openAi = 3600, neprekidno = 3600, kratko = 30,
    )

    @Test
    fun `gemini live staje posle dva minuta`() {
        // Jedini izvor koji salje zvuk DOK snimas (~2,5 MB/min): zaboravljen
        // mikrofon tu curi podatke sve vreme, a ne tek na kraju.
        assertEquals(120, sekundi("gemini_live"))
    }

    @Test
    fun `granica za live vazi i bez dugog snimanja`() {
        // Ne stiti od predugackog ZAHTEVA nego od zaboravljenog mikrofona, pa
        // ne sme da zavisi od tog prekidaca.
        assertEquals(120, sekundi("gemini_live", dugo = false))
    }

    @Test
    fun `ostali izvori zadrzavaju svoje granice`() {
        assertEquals(3600, sekundi("google"))
        assertEquals(3600, sekundi("openai"))
        assertEquals(30, sekundi("google", dugo = false))
        assertEquals(30, sekundi("openai", dugo = false))
    }

    @Test
    fun `podrazumevano je dva minuta`() {
        assertEquals(120, Granica.GEMINI_LIVE_PODRAZUMEVANO)
    }
}
