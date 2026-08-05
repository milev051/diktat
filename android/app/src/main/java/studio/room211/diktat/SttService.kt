package studio.room211.diktat

import android.content.Intent
import android.os.Bundle
import android.speech.RecognitionService
import android.speech.SpeechRecognizer
import kotlin.concurrent.thread

/**
 * Put A — mikrofon na postojecoj tastaturi.
 *
 * Kad je izabrana kao "Voice input", tastatura zove nas umesto Google-a, mi
 * vratimo vec doteran tekst, a ona ga sama ubaci. Bez ijedne posebne dozvole
 * osim mikrofona.
 */
class SttService : RecognitionService() {

    private var recorder: Recorder? = null
    private lateinit var cfg: Config

    override fun onCreate() {
        super.onCreate()
        cfg = Config(this)
    }

    override fun onStartListening(intent: Intent, listener: Callback) {
        cfg = Config(this)
        listener.readyForSpeech(Bundle())
        try {
            recorder = Recorder(cfg.sampleRate).also { it.start() }
            listener.beginningOfSpeech()
        } catch (exc: Exception) {
            listener.error(SpeechRecognizer.ERROR_AUDIO)
        }
    }

    override fun onStopListening(listener: Callback) = finish(listener)

    override fun onCancel(listener: Callback) {
        recorder?.stop()
        recorder = null
    }

    private fun finish(listener: Callback) {
        val pcm = recorder?.stop() ?: ByteArray(0)
        recorder = null
        listener.endOfSpeech()
        thread {
            try {
                val text = TextPolish.apply(WebStt.recognize(pcm, cfg), cfg)
                if (text.isBlank()) {
                    listener.error(SpeechRecognizer.ERROR_NO_MATCH)
                    return@thread
                }
                listener.results(Bundle().apply {
                    putStringArrayList(
                        SpeechRecognizer.RESULTS_RECOGNITION, arrayListOf(text)
                    )
                    putFloatArray(SpeechRecognizer.CONFIDENCE_SCORES, floatArrayOf(1f))
                })
            } catch (_: Exception) {
                runCatching { listener.error(SpeechRecognizer.ERROR_NETWORK) }
            }
        }
    }
}
