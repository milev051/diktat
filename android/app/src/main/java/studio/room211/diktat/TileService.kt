package studio.room211.diktat

import android.content.Intent
import android.service.quicksettings.TileService

/** Rezervni okidac: plocica u brzim podesavanjima radi isto sto i bocni taster. */
class DiktatTileService : TileService() {
    override fun onClick() {
        startForegroundService(
            Intent(this, DictationService::class.java)
                .setAction(DictationService.ACTION_TOGGLE)
        )
    }
}
