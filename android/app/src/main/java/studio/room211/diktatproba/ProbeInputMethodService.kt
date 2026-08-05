package studio.room211.diktatproba

import android.inputmethodservice.InputMethodService
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView

/**
 * B — glasovni IME (tastatura koja ima samo dugme).
 *
 * Rezervna varijanta: uvek radi, jer commitText() ubacuje tekst u polje bez
 * ikakve posebne dozvole. Mana je trenje — moras da prebacis tastaturu.
 */
class ProbeInputMethodService : InputMethodService() {

    override fun onCreateInputView(): View {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding(32, 48, 32, 48)
        }

        root.addView(TextView(this).apply {
            text = "Diktat proba — tastatura (B)"
            textSize = 14f
            gravity = Gravity.CENTER
            setPadding(0, 0, 0, 24)
        })

        root.addView(Button(this).apply {
            text = "Ubaci probni tekst"
            setOnClickListener {
                currentInputConnection?.commitText("proba b — ime radi ", 1)
            }
        })

        root.addView(Button(this).apply {
            text = "Nazad na prethodnu tastaturu"
            setOnClickListener { switchToPreviousInputMethod() }
        })

        return root
    }
}
