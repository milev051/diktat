package studio.room211.diktat

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class InputContentTest {
    @Test fun `natpis bez hint metapodataka i sa kursorom na nuli ne postaje prefiks`() {
        for (label in listOf("Poruka", "Message", "Napiši poruku", "Pretraga")) {
            assertFalse(InputContent.canAppend(label, null, 0, 0))
        }
    }
    @Test fun `nejasna selekcija ide kroz paste`() {
        assertFalse(InputContent.canAppend("Poruka", null, -1, -1))
        assertFalse(InputContent.canAppend("Poruka", null, -1, 0))
        assertFalse(InputContent.canAppend("Poruka", null, 0, 10))
    }
    @Test fun `kursor na pocetku stvarnog teksta takodje koristi paste`() {
        assertFalse(InputContent.canAppend("Moj postojeći tekst", null, 0, 0))
    }
    @Test fun `rec poruka se ne brise iz stvarnog teksta`() {
        assertTrue(InputContent.canAppend("Poruka", null, 6, 6))
        assertTrue(InputContent.canAppend("poruka koju sam diktirao", "Napiši poruku", 23, 23))
    }
    @Test fun `poklapanje teksta i natpisa ne prepisuje sadrzaj`() {
        assertFalse(InputContent.canAppend("Poruka", "Poruka", 0, 0))
        assertFalse(InputContent.canAppend("Poruka", "Poruka", 6, 6))
    }
    @Test fun `obicno polje sa stvarnim sadrzajem ostaje podrzano`() {
        assertTrue(InputContent.canAppend("postojeći tekst ", null, 15, 15))
        assertFalse(InputContent.canAppend("", null, 0, 0))
    }
}
