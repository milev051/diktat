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
    private var nextTicket = 0
    private var expected = 0
    private val buffered = HashMap<Int, String>()
    private val pending = java.util.concurrent.atomic.AtomicInteger(0)
    private val formalParts = mutableListOf<String>()
    @Volatile private var polishing = false

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
        if (cfg.continuous) thread { segmentLoop() }
    }

    private fun stopRecording() {
        if (!isRecording) return
        isRecording = false
        handler.removeCallbacksAndMessages(null)
        busy = true
        updatePill(elapsed(), busy = true)

        if (cfg.continuous) {
            // Petlja sama pokupi ostatak iz reda i posalje rep; ovde se samo
            // trazi kraj, da se poslednji komadi ne izgube.
            recorder?.requestStop()
            return
        }

        val pcm = recorder?.stop() ?: ByteArray(0)
        recorder = null
        thread { recognizeAndDeliver(pcm, last = true) }
    }

    /**
     * Neprekidni rezim: sece na pauzama i salje delove dok snimanje tece
     * dalje. Segment se pusta iz memorije cim ode — inace bi dug diktat
     * nagomilao sve u baferu.
     */
    private fun segmentLoop() {
        val rec = recorder ?: return
        val detector = PauseDetector(pauseSeconds = cfg.pauseSeconds)
        val cutAfter = cfg.segmentAfterSeconds.toDouble()
        val hardCut = cfg.maxRequestSeconds.toDouble()
        var frames = java.io.ByteArrayOutputStream()
        var seconds = 0.0
        var bytesInSegment = 0

        while (true) {
            val chunk = rec.nextChunk() ?: break
            if (chunk.isEmpty()) continue
            frames.write(chunk)
            bytesInSegment += chunk.size
            val step = chunk.size / 2.0 / cfg.sampleRate
            seconds += step
            val paused = detector.feed(peakLevel(chunk), step)
            // Tvrdi rez postoji jer endpoint odbija zahteve duze od ~30s, a
            // neko moze da prica bez ijedne pauze.
            if (bytesInSegment > 0 && ((paused && seconds >= cutAfter) || seconds >= hardCut)) {
                ship(frames.toByteArray(), last = false)
                frames = java.io.ByteArrayOutputStream()
                bytesInSegment = 0
                seconds = 0.0
                detector.reset()
            }
        }

        val rest = rec.stop()
        recorder = null
        frames.write(rest)
        ship(frames.toByteArray(), last = true)
    }

    private fun ship(pcm: ByteArray, last: Boolean) {
        if (pcm.isEmpty()) {
            if (last) handler.post { finishSession() }
            return
        }
        val myTicket = nextTicket++
        pending.incrementAndGet()
        thread { recognizeAndDeliver(pcm, last = last, ticket = myTicket) }
    }

    private fun recognizeAndDeliver(pcm: ByteArray, last: Boolean, ticket: Int = 0) {
        var text = ""
        var problem: String? = null
        try {
            val sirov = WebStt.recognize(pcm, cfg)
            // Kad model sredjuje tekst, dobija ga nedirnutog: skracenice i
            // skidanje kvacica mu otezavaju citanje. Kad NE sredjuje (samo
            // skracuje ili dodaje emotikon), nasa pravila moraju da odrade svoje.
            text = if (formal() && cfg.polishTidy) sirov.trim()
            else TextPolish.apply(sirov, cfg)
        } catch (exc: Exception) {
            problem = exc.message ?: "greška u prepoznavanju"
            // Snimak se cuva da izgovoreno ne propadne.
            PendingStore(this).save(pcm)
            problem += " — snimak sačuvan za ponovni pokušaj"
        }
        handler.post { deliver(text, problem, ticket, last) }
    }

    /**
     * Ubacuje strogo po redosledu snimanja. Prepoznavanja teku paralelno i mogu
     * da se zavrse van reda — kratak drugi segment lako stigne pre dugog prvog.
     */
    private fun deliver(text: String, problem: String?, ticket: Int, last: Boolean) {
        buffered[ticket] = text
        if (problem != null) toast(problem)

        while (buffered.containsKey(expected)) {
            val ready = buffered.remove(expected)!!
            expected++
            pending.decrementAndGet()
            if (ready.isNotBlank()) {
                if (formal()) synchronized(formalParts) { formalParts.add(ready.trim()) }
                else insertNow(ready)
            }
        }
        if (last) {
            isRecording = false
            if (formal() && pending.get() == 0) startPolish()
            else handler.post { finishSession() }
        }
    }

    // Ukljucena obrada bez ijednog alata nema sta da posalje, pa se tekst upisuje
    // odmah kao i inace — bez toga bi diktat visio na praznom pozivu.
    private fun formal() = cfg.polish && Polish.available(cfg) && Polish.toolCount(cfg) > 0

    /** Ceo diktat ide modelu jednim pozivom, pa tek onda u polje. */
    private fun startPolish() {
        val tekst = synchronized(formalParts) {
            val t = formalParts.filter { it.isNotBlank() }.joinToString(" ").trim()
            formalParts.clear()
            t
        }
        if (tekst.isBlank()) {
            handler.post { finishSession() }
            return
        }
        polishing = true
        // Korisnik mora da zna da je otislo modelu i da se ceka odgovor.
        handler.post { updatePill(elapsed(), busy = true) }
        thread {
            val doteran = runCatching {
                val izlaz = Polish.polish(tekst, cfg).also { cfg.countPolish() }
                // Kad sredjivanje nije trazeno, model ga svejedno uradi cim
                // prepisuje recenice — skracivanje ih vraca pravopisno uredne.
                // Uputstvo to ne resava pouzdano, pa presudjuju nasa pravila.
                if (cfg.polishTidy) izlaz else TextPolish.applyBlocks(izlaz, cfg)
            }.getOrElse { exc ->
                // Nedoteran tekst je bolji nego nikakav — model je dodatak.
                handler.post { toast(exc.message ?: "doterivanje nije uspelo") }
                tekst
            }
            polishing = false
            val konacan = if (cfg.trailingSpace) "$doteran " else doteran
            insertNow(konacan)
            handler.post { finishSession() }
        }
    }

    private fun insertNow(text: String) {
        if (!InsertService.isRunning) {
            copyToClipboard(text)
            toast("Uključi Pristupačnost — tekst je u clipboard-u")
            return
        }
        // Upis ceka da se fokus vrati u polje, pa ne sme na glavnu nit.
        thread {
            val upisano = InsertService.insert(text, cfg.restoreClipboard)
            if (!upisano) handler.post { toast("Nema gde da upišem — tekst je u clipboard-u") }
        }
    }

    private fun finishSession() {
        if (isRecording || pending.get() > 0) return
        busy = false
        hidePill()
        stopSelf()
    }

    // ------------------------------------------------------- tajmer

    private fun elapsed() = ((System.currentTimeMillis() - startedAt) / 1000).toInt()

    private fun tick() {
        if (!isRecording) return
        val sec = elapsed()
        val limit = if (cfg.continuous) cfg.continuousMaxSeconds else cfg.maxSeconds
        if (sec >= limit) {
            // Bez granice bi slucajno pokrenut diktat mogao da snima satima.
            // Nastavak trazi nov pritisak.
            toast("Granica od ${limit}s — snimanje zaustavljeno")
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
        val limit = if (cfg.continuous) cfg.continuousMaxSeconds else cfg.maxSeconds
        if (polishing) {
            view.text = "AI"
            (view.background as GradientDrawable).setColor(Color.parseColor("#1565C0"))
            return
        }
        view.text = if (seconds >= 60) {
            "%d:%02d".format(seconds / 60, seconds % 60)
        } else {
            "%02d".format(minOf(seconds, limit))
        }
        val color = when {
            busy -> "#E08A00"                                   // obrada
            // U neprekidnom rezimu nema granice od 30s, pa crveno upozorenje
            // nema sta da najavi.
            !cfg.continuous && seconds >= cfg.redAfterSeconds -> "#C62828"
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
