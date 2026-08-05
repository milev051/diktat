package studio.room211.diktat

import org.junit.Assert.assertEquals
import org.junit.Test

/** Emotikoni: hvatanje celih znakova i brisanje ponovljenih. */
class EmojiTest {

    @Test
    fun `zwj sekvenca je jedan znak`() {
        // "👨‍💼" su dve kodne tacke spojene ZWJ-om; ako se broje odvojeno,
        // istorija bi pamtila polovine i poredjenje ne bi radilo.
        assertEquals(listOf("👨‍💼"), Polish.emojiList("kolega 👨‍💼"))
    }

    @Test
    fun `varijantni selektor ostaje uz znak`() {
        assertEquals(listOf("☀️"), Polish.emojiList("sunce ☀️"))
    }

    @Test
    fun `ponovljeni emotikon se brise a prvi ostaje`() {
        val out = Polish.bezPonavljanja("a 🤝 b 🏢 c 🤝 d")
        assertEquals("a 🤝 b 🏢 c d", out)
    }

    @Test
    fun `podela na pasuse prezivljava brisanje`() {
        val out = Polish.bezPonavljanja("prvi 🤝\n\ndrugi 🤝 kraj")
        assertEquals("prvi 🤝\n\ndrugi kraj", out)
    }

    @Test
    fun `tekst bez emotikona ostaje isti`() {
        assertEquals("obican tekst", Polish.bezPonavljanja("obican tekst"))
    }
}
