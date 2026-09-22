package studio.room211.diktat

import android.content.Context
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast

/**
 * Pilula preko ekrana dok diktat traje: dugme „Aa/aa", brojac i pregled uzivo.
 *
 * Prozor je FLAG_NOT_FOCUSABLE: polje u koje tekst treba da udje mora da
 * zadrzi fokus, inace nema gde da se upise. Isti problem kao HUD u macOS
 * verziji. Servis (`DictationService`) je samo pali, osvezava i gasi; sve o
 * izgledu je ovde.
 *
 * `granica` je trenutna granica snimanja u sekundama; racuna je servis
 * (`Granica.sekundi`), da pilula i tajmer nikad ne pokazuju razlicitu.
 */
class Pilula(
    private val context: Context,
    private val cfg: Config,
    private val granica: () -> Int,
) {
    private val windows = context.getSystemService(WindowManager::class.java)
    private var pill: View? = null
    private var pillCounter: TextView? = null
    private var pillToggle: TextView? = null
    private var pillPreview: TextView? = null

    /** Prikazi pilulu; vraca false ako nema dozvolu za prikaz preko drugih aplikacija. */
    fun prikazi(): Boolean {
        if (pill != null) return true

        val brojac = TextView(context).apply {
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 20f)
            setTextColor(Color.WHITE)
            gravity = Gravity.CENTER
            val pad = dp(18)
            setPadding(pad, dp(10), pad, dp(10))
            background = GradientDrawable().apply {
                cornerRadius = dp(22).toFloat()
                setColor(Color.parseColor("#1C8F3D"))
            }
            text = "00"
        }

        // Dugme za „pravilno", LEVO od brojaca. Menja sva cetiri prekidaca za
        // izgled teksta odjednom i to stanje OSTAJE za sledeci diktat.
        //
        // Sam natpis nosi stanje: „Aa" znaci pravopisno, „aa" znaci kako si
        // izgovorio. Ikonica bi ovde bila gora — pilula je siroka par
        // centimetara i gleda se krajickom oka usred diktata, pa dva slova
        // kazu vise nego bilo koji simbol.
        val prekidac = TextView(context).apply {
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 17f)
            gravity = Gravity.CENTER
            // Sirok dodir: prst ide na dugme dok govoris, ne gledajuci.
            minWidth = dp(46)
            minHeight = dp(44)
            setPadding(dp(12), dp(10), dp(12), dp(10))
            isClickable = true
            setOnClickListener { togglePravilno() }
        }

        val red = LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            addView(prekidac)
            addView(
                brojac,
                LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.WRAP_CONTENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT,
                ).apply { leftMargin = dp(8) },
            )
        }

        val preview = TextView(context).apply {
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 16f)
            setTextColor(Color.WHITE)
            setPadding(dp(14), dp(12), dp(14), dp(12))
            maxWidth = context.resources.displayMetrics.widthPixels - dp(28)
            maxLines = 6
            // Dno, ne vrh: tekst preraste šest redova posle ~15s govora, a
            // TextView tada pokazuje PRVIH šest, pa nove reči padaju van
            // okvira i prikaz izgleda kao da kasni. Uz donju gravitaciju
            // TextView sam skroluje na poslednji red.
            gravity = Gravity.BOTTOM or Gravity.START
            text = "Slušam…"
            background = GradientDrawable().apply {
                cornerRadius = dp(16).toFloat()
                setColor(Color.parseColor("#E61F2933"))
            }
            visibility = if (GeminiStt.enabled(cfg) && cfg.geminiLivePreview) {
                View.VISIBLE
            } else View.GONE
        }
        val view: View = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.END
            addView(red)
            addView(preview, LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT,
            ).apply { topMargin = dp(8) })
        }
        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            else
                @Suppress("DEPRECATION") WindowManager.LayoutParams.TYPE_PHONE,
            // NE sme da uzme fokus: polje u koje pisemo mora da ga zadrzi.
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            android.graphics.PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.END
            x = dp(14)
            y = dp(14)
        }
        return runCatching { windows.addView(view, params) }
            .onSuccess {
                pill = view
                pillCounter = brojac
                pillToggle = prekidac
                pillPreview = preview
                updateToggle()
            }
            .onFailure { toast("Nema dozvolu za prikaz preko drugih aplikacija") }
            .isSuccess
    }

    /**
     * Klik na dugme dok snimanje traje.
     *
     * Prozor je `FLAG_NOT_FOCUSABLE`, pa dodir stize dugmetu a fokus ostaje u
     * polju u koje tekst treba da se upise. Bez toga bi klik na dugme oduzeo
     * fokus i prepoznat tekst ne bi imao gde da ode — ista zamka zbog koje
     * pilula uopste ima tu zastavicu.
     */
    private fun togglePravilno() {
        cfg.pravilno = !cfg.pravilno
        updateToggle()
        toast(if (cfg.pravilno) "Pravilno: uključeno" else "Pravilno: isključeno")
    }

    private fun updateToggle() {
        val dugme = pillToggle ?: return
        val ukljuceno = cfg.pravilno
        dugme.text = if (ukljuceno) "Aa" else "aa"
        dugme.setTextColor(if (ukljuceno) Color.parseColor("#10331C") else Color.WHITE)
        dugme.background = GradientDrawable().apply {
            cornerRadius = dp(22).toFloat()
            setColor(Color.parseColor(if (ukljuceno) "#FFFFFF" else "#33000000"))
            setStroke(dp(2), Color.parseColor("#66FFFFFF"))
        }
    }

    /**
     * U piluli su UVEK cifre; stanje se cita iz boje.
     *
     * Tekst „AI" je ranije gutao sat, pa se nije videlo ni koliko traje ni
     * koliko je ostalo — a bas to je jedini podatak koji pilula nosi.
     */
    fun osvezi(seconds: Int, busy: Boolean, polishing: Boolean) {
        val view = pillCounter ?: return
        val limit = granica()
        view.text = if (seconds >= 60) {
            "%d:%02d".format(seconds / 60, seconds % 60)
        } else {
            "%02d".format(minOf(seconds, limit))
        }
        // Model ima prednost nad prepoznavanjem, a oboje nad granicom snimanja:
        // cekanje na tudji odgovor je vaznije od toga koliko traje ovaj snimak.
        val color = when {
            polishing -> "#1565C0"                              // ceka model
            busy -> "#E08A00"                                   // prepoznaje
            // U neprekidnom rezimu nema granice od 30s, pa crveno upozorenje
            // nema sta da najavi.
            !cfg.longRecording && seconds >= cfg.redAfterSeconds -> "#C62828"
            else -> "#1C8F3D"                                   // snima
        }
        (view.background as GradientDrawable).setColor(Color.parseColor(color))
    }

    /** Tekst uzivo ispod brojaca (Gemini Live, kad je ukljucen pregled). */
    fun pregled(tekst: String) {
        pillPreview?.text = tekst.ifBlank { "Slušam…" }
    }

    fun sakrij() {
        pill?.let { runCatching { windows.removeView(it) } }
        pill = null
        pillCounter = null
        pillToggle = null
        pillPreview = null
    }

    private fun dp(value: Int) =
        (value * context.resources.displayMetrics.density).toInt()

    private fun toast(text: String) =
        Toast.makeText(context, text, Toast.LENGTH_LONG).show()
}
