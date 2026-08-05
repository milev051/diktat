package studio.room211.diktatproba

import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.os.Bundle
import android.widget.Toast

/**
 * C — digitalni asistent (bocni taster).
 *
 * Radi svuda, ne samo kad je tastatura otvorena. Ali obicna aktivnost otima
 * fokus polju u koje bi tekst trebalo da udje — zato proba i ne pokusava da
 * pise, nego samo javi da je pokrenuta i spusti marker u clipboard.
 */
class AssistActivity : Activity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val marker = "proba c — asistent radi"
        getSystemService(ClipboardManager::class.java)
            ?.setPrimaryClip(ClipData.newPlainText("diktat", marker))
        Toast.makeText(this, "$marker\n(marker je u clipboard-u)", Toast.LENGTH_LONG).show()
        finish()
    }
}
