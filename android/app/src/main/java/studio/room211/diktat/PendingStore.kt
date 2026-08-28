package studio.room211.diktat

import android.content.Context
import java.io.File

/**
 * Snimci koje prepoznavanje nije primilo.
 *
 * Endpoint je nedokumentovan i moze da zakaze bez najave. Kad se to desi,
 * izgovoreno ne sme prosto da nestane — snimak ostaje na disku i moze da se
 * posalje ponovo iz aplikacije.
 */
class PendingStore(
    context: Context,
    private val sampleRate: Int = 16_000,
) {

    private val dir = File(context.filesDir, "neuspeli").apply { mkdirs() }

    companion object {
        private const val KEEP = 3   // koliko poslednjih drzimo
    }

    init {
        // I ranije sačuvani folderi odmah poštuju novi limit.
        trim()
    }

    /**
     * Sačuvaj i provajdera koji je prvobitno pokušao obradu.
     *
     * Bez ovoga je ponovni pokušaj koristio trenutno izabrani provajder. To je
     * bilo zbunjujuće kada je snimak napravljen preko OpenAI-ja, a korisnik je
     * kasnije prebacio aplikaciju na Google.
     */
    fun save(pcm: ByteArray, provider: String = ""): File? {
        if (pcm.isEmpty()) return null
        // WAV može direktno da se presluša ili konvertuje, a load() i dalje
        // razume stare .pcm fajlove iz prethodnih verzija.
        val file = File(dir, "${System.currentTimeMillis()}-${System.nanoTime()}.wav")
        return runCatching {
            file.writeBytes(OpenAiTranscription.wav(pcm, sampleRate))
            if (provider.isNotBlank()) metadataFile(file).writeText(provider.trim())
            trim()
            file
        }.getOrNull()
    }

    fun list(): List<File> =
        dir.listFiles()
            ?.filter { it.name.endsWith(".pcm") || it.name.endsWith(".wav") }
            ?.sortedBy { it.lastModified() }
            ?: emptyList()

    /** Provajder kojim je snimak prvobitno pokušao obradu; stari fajlovi nemaju zapis. */
    fun provider(file: File): String? = runCatching {
        metadataFile(file).takeIf { it.isFile }?.readText()?.trim()?.ifBlank { null }
    }.getOrNull()

    /** Učitaj PCM, bilo da je fajl novi WAV ili stari sirovi PCM. */
    fun load(file: File): ByteArray {
        val bytes = file.readBytes()
        return pcmFrom(bytes)
    }

    fun find(name: String): File? =
        list().firstOrNull { it.name == name }

    fun remove(file: File) {
        file.delete()
        metadataFile(file).delete()
    }

    fun count(): Int = list().size

    fun seconds(file: File): Double =
        load(file).size / 2.0 / sampleRate

    /** Drzi samo poslednjih KEEP — inace disk raste bez granice. */
    private fun trim() {
        val files = list()
        files.take(maxOf(0, files.size - KEEP)).forEach { remove(it) }
    }

    /**
     * WAV parser koji prolazi kroz RIFF chunk-ove umesto da traži reč "data".
     * Tako rade i WAV fajlovi sa dodatnim zaglavljem, a sirov PCM iz stare
     * verzije i dalje prolazi nepromenjen.
     */
    private fun pcmFrom(bytes: ByteArray): ByteArray {
        if (bytes.size < 12 || String(bytes, 0, 4, Charsets.US_ASCII) != "RIFF" ||
            String(bytes, 8, 4, Charsets.US_ASCII) != "WAVE"
        ) return bytes
        var offset = 12
        while (offset + 8 <= bytes.size) {
            val chunk = String(bytes, offset, 4, Charsets.US_ASCII)
            val declared = littleEndianInt(bytes, offset + 4).toLong() and 0xffffffffL
            val start = offset + 8
            if (chunk == "data") {
                val end = minOf(bytes.size.toLong(), start.toLong() + declared).toInt()
                return if (end >= start) bytes.copyOfRange(start, end) else bytes
            }
            val next = start.toLong() + declared + (declared and 1L)
            if (next <= offset || next > bytes.size) break
            offset = next.toInt()
        }
        return bytes
    }

    private fun metadataFile(file: File): File = File(file.parentFile, "${file.name}.meta")

    private fun littleEndianInt(bytes: ByteArray, offset: Int): Int =
        (bytes[offset].toInt() and 0xff) or
            ((bytes[offset + 1].toInt() and 0xff) shl 8) or
            ((bytes[offset + 2].toInt() and 0xff) shl 16) or
            ((bytes[offset + 3].toInt() and 0xff) shl 24)

}
