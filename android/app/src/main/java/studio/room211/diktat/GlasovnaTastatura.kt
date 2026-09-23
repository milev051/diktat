package studio.room211.diktat

import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.inputmethodservice.InputMethodService
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.inputmethod.EditorInfo
import android.widget.LinearLayout
import android.widget.TextView
import kotlin.concurrent.thread

/**
 * Glasovna tastatura, isto kao Google Voice Typing.
 *
 * Samsung tastatura u „Voice input" nudi GLASOVNE TASTATURE: tastature sa
 * podtipom `imeSubtypeMode="voice"` i `isAuxiliary="true"` (tako je prijavljen
 * i Google-ov `VoiceInputMethodService`, provereno preko `dumpsys input_method`
 * 22.09.2026). `SttService` (RecognitionService) je druga vrsta komponente i u
 * tu listu ne ulazi, pa je mikrofon na tastaturi i dalje zvao Google, koji bez
 * Google aplikacije ne radi.
 *
 * Tok: tastatura se prebaci na nas, mi odmah pocnemo da slusamo, dodir na
 * panel zavrsi, tekst ide pravo u polje (`commitText`, bez Pristupacnosti), a
 * tastatura se vrati na prethodnu.
 */
class GlasovnaTastatura : InputMethodService() {

    private lateinit var cfg: Config
    private val handler = Handler(Looper.getMainLooper())
    private var recorder: Recorder? = null
    private var pocetak = 0L
    private var obradjuje = false
    private var natpis: TextView? = null
    private var brojac: TextView? = null
    private val tik = Runnable { osvezi() }

    override fun onCreate() {
        super.onCreate()
        cfg = Config(this)
    }

    override fun onCreateInputView(): View {
        val tamno = Color.parseColor("#1F2933")
        val brojacView = TextView(this).apply {
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 22f)
            setTextColor(Color.WHITE)
            gravity = Gravity.CENTER
            setPadding(dp(22), dp(10), dp(22), dp(10))
            background = GradientDrawable().apply {
                cornerRadius = dp(24).toFloat()
                setColor(Color.parseColor("#1C8F3D"))
            }
            text = "00"
        }
        val natpisView = TextView(this).apply {
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 15f)
            setTextColor(Color.parseColor("#CCFFFFFF"))
            gravity = Gravity.CENTER
            text = "Slušam… dodirni za kraj"
        }
        val otkazi = TextView(this).apply {
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
            setTextColor(Color.parseColor("#99FFFFFF"))
            gravity = Gravity.CENTER
            setPadding(dp(16), dp(12), dp(16), dp(12))
            text = "Otkaži"
            setOnClickListener { otkazi() }
        }
        natpis = natpisView
        brojac = brojacView
        return LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setBackgroundColor(tamno)
            setPadding(dp(16), dp(20), dp(16), dp(8))
            minimumHeight = dp(220)
            // Ceo panel je dugme: prst ide na tastaturu ne gledajuci.
            isClickable = true
            setOnClickListener { zavrsi() }
            addView(brojacView)
            addView(natpisView, LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT,
            ).apply { topMargin = dp(14) })
            addView(otkazi, LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT,
            ).apply { topMargin = dp(10) })
        }
    }

    override fun onStartInputView(info: EditorInfo?, restarting: Boolean) {
        super.onStartInputView(info, restarting)
        cfg = Config(this)
        if (recorder == null && !obradjuje) pocni()
    }

    override fun onFinishInputView(finishingInput: Boolean) {
        // Korisnik je otisao iz polja: snimak nema gde da ode.
        if (recorder != null) odbaci()
        super.onFinishInputView(finishingInput)
    }

    override fun onDestroy() {
        odbaci()
        super.onDestroy()
    }

    private fun pocni() {
        try {
            recorder = Recorder(cfg.sampleRate).also { it.start() }
        } catch (exc: Exception) {
            natpis?.text = "Mikrofon nije dostupan"
            return
        }
        pocetak = System.currentTimeMillis()
        natpis?.text = "Slušam… dodirni za kraj"
        boja("#1C8F3D")
        handler.post(tik)
    }

    private fun osvezi() {
        if (recorder == null) return
        val sekundi = ((System.currentTimeMillis() - pocetak) / 1000).toInt()
        brojac?.text = if (sekundi >= 60) "%d:%02d".format(sekundi / 60, sekundi % 60)
        else "%02d".format(sekundi)
        // Ista granica kao kod bocnog tastera: zaboravljen mikrofon ne sme da snima satima.
        if (sekundi >= Prepoznaj.granica(cfg)) {
            zavrsi()
            return
        }
        handler.postDelayed(tik, 250)
    }

    private fun zavrsi() {
        if (obradjuje) return
        // Posle greske dodir samo vraca tastaturu, da korisnik ne ostane zaglavljen.
        val snimac = recorder ?: return vratiTastaturu()
        handler.removeCallbacks(tik)
        recorder = null
        val pcm = snimac.stop()
        cfg.addRecordedSeconds(pcm.size / 2.0 / cfg.sampleRate)
        obradjuje = true
        natpis?.text = "Obrađujem…"
        boja("#E08A00")
        thread {
            val tekst = runCatching { Prepoznaj.tekst(pcm, cfg) }
            handler.post {
                obradjuje = false
                tekst.onSuccess { t ->
                    if (t.isNotBlank()) {
                        currentInputConnection?.commitText(t.trim() + " ", 1)
                        cfg.addHistory(t.trim())
                    }
                    vratiTastaturu()
                }.onFailure { greska ->
                    natpis?.text = "Nije uspelo: ${greska.message ?: "greška"}"
                    boja("#C62828")
                }
            }
        }
    }

    private fun otkazi() {
        odbaci()
        vratiTastaturu()
    }

    private fun odbaci() {
        handler.removeCallbacks(tik)
        recorder?.stop()?.let { cfg.addRecordedSeconds(it.size / 2.0 / cfg.sampleRate) }
        recorder = null
    }

    private fun vratiTastaturu() {
        val vraceno = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            switchToPreviousInputMethod()
        } else false
        if (!vraceno) requestHideSelf(0)
    }

    private fun boja(hex: String) {
        (brojac?.background as? GradientDrawable)?.setColor(Color.parseColor(hex))
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
}
