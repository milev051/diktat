package studio.room211.diktat

import android.content.Context
import android.media.AudioFormat
import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import android.net.Uri
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** Pretvara audio iz drugih aplikacija u 16 kHz, mono, 16-bit PCM. */
object AudioDecoder {

    private const val TIMEOUT_US = 10_000L
    private const val TARGET_RATE = 16_000

    fun decode(context: Context, uri: Uri): ByteArray {
        val extractor = MediaExtractor()
        var codec: MediaCodec? = null
        try {
            extractor.setDataSource(context, uri, emptyMap())
            val trackIndex = (0 until extractor.trackCount).firstOrNull { index ->
                extractor.getTrackFormat(index).getString(MediaFormat.KEY_MIME)
                    ?.startsWith("audio/") == true
            } ?: throw IllegalArgumentException("Fajl nema audio zapis.")

            val format = extractor.getTrackFormat(trackIndex)
            val mime = format.getString(MediaFormat.KEY_MIME)
                ?: throw IllegalArgumentException("Nepoznat audio format.")
            val sourceRate = format.getInteger(MediaFormat.KEY_SAMPLE_RATE)
            val sourceChannels = format.getInteger(MediaFormat.KEY_CHANNEL_COUNT)
            require(sourceRate > 0 && sourceChannels > 0) { "Audio nema ispravan format." }

            extractor.selectTrack(trackIndex)
            codec = MediaCodec.createDecoderByType(mime)
            codec.configure(format, null, null, 0)
            codec.start()

            val decoded = ByteArrayOutputStream()
            var inputDone = false
            var outputDone = false
            var pcmEncoding = intOr(
                format, MediaFormat.KEY_PCM_ENCODING, AudioFormat.ENCODING_PCM_16BIT,
            )

            while (!outputDone) {
                if (!inputDone) {
                    val inputIndex = codec.dequeueInputBuffer(TIMEOUT_US)
                    if (inputIndex >= 0) {
                        val input = codec.getInputBuffer(inputIndex)
                            ?: throw IllegalStateException("Dekoder nije dao ulazni bafer.")
                        val sampleSize = extractor.readSampleData(input, 0)
                        if (sampleSize < 0) {
                            codec.queueInputBuffer(
                                inputIndex, 0, 0, 0L, MediaCodec.BUFFER_FLAG_END_OF_STREAM,
                            )
                            inputDone = true
                        } else {
                            val timestamp = extractor.sampleTime.coerceAtLeast(0L)
                            codec.queueInputBuffer(inputIndex, 0, sampleSize, timestamp, 0)
                            extractor.advance()
                        }
                    }
                }

                when (val outputIndex = codec.dequeueOutputBuffer(OUTPUT_INFO, TIMEOUT_US)) {
                    MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {
                        val outputFormat = codec.outputFormat
                        pcmEncoding = intOr(outputFormat, MediaFormat.KEY_PCM_ENCODING, pcmEncoding)
                    }
                    MediaCodec.INFO_TRY_AGAIN_LATER -> Unit
                    else -> if (outputIndex >= 0) {
                        if (OUTPUT_INFO.size > 0 &&
                            OUTPUT_INFO.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG == 0
                        ) {
                            val output = codec.getOutputBuffer(outputIndex)
                                ?: throw IllegalStateException("Dekoder nije dao izlazni bafer.")
                            val start = OUTPUT_INFO.offset.coerceAtLeast(0)
                            val end = (start + OUTPUT_INFO.size).coerceAtMost(output.limit())
                            if (end > start) {
                                output.position(start)
                                output.limit(end)
                                val chunk = ByteArray(output.remaining())
                                output.get(chunk)
                                decoded.write(chunk)
                            }
                        }
                        outputDone = OUTPUT_INFO.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0
                        codec.releaseOutputBuffer(outputIndex, false)
                    }
                }
            }
            return normalize(decoded.toByteArray(), sourceRate, sourceChannels, pcmEncoding)
        } finally {
            runCatching { codec?.stop() }
            runCatching { codec?.release() }
            extractor.release()
        }
    }

    private fun normalize(
        bytes: ByteArray,
        sourceRate: Int,
        channels: Int,
        encoding: Int,
    ): ByteArray {
        if (bytes.isEmpty()) return bytes
        val sourceSamples = if (encoding == AudioFormat.ENCODING_PCM_FLOAT) {
            val floats = bytes.size / 4
            FloatArray(floats) { index ->
                ByteBuffer.wrap(bytes, index * 4, 4)
                    .order(ByteOrder.LITTLE_ENDIAN).getFloat()
            }.map { (it.coerceIn(-1f, 1f) * 32767f).toInt().toShort() }.toShortArray()
        } else {
            val shorts = bytes.size / 2
            ShortArray(shorts) { index ->
                ByteBuffer.wrap(bytes, index * 2, 2)
                    .order(ByteOrder.LITTLE_ENDIAN).getShort()
            }
        }
        val frames = sourceSamples.size / channels
        if (frames == 0) return ByteArray(0)
        val mono = ShortArray(frames) { frame ->
            var sum = 0
            for (channel in 0 until channels) sum += sourceSamples[frame * channels + channel].toInt()
            (sum / channels).coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt()).toShort()
        }
        val targetFrames = (frames.toLong() * TARGET_RATE / sourceRate).toInt().coerceAtLeast(1)
        val out = ByteBuffer.allocate(targetFrames * 2).order(ByteOrder.LITTLE_ENDIAN)
        for (index in 0 until targetFrames) {
            val sourceIndex = (index.toLong() * sourceRate / TARGET_RATE)
                .toInt().coerceAtMost(mono.lastIndex)
            out.putShort(mono[sourceIndex])
        }
        return out.array()
    }

    private val OUTPUT_INFO = MediaCodec.BufferInfo()

    private fun intOr(format: MediaFormat, key: String, fallback: Int): Int =
        if (format.containsKey(key)) format.getInteger(key) else fallback
}
