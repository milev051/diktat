package studio.room211.diktatproba

import android.content.ClipData
import android.content.ClipboardManager
import android.service.quicksettings.TileService
import android.widget.Toast

/**
 * E — plocica u brzim podesavanjima.
 *
 * Najkraci put do necega sto radi: nula posebnih dozvola, radi svuda, ali
 * tekst zavrsi u clipboard-u pa se lepi rucno.
 */
class ProbeTileService : TileService() {

    override fun onClick() {
        val marker = "proba e — plocica radi"
        getSystemService(ClipboardManager::class.java)
            ?.setPrimaryClip(ClipData.newPlainText("diktat", marker))
        Toast.makeText(this, "$marker\n(marker je u clipboard-u)", Toast.LENGTH_LONG).show()
    }
}
