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
class PendingStore(context: Context) {

    private val dir = File(context.filesDir, "neuspeli").apply { mkdirs() }

    companion object {
        private const val KEEP = 5   // koliko poslednjih drzimo
    }

    fun save(pcm: ByteArray): File? {
        if (pcm.isEmpty()) return null
        val file = File(dir, "${System.currentTimeMillis()}.pcm")
        return runCatching {
            file.writeBytes(pcm)
            trim()
            file
        }.getOrNull()
    }

    fun list(): List<File> =
        dir.listFiles()?.filter { it.name.endsWith(".pcm") }?.sortedBy { it.name } ?: emptyList()

    fun load(file: File): ByteArray = file.readBytes()

    fun remove(file: File) {
        file.delete()
    }

    fun count(): Int = list().size

    /** Drzi samo poslednjih KEEP — inace disk raste bez granice. */
    private fun trim() {
        val files = list()
        files.take(maxOf(0, files.size - KEEP)).forEach { it.delete() }
    }
}
