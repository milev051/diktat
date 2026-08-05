package studio.room211.diktat

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import java.io.ByteArrayOutputStream
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

/**
 * Mikrofon -> 16-bit PCM, isti format koji endpoint prima.
 *
 * Komadi izlaze kroz red umesto da se gomilaju u jednom baferu: u neprekidnom
 * rezimu snimanje traje koliko treba, a sat vremena bi u baferu bilo preko
 * 100 MB. Potrosac skuplja samo tekuci segment i pusta ga cim ga posalje.
 */
class Recorder(private val sampleRate: Int) {

    private val queue = LinkedBlockingQueue<ByteArray>()
    private var record: AudioRecord? = null
    private var worker: Thread? = null
    @Volatile private var running = false

    @Volatile
    var captured = 0L
        private set

    @SuppressLint("MissingPermission")
    fun start() {
        val minBuf = AudioRecord.getMinBufferSize(
            sampleRate,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        val rec = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION,
            sampleRate,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            maxOf(minBuf, sampleRate),   // bar sekunda, da ne pucketa
        )
        check(rec.state == AudioRecord.STATE_INITIALIZED) { "Mikrofon nije dostupan" }

        record = rec
        running = true
        rec.startRecording()

        worker = thread(name = "diktat-rec") {
            val size = minOf(4096, maxOf(minBuf, 2048))
            while (running) {
                val chunk = ByteArray(size)
                val read = rec.read(chunk, 0, size)
                if (read > 0) {
                    captured += read
                    queue.put(if (read == size) chunk else chunk.copyOf(read))
                }
            }
        }
    }

    /**
     * Sledeci komad zvuka.
     *
     * Prazan niz znaci "jos nista, ali snimanje traje" — potrosac tada moze da
     * osvezi prikaz. `null` znaci da je snimanje zaustavljeno i red ispraznjen.
     */
    fun nextChunk(timeoutMs: Long = 250): ByteArray? {
        val chunk = queue.poll(timeoutMs, TimeUnit.MILLISECONDS)
        if (chunk != null) return chunk
        return if (running) ByteArray(0) else null
    }

    /**
     * Trazi kraj snimanja bez ciscenja: `nextChunk` ce vratiti jos ono sto je
     * u redu, pa tek onda null. Petlja koja secka segmente tako pokupi i
     * poslednje komade pre nego sto posalje rep.
     */
    fun requestStop() {
        running = false
    }

    /** Zaustavi snimanje i vrati sve sto jos stoji u redu. */
    fun stop(): ByteArray {
        running = false
        worker?.join(1000)
        worker = null
        record?.runCatching { stop(); release() }
        record = null

        val rest = ByteArrayOutputStream()
        while (true) {
            val chunk = queue.poll() ?: break
            rest.write(chunk)
        }
        return rest.toByteArray()
    }

    /** Snimaj do zaustavljanja i vrati sve odjednom — za obican rezim. */
    fun drainAll(): ByteArray {
        val all = ByteArrayOutputStream()
        while (true) {
            val chunk = nextChunk() ?: break
            if (chunk.isNotEmpty()) all.write(chunk)
        }
        all.write(stop())
        return all.toByteArray()
    }
}
