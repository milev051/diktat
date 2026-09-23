package studio.room211.diktat

import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
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
    private var activeListener: Callback? = null
    private val handler = Handler(Looper.getMainLooper())
    private val safetyStop = Runnable {
        activeListener?.let { finish(it) }
    }

    override fun onCreate() {
        super.onCreate()
        cfg = Config(this)
    }

    override fun onStartListening(intent: Intent, listener: Callback) {
        cfg = Config(this)
        activeListener = listener
        listener.readyForSpeech(Bundle())
        try {
            recorder = Recorder(cfg.sampleRate).also { it.start() }
            listener.beginningOfSpeech()
            if (cfg.transcriptionProvider == "openai") {
                val seconds = if (cfg.openAiLongRecording) {
                    cfg.openAiMaxSeconds
                } else {
                    cfg.maxSeconds
                }
                handler.postDelayed(safetyStop, seconds * 1000L)
            }
        } catch (exc: Exception) {
            activeListener = null
            listener.error(SpeechRecognizer.ERROR_AUDIO)
        }
    }

    override fun onStopListening(listener: Callback) = finish(listener)

    override fun onCancel(listener: Callback) {
        handler.removeCallbacks(safetyStop)
        val pcm = recorder?.stop() ?: ByteArray(0)
        cfg.addRecordedSeconds(pcm.size / 2.0 / cfg.sampleRate)
        recorder = null
        activeListener = null
    }

    private fun finish(listener: Callback) {
        if (recorder == null) return
        handler.removeCallbacks(safetyStop)
        val pcm = recorder?.stop() ?: ByteArray(0)
        cfg.addRecordedSeconds(pcm.size / 2.0 / cfg.sampleRate)
        recorder = null
        activeListener = null
        listener.endOfSpeech()
        thread {
            try {
                val text = Prepoznaj.tekst(pcm, cfg)
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
            } catch (exc: Exception) {
                // Bez Toast-a: tastatura vec prikazuje gresku, a dodatna
                // poruka je izgledala kao da isti poziv puca vise puta.
                runCatching { listener.error(SpeechRecognizer.ERROR_NETWORK) }
            }
        }
    }

    override fun onDestroy() {
        handler.removeCallbacks(safetyStop)
        val pcm = recorder?.stop() ?: ByteArray(0)
        cfg.addRecordedSeconds(pcm.size / 2.0 / cfg.sampleRate)
        recorder = null
        activeListener = null
        super.onDestroy()
    }
}
