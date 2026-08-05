package studio.room211.diktat

import android.media.AudioFormat
import android.media.MediaCodec
import android.media.MediaFormat
import android.os.Build
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer

/**
 * PCM -> FLAC, da se salje manje podataka.
 *
 * Izmereno na endpointu: 36% manje na snimku od 5s, 42% na 24s, uz identican
 * transkript. Endpoint prima iskljucivo `audio/x-flac; rate=N` — bez `rate=`
 * ili sa `audio/flac` vraca 400.
 *
 * Vraca null na bilo kakav problem; pozivalac tada salje PCM. Kodiranje nikad
 * ne sme da obori diktat zbog ustede podataka.
 */
object FlacEncoder {

    private const val TIMEOUT_US = 10_000L

    val available: Boolean
        get() = Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q   // FLAC enkoder od Androida 10

    fun encode(pcm: ByteArray, sampleRate: Int): ByteArray? {
        if (!available || pcm.isEmpty()) return null
        return runCatching { doEncode(pcm, sampleRate) }.getOrNull()
    }

    private fun doEncode(pcm: ByteArray, sampleRate: Int): ByteArray {
        val format = MediaFormat.createAudioFormat(
            MediaFormat.MIMETYPE_AUDIO_FLAC, sampleRate, 1
        ).apply {
            setInteger(MediaFormat.KEY_PCM_ENCODING, AudioFormat.ENCODING_PCM_16BIT)
            setInteger(MediaFormat.KEY_FLAC_COMPRESSION_LEVEL, 5)
            setInteger(MediaFormat.KEY_BIT_RATE, sampleRate * 16)
        }

        val codec = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_AUDIO_FLAC)
        codec.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
        codec.start()

        val out = ByteArrayOutputStream(pcm.size / 2)
        val info = MediaCodec.BufferInfo()
        var offset = 0
        var fed = false
        var headerWritten = false
        // Tvrda granica: bez nje bi enkoder koji stane u INFO_TRY_AGAIN_LATER
        // vrteo petlju u nedogled i zamrznuo diktat.
        val deadline = System.currentTimeMillis() + 15_000

        try {
            while (System.currentTimeMillis() < deadline) {
                if (!fed) {
                    val index = codec.dequeueInputBuffer(TIMEOUT_US)
                    if (index >= 0) {
                        val buffer: ByteBuffer = codec.getInputBuffer(index)!!
                        buffer.clear()
                        val size = minOf(buffer.capacity(), pcm.size - offset)
                        if (size > 0) buffer.put(pcm, offset, size)
                        val last = offset + size >= pcm.size
                        codec.queueInputBuffer(
                            index,
                            0,
                            size,
                            offset.toLong() * 1_000_000L / 2 / sampleRate,
                            if (last) MediaCodec.BUFFER_FLAG_END_OF_STREAM else 0,
                        )
                        offset += size
                        if (last) fed = true
                    }
                }

                val index = codec.dequeueOutputBuffer(info, TIMEOUT_US)
                when {
                    index >= 0 -> {
                        val buffer = codec.getOutputBuffer(index)!!
                        val bytes = ByteArray(info.size)
                        buffer.position(info.offset)
                        buffer.get(bytes)
                        val isHeader =
                            info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG != 0
                        if (!isHeader || !headerWritten) {
                            out.write(bytes)
                            if (isHeader) headerWritten = true
                        }
                        codec.releaseOutputBuffer(index, false)
                        if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) break
                    }

                    index == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {
                        // Neki enkoderi zaglavlje ("fLaC" + STREAMINFO) daju samo
                        // ovde, a ne kao BUFFER_FLAG_CODEC_CONFIG.
                        if (!headerWritten) {
                            codec.outputFormat.getByteBuffer("csd-0")?.let { csd ->
                                val bytes = ByteArray(csd.remaining())
                                csd.get(bytes)
                                out.write(bytes)
                                headerWritten = true
                            }
                        }
                    }

                    index == MediaCodec.INFO_TRY_AGAIN_LATER && fed && out.size() > 0 -> break
                }
            }
        } finally {
            runCatching { codec.stop() }
            runCatching { codec.release() }
        }

        val result = out.toByteArray()
        // Ispravan FLAC uvek pocinje sa "fLaC".
        val magic = byteArrayOf(0x66, 0x4C, 0x61, 0x43)
        if (result.size < 64 || !result.copyOfRange(0, 4).contentEquals(magic)) {
            throw IllegalStateException("FLAC tok nije ispravan")
        }
        return result
    }
}
