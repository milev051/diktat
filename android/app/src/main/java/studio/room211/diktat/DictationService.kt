package studio.room211.diktat

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.TypedValue
import android.view.Gravity
import android.view.WindowManager
import android.widget.TextView
import android.widget.Toast
import kotlin.concurrent.thread

/**
 * Snimanje pokrenuto bocnim tasterom.
 *
 * Prozorcic sa tajmerom je FLAG_NOT_FOCUSABLE — polje u koje tekst treba da
 * udje mora da zadrzi fokus, inace nema gde da se upise. Isti problem kao HUD
 * u macOS verziji.
 *
 * Bocni taster salje samo "pokreni", nema dogadjaj za pustanje, pa radi kao
 * prekidac: prvi pritisak pocinje, drugi zavrsava. Samo staje na maxSeconds.
 */
class DictationService : Service() {

    companion object {
        const val ACTION_TOGGLE = "studio.room211.diktat.TOGGLE"
        private const val CHANNEL = "diktat"
        private const val NOTIFICATION_ID = 1

        @Volatile
        var isRecording = false
            private set
    }

    private lateinit var cfg: Config
    private val handler = Handler(Looper.getMainLooper())
    private var recorder: Recorder? = null
    private var pill: TextView? = null
    private var windows: WindowManager? = null
    private var startedAt = 0L
    private var busy = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        cfg = Config(this)
        windows = getSystemService(WindowManager::class.java)
        startForeground(NOTIFICATION_ID, buildNotification())
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_TOGGLE) {
            if (isRecording) stopRecording() else startRecording()
        }
        return START_NOT_STICKY
    }

    // ------------------------------------------------------------------

    private fun startRecording() {
        cfg = Config(this)
        // Bez polja u koje bi tekst usao snimanje nema smisla — inace se
        // diktat pokrene i sa pocetnog ekrana, pa zavrsi u praznom.
        if (cfg.requireInputField && InsertService.isRunning &&
            !InsertService.hasInputField()
        ) {
            toast("Nema polja za unos — klikni u polje pa probaj ponovo")
            stopSelf()
            return
        }
        try {
            recorder = Recorder(cfg.sampleRate).also { it.start() }
        } catch (exc: Exception) {
            toast("Mikrofon: ${exc.message}")
            stopSelf()
            return
        }
        isRecording = true
        startedAt = System.currentTimeMillis()
        showPill()
        tick()
    }

    private fun stopRecording() {
        if (!isRecording) return
        isRecording = false
        handler.removeCallbacksAndMessages(null)
        val pcm = recorder?.stop() ?: ByteArray(0)
        recorder = null
        busy = true
        updatePill(elapsed(), busy = true)

        thread {
            var text = ""
            var problem: String? = null
            try {
                text = TextPolish.apply(WebStt.recognize(pcm, cfg), cfg)
            } catch (exc: Exception) {
                problem = exc.message ?: "greška u prepoznavanju"
            }
            handler.post { deliver(text, problem) }
        }
    }

    private fun deliver(text: String, problem: String?) {
        busy = false
        hidePill()
        if (problem != null) {
            toast(problem)
            stopSelf()
            return
        }
        if (text.isBlank()) {
            toast("Ništa nije prepoznato")
            stopSelf()
            return
        }
        if (!InsertService.isRunning) {
            // Nema ko da upise — clipboard je jedini nacin da tekst ne propadne.
            copyToClipboard(text)
            toast("Uključi Pristupačnost — tekst je u clipboard-u")
            stopSelf()
            return
        }

        // Upis ceka da se fokus vrati u polje, pa ne sme na glavnu nit.
        thread {
            val upisano = InsertService.insert(text, cfg.restoreClipboard)
            handler.post {
                if (!upisano) toast("Nema gde da upišem — tekst je u clipboard-u")
                stopSelf()
            }
        }
    }

    // ------------------------------------------------------- tajmer

    private fun elapsed() = ((System.currentTimeMillis() - startedAt) / 1000).toInt()

    private fun tick() {
        if (!isRecording) return
        val sec = elapsed()
        if (sec >= cfg.maxSeconds) {
            stopRecording()
            return
        }
        updatePill(sec, busy = false)
        handler.postDelayed(::tick, 250)
    }

    // -------------------------------------------------------- prozor

    private fun showPill() {
        if (pill != null) return
        val view = TextView(this).apply {
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
        runCatching { windows?.addView(view, params) }
            .onSuccess { pill = view }
            .onFailure { toast("Nema dozvolu za prikaz preko drugih aplikacija") }
    }

    private fun updatePill(seconds: Int, busy: Boolean) {
        val view = pill ?: return
        view.text = "%02d".format(minOf(seconds, cfg.maxSeconds))
        val color = when {
            busy -> "#E08A00"                                   // obrada
            seconds >= cfg.redAfterSeconds -> "#C62828"         // pred kraj
            else -> "#1C8F3D"                                   // snima
        }
        (view.background as GradientDrawable).setColor(Color.parseColor(color))
    }

    private fun hidePill() {
        pill?.let { runCatching { windows?.removeView(it) } }
        pill = null
    }

    override fun onDestroy() {
        handler.removeCallbacksAndMessages(null)
        recorder?.stop()
        hidePill()
        isRecording = false
        super.onDestroy()
    }

    // ------------------------------------------------------- sitnice

    private fun dp(value: Int) =
        (value * resources.displayMetrics.density).toInt()

    private fun toast(text: String) =
        Toast.makeText(this, text, Toast.LENGTH_LONG).show()

    private fun copyToClipboard(text: String) {
        val cm = getSystemService(android.content.ClipboardManager::class.java)
        cm?.setPrimaryClip(android.content.ClipData.newPlainText("diktat", text))
    }

    private fun buildNotification(): Notification {
        val manager = getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL, "Diktat", NotificationManager.IMPORTANCE_LOW)
            )
        }
        return Notification.Builder(this, CHANNEL)
            .setContentTitle("Diktat")
            .setContentText("Snimanje govora")
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .build()
    }
}
