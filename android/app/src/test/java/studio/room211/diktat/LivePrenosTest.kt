package studio.room211.diktat

import org.junit.Assert.assertEquals
import org.junit.Test

class LivePrenosTest {

    @Test
    fun prazanTokCuvaPrikaz() {
        val p = LivePrenos()
        p.vidi("danas je lep dan")
        assertEquals("danas je lep dan", p.ostatak(""))
    }

    @Test
    fun konacanTekstNadogradjujePrikaz() {
        val p = LivePrenos()
        p.vidi("danas je")
        assertEquals("danas je lep dan", p.ostatak("danas je lep dan"))
    }

    @Test
    fun kraciKonacanNeBriseDuziPrikaz() {
        val p = LivePrenos()
        p.vidi("danas je lep dan i sunce")
        assertEquals("danas je lep dan i sunce", p.ostatak("danas je lep"))
    }

    @Test
    fun potvrdjeniPrefiksSeNeUpisujePonovo() {
        val p = LivePrenos()
        p.vidi("danas je lep dan")
        p.potvrdi("danas je")
        assertEquals("lep dan", p.ostatak("danas je lep dan"))
    }

    @Test
    fun vecUpisanoSeNeDuplira() {
        val p = LivePrenos()
        p.vidi("danas je lep dan")
        p.potvrdi("danas je lep dan")
        assertEquals("", p.ostatak("danas je lep dan"))
    }

    @Test
    fun pukaoTokPosleDelimičnogUpisa() {
        val p = LivePrenos()
        p.vidi("prva rečenica druga rečenica")
        p.potvrdi("prva rečenica")
        assertEquals("druga rečenica", p.ostatak(""))
    }
}
