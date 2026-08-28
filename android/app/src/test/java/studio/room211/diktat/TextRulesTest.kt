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
        assertEquals("kosta 100dolara", Abbreviations.apply("kosta 100 dolara", d))
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
        assertEquals("crnobeli film bez crtice",
            TextPolish.stripPunctuation("crno-beli film — bez crtice"))
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
    fun `apostrof odlazi sa ostalim znacima`() {
        // Endpoint ga vraca u „je l'", „ć'š".
        assertEquals("je l tako", TextPolish.stripPunctuation("je l' tako"))
        assertEquals("je l tako", TextPolish.stripPunctuation("je l\u2019 tako"))
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
