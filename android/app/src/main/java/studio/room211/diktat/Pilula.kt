package studio.room211.diktat

import android.content.Context
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.FrameLayout
import android.widget.TextView

/**
 * Okvir preko ekrana dok diktat traje: crna kartica (95 %) fiksne sirine kao
 * u 1.76 (vraceno 2026-11-25 na zahtev korisnika; titl sa trakom po redu iz
 * 1.87 izgledao je kao go tekst). Zuta kartica i crn tekst kad prepis kasni.
 * Stoji dole, bez dugmeta.
 *
 * Prozor je FLAG_NOT_FOCUSABLE: polje u koje tekst ide mora da zadrzi fokus.
 */
class Pilula(
    private val context: Context,
    private val cfg: Config,
    private val granica: () -> Int,
    private val onStop: () -> Unit,
) {
    private val windows = context.getSystemService(WindowManager::class.java)
    private var pill: View? = null
    private var preview: TextView? = null
    private val kartica = GradientDrawable()
    private var kasni = false
    private var poslednjiTekst = ""

    /** Postavlja servis: da li prepis kasni (glas se cuje, a teksta nema). */
    var proveraKasnjenja: () -> Boolean = { false }

    private val sat = object : Runnable {
        override fun run() {
            val v = pill ?: return
            postaviKasnjenje(proveraKasnjenja())
            v.postDelayed(this, 500)
        }
    }

    fun prikazi(): Boolean {
        if (pill != null) return true
        val text = TextView(context).apply {
            text = LISTENING
            textSize = 16f
            setTextColor(DIM)
            // Razmak redova = luft trake gore + dole, da se trake dodiruju
            // i da svaki red ima isti luft iznad i ispod slova.
            maxLines = MAX_REDOVA
            gravity = Gravity.BOTTOM or Gravity.START
            setPadding(dp(14), dp(12), dp(14), dp(12))
            kartica.cornerRadius = dp(16).toFloat()
            kartica.setColor(CRNO)
            background = kartica
        }
        // Samo kartica, bez dugmeta: prozor ne prima dodire, pa tastatura
        // ispod njega radi normalno. Diktat se zaustavlja kao i do sada.
        val view = FrameLayout(context).apply {
            addView(text, FrameLayout.LayoutParams(-1, -2))
        }
        val params = WindowManager.LayoutParams(
            context.resources.displayMetrics.widthPixels - dp(24),
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
                WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE,
            android.graphics.PixelFormat.TRANSLUCENT,
        ).apply {
            // Dole, iznad navigacione trake, sa malo lufta (2026-11-13).
            gravity = Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL
            y = dp(24)
        }
        return runCatching { windows.addView(view, params) }.onSuccess {
            pill = view
            preview = text
            kasni = false
            poslednjiTekst = ""
            view.post(sat)
        }.isSuccess
    }

    fun osvezi(seconds: Int, busy: Boolean, polishing: Boolean) { /* No elapsed-time UI. */ }

    fun pregled(tekst: String) {
        val t = preview ?: return
        poslednjiTekst = tekst.trim()
        postaviTekst(t, poslednjiTekst.takeLast(450).ifBlank { LISTENING })
        oboji()
        // Kartica ima najvise MAX_REDOVA redova. TextView tada crta PRVE redove,
        // pa bi red koji se upravo izgovara ostao skriven. Zato se posle
        // prelamanja odbace pocetni redovi i ostane samo rep.
        t.post {
            val layout = t.layout ?: return@post
            if (layout.lineCount > MAX_REDOVA) {
                val od = layout.getLineStart(layout.lineCount - MAX_REDOVA)
                postaviTekst(t, t.text.subSequence(od, t.text.length).toString())
            }
        }
    }

    private fun postaviKasnjenje(novo: Boolean) {
        if (novo == kasni) return
        kasni = novo
        kartica.setColor(if (kasni) ZUTO else CRNO)
        preview?.let { postaviTekst(it, it.text.toString()) }
        oboji()
    }

    private fun oboji() {
        val prazno = poslednjiTekst.isBlank()
        preview?.setTextColor(when {
            kasni && prazno -> 0x8C000000.toInt()
            kasni -> 0xEB000000.toInt()
            prazno -> DIM
            else -> Color.WHITE
        })
    }

    fun sakrij() {
        pill?.let {
            it.removeCallbacks(sat)
            runCatching { windows.removeView(it) }
        }
        pill = null
        preview = null
    }
    private fun postaviTekst(t: TextView, tekst: String) {
        t.text = tekst
    }

    private fun dp(value: Int) = (value * context.resources.displayMetrics.density).toInt()

    private companion object {
        const val LISTENING = "Listening…"
        const val DIM = 0x8CFFFFFF.toInt()
        const val MAX_REDOVA = 6
        const val CRNO = 0xF2000000.toInt()   // crna kartica, 95 % (od 1.90)
        const val ZUTO = 0xEBFFCC0D.toInt()
    }
}
