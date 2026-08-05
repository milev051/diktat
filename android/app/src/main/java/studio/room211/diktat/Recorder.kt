package studio.room211.diktat

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import java.io.ByteArrayOutputStream
import kotlin.concurrent.thread

/** Mikrofon -> 16-bit PCM, isti format koji endpoint prima. */
class Recorder(private val sampleRate: Int) {

    private var record: AudioRecord? = null
    private var worker: Thread? = null
    @Volatile private var running = false
    private val buffer = ByteArrayOutputStream()

    val seconds: Double get() = synchronized(buffer) { buffer.size() / 2.0 / sampleRate }

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
            val chunk = ByteArray(minOf(4096, maxOf(minBuf, 2048)))
            while (running) {
                val read = rec.read(chunk, 0, chunk.size)
                if (read > 0) synchronized(buffer) { buffer.write(chunk, 0, read) }
            }
        }
    }

    /** Zaustavi i vrati sve sto je snimljeno. */
    fun stop(): ByteArray {
        running = false
        worker?.join(1000)
        worker = null
        record?.runCatching { stop(); release() }
        record = null
        return synchronized(buffer) { buffer.toByteArray() }
    }
}
