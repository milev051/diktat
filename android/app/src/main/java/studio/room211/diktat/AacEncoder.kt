package studio.room211.diktat

import android.media.MediaCodec
import android.media.MediaFormat
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer

/**
 * PCM -> AAC 32 kbps, iskljucivo za snimak koji ide MODELU.
 *
 * Izmereno na istom snimku: WAV 139 KB, FLAC 85 KB, AAC 18 KB — a prepis
 * identican. Zvuk se modelu salje u base64, sto ga uveca za trecinu, pa je na
 * telefonskom uplinku bas ta velicina bila glavni razlog cekanja.
 *
 * Endpointu se AAC NE salje: on prima samo PCM i FLAC.
 *
 * MediaCodec vraca sirove AAC okvire, bez kontejnera. Zato se ispred svakog
 * lepi ADTS zaglavlje od 7 bajtova — bez njega je tok neupotrebljiv.
 */
object AacEncoder {

    private const val TIMEOUT_US = 10_000L
    private const val BITRATE = 32_000

    // Indeksi ucestanosti iz AAC specifikacije; ADTS zaglavlje nosi indeks, ne broj.
    internal val RATES = mapOf(
        96000 to 0, 88200 to 1, 64000 to 2, 48000 to 3, 44100 to 4, 32000 to 5,
        24000 to 6, 22050 to 7, 16000 to 8, 12000 to 9, 11025 to 10, 8000 to 11,
    )

    fun encode(pcm: ByteArray, sampleRate: Int): ByteArray? {
        if (pcm.isEmpty() || sampleRate !in RATES) return null
        return runCatching { doEncode(pcm, sampleRate) }.getOrNull()
    }

    /** Vidljivo zbog testa: ovih 7 bajtova su pisani rukom. */
    internal fun adts(frameLength: Int, rateIndex: Int): ByteArray {
        val len = frameLength + 7
        return byteArrayOf(
            0xFF.toByte(),
            0xF1.toByte(),                                   // MPEG-4, bez CRC
            (((2 - 1) shl 6) or (rateIndex shl 2)).toByte(), // AAC LC, 1 kanal
            (((1 and 3) shl 6) or (len shr 11)).toByte(),
            ((len and 0x7FF) shr 3).toByte(),
            (((len and 7) shl 5) or 0x1F).toByte(),
            0xFC.toByte(),
        )
    }

    private fun doEncode(pcm: ByteArray, sampleRate: Int): ByteArray {
        val rateIndex = RATES.getValue(sampleRate)
        val format = MediaFormat.createAudioFormat(
            MediaFormat.MIMETYPE_AUDIO_AAC, sampleRate, 1
        ).apply {
            setInteger(MediaFormat.KEY_BIT_RATE, BITRATE)
            setInteger(MediaFormat.KEY_AAC_PROFILE, android.media.MediaCodecInfo.CodecProfileLevel.AACObjectLC)
            setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, 16384)
        }

        val codec = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_AUDIO_AAC)
        codec.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
        codec.start()

        val out = ByteArrayOutputStream(pcm.size / 8)
        val info = MediaCodec.BufferInfo()
        var offset = 0
        var fed = false
        // Tvrda granica: enkoder koji stane u INFO_TRY_AGAIN_LATER bi inace
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
                            index, 0, size,
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
                        // Zaglavlje kodeka (csd) se u ADTS toku ne prenosi.
                        if (info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG == 0 && info.size > 0) {
                            val buffer = codec.getOutputBuffer(index)!!
                            val bytes = ByteArray(info.size)
                            buffer.position(info.offset)
                            buffer.get(bytes)
                            out.write(adts(bytes.size, rateIndex))
                            out.write(bytes)
                        }
                        codec.releaseOutputBuffer(index, false)
                        if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) break
                    }

                    index == MediaCodec.INFO_TRY_AGAIN_LATER && fed && out.size() > 0 -> break
                }
            }
        } finally {
            runCatching { codec.stop() }
            runCatching { codec.release() }
        }

        val result = out.toByteArray()
        // Ispravan ADTS tok pocinje sinhro-recju 0xFFF.
        if (result.size < 16 || result[0] != 0xFF.toByte() || (result[1].toInt() and 0xF0) != 0xF0) {
            throw IllegalStateException("AAC tok nije ispravan")
        }
        return result
    }
}
