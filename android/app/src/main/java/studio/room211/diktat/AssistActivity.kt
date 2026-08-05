package studio.room211.diktat

import android.app.Activity
import android.content.Intent
import android.os.Bundle

/**
 * Okidac sa bocnog tastera.
 *
 * Aktivnost je providna i odmah se zatvara — sav posao radi servis, da polje u
 * kome je kursor sto krace bude bez fokusa.
 */
class AssistActivity : Activity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        startForegroundService(
            Intent(this, DictationService::class.java)
                .setAction(DictationService.ACTION_TOGGLE)
        )
        finish()
        overridePendingTransition(0, 0)
    }
}
