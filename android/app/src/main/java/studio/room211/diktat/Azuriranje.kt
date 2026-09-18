package studio.room211.diktat

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.core.content.FileProvider
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

/**
 * Azuriranje iz GitHub izdanja, bez prodavnice aplikacija.
 *
 * Aplikacija se ne objavljuje na Google Play-u, pa nema ko da javi da je
 * izasla nova verzija. Zato se poslednje izdanje cita direktno sa GitHub-a,
 * APK se preuzme u kes aplikacije, a instalaciju potvrdjuje korisnik, kao i
 * kod svakog drugog APK-a.
 */
object Azuriranje {
    private const val IZDANJA = "https://api.github.com/repos/milev051/diktat/releases/latest"
    private const val IME_FAJLA = "azuriranje.apk"

    data class Izdanje(val oznaka: String, val naslov: String, val adresaApk: String)

    fun trenutnaVerzija(context: Context): String =
        runCatching {
            context.packageManager.getPackageInfo(context.packageName, 0).versionName.orEmpty()
        }.getOrDefault("")

    fun poslednje(): Izdanje {
        val veza = URL(IZDANJA).openConnection() as HttpURLConnection
        val telo = try {
            veza.connectTimeout = 12_000
            veza.readTimeout = 20_000
            veza.setRequestProperty("Accept", "application/vnd.github+json")
            veza.setRequestProperty("User-Agent", "Diktat-Android")
            val kod = veza.responseCode
            if (kod !in 200..299) error("GitHub je vratio HTTP $kod")
            veza.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
        } finally {
            veza.disconnect()
        }
        return izOdgovora(telo)
    }

    internal fun izOdgovora(json: String): Izdanje {
        val koren = JSONObject(json)
        val oznaka = koren.optString("tag_name").trim()
        require(oznaka.isNotBlank()) { "Izdanje nema oznaku verzije" }
        val prilozi = koren.optJSONArray("assets")
        var adresa = ""
        if (prilozi != null) {
            for (i in 0 until prilozi.length()) {
                val prilog = prilozi.getJSONObject(i)
                if (prilog.optString("name").endsWith(".apk", ignoreCase = true)) {
                    adresa = prilog.optString("browser_download_url")
                    break
                }
            }
        }
        require(adresa.isNotBlank()) { "Izdanje $oznaka nema APK" }
        return Izdanje(
            oznaka = oznaka,
            naslov = koren.optString("name").ifBlank { oznaka },
            adresaApk = adresa,
        )
    }

    /** „1.9" je starije od „1.11", pa se poredi broj po broj, ne kao tekst. */
    internal fun novije(trenutna: String, izdanje: String): Boolean {
        val leva = brojevi(trenutna)
        val desna = brojevi(izdanje)
        for (i in 0 until maxOf(leva.size, desna.size)) {
            val a = leva.getOrElse(i) { 0 }
            val b = desna.getOrElse(i) { 0 }
            if (a != b) return b > a
        }
        return false
    }

    private fun brojevi(verzija: String): List<Int> = verzija.trim()
        .removePrefix("v")
        .removePrefix("V")
        .split('.', '-', '_')
        .mapNotNull { deo -> deo.takeWhile { it.isDigit() }.toIntOrNull() }

    fun preuzmi(context: Context, adresa: String, napredak: (Int) -> Unit): File {
        val veza = URL(adresa).openConnection() as HttpURLConnection
        try {
            veza.connectTimeout = 15_000
            veza.readTimeout = 60_000
            veza.instanceFollowRedirects = true
            veza.setRequestProperty("User-Agent", "Diktat-Android")
            val kod = veza.responseCode
            if (kod !in 200..299) error("Preuzimanje je vratilo HTTP $kod")
            val ukupno = veza.contentLength.toLong()
            val fajl = File(context.cacheDir, IME_FAJLA)
            veza.inputStream.use { ulaz ->
                fajl.outputStream().use { izlaz ->
                    val bafer = ByteArray(64 * 1024)
                    var preneto = 0L
                    while (true) {
                        val broj = ulaz.read(bafer)
                        if (broj < 0) break
                        izlaz.write(bafer, 0, broj)
                        preneto += broj
                        if (ukupno > 0) napredak(((preneto * 100) / ukupno).toInt())
                    }
                }
            }
            return fajl
        } finally {
            veza.disconnect()
        }
    }

    fun smeDaInstalira(context: Context): Boolean =
        context.packageManager.canRequestPackageInstalls()

    fun otvoriDozvolu(context: Context) {
        context.startActivity(
            Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES)
                .setData(Uri.parse("package:${context.packageName}"))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        )
    }

    fun instaliraj(context: Context, fajl: File) {
        val adresa = FileProvider.getUriForFile(context, "${context.packageName}.fajlovi", fajl)
        context.startActivity(
            Intent(Intent.ACTION_VIEW)
                .setDataAndType(adresa, "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        )
    }
}
