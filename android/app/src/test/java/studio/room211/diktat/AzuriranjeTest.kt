package studio.room211.diktat

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Poredjenje verzija i citanje GitHub odgovora.
 *
 * Bez ovoga bi „1.9" ispalo novije od „1.11", jer je kao tekst vece.
 */
class AzuriranjeTest {

    @Test
    fun `veci broj je noviji, ne duzi tekst`() {
        assertTrue(Azuriranje.novije("1.9", "1.11"))
        assertFalse(Azuriranje.novije("1.11", "1.9"))
        assertTrue(Azuriranje.novije("1.63", "v1.64"))
        assertFalse(Azuriranje.novije("1.63", "v1.63"))
        assertFalse(Azuriranje.novije("1.63", "v1.62"))
    }

    @Test
    fun `krace i duze oznake se porede po delovima`() {
        assertTrue(Azuriranje.novije("1.63", "1.63.1"))
        assertFalse(Azuriranje.novije("1.63.1", "1.63"))
        assertFalse(Azuriranje.novije("1.63.0", "1.63"))
    }

    @Test
    fun `iz odgovora se uzima APK prilog`() {
        val json = """
            {
              "tag_name": "v1.64",
              "name": "Diktat 1.64",
              "assets": [
                {"name": "izvor.zip", "browser_download_url": "https://x/izvor.zip"},
                {"name": "app-release.apk", "browser_download_url": "https://x/app-release.apk"}
              ]
            }
        """.trimIndent()
        val izdanje = Azuriranje.izOdgovora(json)
        assertEquals("v1.64", izdanje.oznaka)
        assertEquals("Diktat 1.64", izdanje.naslov)
        assertEquals("https://x/app-release.apk", izdanje.adresaApk)
    }

    @Test
    fun `izdanje bez APK-a je greska, ne tiho prazan URL`() {
        val json = """{"tag_name": "v1.64", "assets": []}"""
        val greska = runCatching { Azuriranje.izOdgovora(json) }.exceptionOrNull()
        assertTrue(greska is IllegalArgumentException)
    }
}
