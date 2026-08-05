package studio.room211.diktatproba

import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognitionService
import android.speech.SpeechRecognizer

/**
 * A — RecognitionService.
 *
 * Ovo je slot u kome vec stoje "Samsung voice input" i "Google voice input".
 * Ako se ovde uspesno ubacimo, mikrofon na POSTOJECOJ tastaturi zove nas, mi
 * vratimo tekst kakav hocemo, a tastatura ga sama ubaci — bez nove tastature
 * i bez Accessibility dozvole.
 *
 * Proba vraca fiksan tekst; pravo prepoznavanje dolazi tek kad znamo da slot radi.
 */
class ProbeRecognitionService : RecognitionService() {

    private val handler = Handler(Looper.getMainLooper())

    override fun onStartListening(intent: Intent, listener: Callback) {
        listener.readyForSpeech(Bundle())
        listener.beginningOfSpeech()

        // Kratka pauza: neke tastature ne ocekuju rezultat u istom trenutku
        // u kome su pozvale, pa bi ga propustile.
        handler.postDelayed({
            try {
                listener.endOfSpeech()
                listener.results(resultBundle("proba a — recognition service radi"))
            } catch (_: Exception) {
                // Tastatura je u medjuvremenu odustala; nema sta da se radi.
            }
        }, 800)
    }

    override fun onStopListening(listener: Callback) {}

    override fun onCancel(listener: Callback) {
        handler.removeCallbacksAndMessages(null)
    }

    private fun resultBundle(text: String) = Bundle().apply {
        putStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION, arrayListOf(text))
        putFloatArray(SpeechRecognizer.CONFIDENCE_SCORES, floatArrayOf(1.0f))
    }
}
