package studio.room211.diktat

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager

/**
 * Tisina dok se snima: utisani mediji i pauzirana muzika ili video.
 *
 * Isto kao dictate/zvuk.py na Mac-u, dve odvojene opcije:
 *
 *   utisaj    utisa zvuk medija (STREAM_MUSIC), pa ga vrati.
 *   pauziraj  trazi audio fokus; plejer (YouTube, Spotify) tada sam stane, a
 *             nastavi kad se fokus vrati. To je ugradjen Android nacin, pa
 *             ovde nema opasnosti sa Mac-a da se pokrene nesto sto nije sviralo.
 *
 * Vraca se samo ono sto je Diktat promenio: vec utisan telefon ostaje utisan.
 */
class Tisina(context: Context, private val utisaj: Boolean, private val pauziraj: Boolean) {

    private val audio = context.getSystemService(AudioManager::class.java)
    private var utisao = false
    private var fokus: AudioFocusRequest? = null

    @Synchronized
    fun pocni() {
        if (pauziraj && fokus == null) {
            val zahtev = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
                .setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_ASSISTANT)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                        .build()
                )
                .setOnAudioFocusChangeListener { }
                .build()
            if (audio.requestAudioFocus(zahtev) == AudioManager.AUDIOFOCUS_REQUEST_GRANTED) {
                fokus = zahtev
            }
        }
        if (utisaj && !utisao && !audio.isStreamMute(AudioManager.STREAM_MUSIC)) {
            audio.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_MUTE, 0)
            utisao = true
        }
    }

    /** Sme da se zove vise puta; drugi poziv ne radi nista. */
    @Synchronized
    fun vrati() {
        if (utisao) {
            audio.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_UNMUTE, 0)
            utisao = false
        }
        fokus?.let { audio.abandonAudioFocusRequest(it) }
        fokus = null
    }

    companion object {
        /** Po podesavanjima; `null` kad su obe opcije ugasene. */
        fun za(context: Context, cfg: Config): Tisina? =
            if (cfg.utisajZvuk || cfg.pauzirajPlejer) {
                Tisina(context, cfg.utisajZvuk, cfg.pauzirajPlejer)
            } else {
                null
            }
    }
}
