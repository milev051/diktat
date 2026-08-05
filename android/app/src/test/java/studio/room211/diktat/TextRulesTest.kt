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
        assertEquals("traje 15min", Abbreviations.apply("traje 15 minuta", d))
        assertEquals("kosta $100", Abbreviations.apply("kosta 100 dolara", d))
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
        assertEquals("crno-beli film bez crtice",
            TextPolish.stripPunctuation("crno-beli film — bez crtice"))
    }

    @Test
    fun `kvacice`() {
        assertEquals("Cacak zuti djak", TextPolish.toAscii("Čačak žuti đak"))
    }
}
