package studio.room211.diktat

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.speech.RecognizerIntent

/**
 * Odgovara tastaturi koje jezike podrzavamo.
 *
 * Bez ovoga Samsung tastatura pretpostavi da servis zna samo engleski i odbije
 * da ga ponudi za srpski — jer nema od koga da sazna suprotno. Gboard ovo ne
 * pita, pa se tamo nije ni primetilo.
 */
class LanguageDetailsReceiver : BroadcastReceiver() {

    companion object {
        /** Jezici koje endpoint dobro radi; prvi je podrazumevan. */
        private val SUPPORTED = arrayListOf(
            "sr-RS", "hr-HR", "bs-BA", "sl-SI", "mk-MK",
            "en-US", "en-GB", "de-DE", "it-IT", "ru-RU",
        )
    }

    override fun onReceive(context: Context, intent: Intent) {
        val cfg = Config(context)
        val preferred = cfg.language.ifBlank { SUPPORTED.first() }

        val details = Bundle().apply {
            putString(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE, preferred)
            putStringArrayList(
                RecognizerIntent.EXTRA_SUPPORTED_LANGUAGES,
                ArrayList(linkedSetOf(preferred) + SUPPORTED),
            )
        }

        // Neke tastature citaju iz result extras, neke iz result data.
        // getResultExtras(true) napravi Bundle ako ga jos nema.
        getResultExtras(true).putAll(details)
        setResultData(preferred)
        setResultCode(android.app.Activity.RESULT_OK)
    }
}
