package studio.room211.diktat

import kotlin.math.max
import kotlin.math.min

/**
 * Prepoznaje pauzu u govoru, sa pragom koji se sam prilagodjava sobi.
 *
 * Fiksni prag ne valja: u tihoj sobi je pozadina ~0.01, u bucnoj ~0.08. Zato
 * se prati "pod" (najtisi nivo do sada) i pauzom se smatra sve ispod `factor`
 * puta tog poda.
 *
 * Prag je ogranicen i odozgo, na PEAK_FRACTION puta najglasnije culo: bez toga
 * bi snimanje koje pocne usred reci inicijalizovalo pod na nivo govora, prag bi
 * odleteo iznad svega i nijedna pauza ne bi bila prepoznata.
 */
class PauseDetector(
    private val pauseSeconds: Double = 0.7,
    private val factor: Double = 2.5,
    private val floorMin: Double = 0.015,
) {
    companion object {
        private const val FLOOR_DOWN = 0.30    // pod brzo pada ka novom minimumu
        private const val FLOOR_UP = 0.002     // a vrlo sporo raste
        private const val PEAK_DECAY = 0.999
        private const val PEAK_FRACTION = 0.25
    }

    private var floor: Double? = null
    private var peak: Double? = null
    private var quietFor = 0.0
    private var heardSpeech = false

    fun reset() {
        quietFor = 0.0
        heardSpeech = false
    }

    val threshold: Double
        get() {
            val low = max(floorMin, (floor ?: 0.0) * factor)
            val p = peak ?: return low
            return min(low, max(floorMin, p * PEAK_FRACTION))
        }

    /** Ubaci nivo jednog komada. Vraca true kad pauza dostigne prag. */
    fun feed(level: Double, dt: Double): Boolean {
        peak = peak?.let { max(level, it * PEAK_DECAY) } ?: level

        val f = floor
        floor = when {
            f == null -> level
            level < f -> f + (level - f) * FLOOR_DOWN
            else -> f + (level - f) * FLOOR_UP
        }

        if (level < threshold) {
            quietFor += dt
        } else {
            quietFor = 0.0
            heardSpeech = true
        }
        // Bez provere da je bilo govora, duza tisina bi okidala u nedogled i
        // slala prazne segmente.
        return heardSpeech && quietFor >= pauseSeconds
    }
}

/** Priblizan vrh amplitude komada, 0.0-1.0. Gleda svaki 16. sempl. */
fun peakLevel(pcm: ByteArray, length: Int = pcm.size): Double {
    var top = 0
    var i = 0
    while (i + 1 < length) {
        val v = ((pcm[i + 1].toInt() shl 8) or (pcm[i].toInt() and 0xFF)).toShort().toInt()
        val a = if (v < 0) -v else v
        if (a > top) top = a
        i += 32
    }
    return min(1.0, top / 32768.0)
}
