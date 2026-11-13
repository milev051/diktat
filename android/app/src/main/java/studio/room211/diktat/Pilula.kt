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
 * Okvir preko ekrana dok diktat traje, u izgledu titla kao na Macu (od
 * 2026-11-13): centriran tekst, svaki red na crnoj cetvrtastoj traci 75 %,
 * zute trake i crn tekst kad prepis kasni. Stoji dole, bez dugmeta.
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
    private val trake = TitlTrake()
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
            includeFontPadding = false
            setLineSpacing(2f * dp(4), 1f)
            maxLines = MAX_REDOVA
            gravity = Gravity.CENTER
            // Mesto za traku oko reda: span je crta van teksta, unutar paddinga.
            setPadding(dp(8), dp(4), dp(8), dp(4))
            setShadowLayer(0f, 0f, 0f, 0)
        }
        // Samo titl, bez dugmeta: prozor ne prima dodire, pa tastatura
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
        trake.boja = if (kasni) ZUTO else CRNO
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
        // Stop ostaje beli kvadrat na crnom krugu i kad trake pozute.
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
        trake.padX = dp(8).toFloat()
        trake.padY = dp(4).toFloat()
        t.text = android.text.SpannableString(tekst).apply {
            setSpan(trake, 0, length, android.text.Spanned.SPAN_INCLUSIVE_INCLUSIVE)
        }
    }

    private fun dp(value: Int) = (value * context.resources.displayMetrics.density).toInt()

    private companion object {
        const val LISTENING = "Listening…"
        const val DIM = 0x8CFFFFFF.toInt()
        const val MAX_REDOVA = 6
        const val CRNO = 0xBF000000.toInt()   // 75 % crno, kao traka titla
        const val ZUTO = 0xEBFFCC0D.toInt()
    }
}

/**
 * Crna cetvrtasta traka iza svakog reda, sirine samog teksta tog reda.
 * Trake susednih redova se dodiruju bez preklapanja, da 75 % ne postane tamnije.
 */
class TitlTrake : android.text.style.LineBackgroundSpan {
    var boja = 0xBF000000.toInt()
    var padX = 0f
    var padY = 0f
    private val rect = android.graphics.RectF()

    override fun drawBackground(
        canvas: android.graphics.Canvas, paint: android.graphics.Paint,
        left: Int, right: Int, top: Int, baseline: Int, bottom: Int,
        text: CharSequence, start: Int, end: Int, lineNumber: Int,
    ) {
        val red = text.subSequence(start, end).toString().trimEnd()
        if (red.isEmpty()) return
        val sirina = paint.measureText(red)
        val sredina = (left + right) / 2f
        // Traka se meri od slova, ne od reda: razmak redova ide samo ispod
        // reda, pa bi traka po redu imala luft dole, a ne gore.
        val fm = paint.fontMetrics
        rect.set(
            sredina - sirina / 2 - padX,
            baseline + fm.ascent - padY,
            sredina + sirina / 2 + padX,
            baseline + fm.descent + padY,
        )
        val stara = paint.color
        paint.color = boja
        canvas.drawRect(rect, paint)
        paint.color = stara
    }
}
