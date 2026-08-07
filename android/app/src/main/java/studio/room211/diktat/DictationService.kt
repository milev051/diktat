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
    // Tajmer se pamti kao JEDAN objekat da bi mogao da se skine pojedinacno.
    // `::tick` bi svaki put napravio novi Runnable, pa `removeCallbacks` ne bi
    // imao sta da uhvati — otud je ranije stajalo removeCallbacksAndMessages.
    private val tickRunnable = Runnable { tick() }
    // Osigurac: ako obrada nikad ne javi da je gotova (nit umre, poziv visi
    // preko svog roka), pilula bi zauvek stajala i servis se ne bi ugasio.
    // Granica je iznad najduzeg poziva (provera snimka ceka do 180s).
    private val watchdogRunnable = Runnable {
        if (!isRecording) {
            pending.set(0)
            toast("Obrada nije stigla — prekidam")
            finishSession()
        }
    }
    private var recorder: Recorder? = null
    private var pill: TextView? = null
    private var windows: WindowManager? = null
    private var startedAt = 0L
    private var busy = false
    private var nextTicket = 0
    private var expected = 0
    // Uz tekst i sesiju cuva se i "da li je ovo poslednji segment": zastavica
    // mora da vazi za segment koji IZLAZI iz reda, ne za onaj koji stigne.
    private val buffered = HashMap<Int, Triple<String, Int, Boolean>>()
    private val pending = java.util.concurrent.atomic.AtomicInteger(0)
    // Sve sto ceka kraj diktata drzi se PO SESIJI: nov diktat sme da pocne dok
    // se prethodni obradjuje, pa bi u zajednickoj kanti dva diktata zavrsila u
    // jednom pozivu i upisala se spojena.
    private var sessionSeq = 0
    private var session = 0
    private val formalParts = sortedMapOf<Int, MutableList<String>>()
    private val pendingBy = HashMap<Int, Int>()
    // Zvuk segmenata za grupnu proveru; kljuc je ticket, da redosled ostane
    // hronoloski i kad se segmenti prepoznaju paralelno.
    private val audioParts = HashMap<Int, java.util.SortedMap<Int, ByteArray>>()
    private val audioSeconds = HashMap<Int, Double>()
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
        session = ++sessionSeq
        startedAt = System.currentTimeMillis()
        showPill()
        tick()
        if (cfg.continuous) thread { segmentLoop() }
    }

    private fun stopRecording() {
        if (!isRecording) return
        isRecording = false
        // Skida se SAMO tajmer. Ranije je ovde stajalo removeCallbacksAndMessages(null),
        // sto je brisalo i `deliver` poruke koje su radne niti vec postavile u red:
        // prepoznat segment bi nestao, `expected` bi zauvek stao, `pending` nikad
        // ne bi pao na nulu — pa bi pilula ostala narandzasta sa poslednjom cifrom
        // i servis se ne bi ugasio dok ga korisnik rucno ne prekine.
        handler.removeCallbacks(tickRunnable)
        handler.postDelayed(watchdogRunnable, 240_000)
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
        // Kroz `ship` zbog tiketa: raniji diktat u istom servisu je vec pomerio
        // `expected`, pa bi tvrdo zakucana nula zauvek cekala svoj red — pilula
        // bi ostala sa poslednjom cifrom dok se servis rucno ne prekine.
        ship(pcm, last = true)
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
        val mojaSesija = session
        keepAudio(mojaSesija, myTicket, pcm)
        pending.incrementAndGet()
        synchronized(formalParts) { pendingBy[mojaSesija] = (pendingBy[mojaSesija] ?: 0) + 1 }
        thread {
            recognizeAndDeliver(pcm, last = last, ticket = myTicket, sesija = mojaSesija)
        }
    }

    /**
     * Sacuvaj zvuk segmenta za grupnu proveru na kraju diktata.
     *
     * Ceo diktat ide modelu jednim pozivom: provera po segmentu je trosila
     * 6-9 poziva na jednu diktiranu poruku, a model je video krhotinu umesto
     * celine. Granica postoji jer neprekidan rezim ume da traje satima.
     */
    private fun keepAudio(sesija: Int, ticket: Int, pcm: ByteArray) {
        if (pcm.isEmpty() || !(Listen.enabled(cfg) || Groq.enabled(cfg))) return
        val sek = pcm.size / 2.0 / cfg.sampleRate
        synchronized(audioParts) {
            val moji = audioParts.getOrPut(sesija) { sortedMapOf() }
            if ((audioSeconds[sesija] ?: 0.0) + sek > cfg.audioCheckMaxSeconds) return
            moji[ticket] = pcm
            audioSeconds[sesija] = (audioSeconds[sesija] ?: 0.0) + sek
        }
    }

    private fun takeAudio(sesija: Int): List<ByteArray> = synchronized(audioParts) {
        val delovi = audioParts.remove(sesija)?.values?.toList() ?: emptyList()
        audioSeconds.remove(sesija)
        delovi
    }

    private fun recognizeAndDeliver(
        pcm: ByteArray,
        last: Boolean,
        ticket: Int = 0,
        sesija: Int = session,
    ) {
        var text = ""
        var problem: String? = null
        try {
            val sirov = WebStt.recognize(pcm, cfg)
            // Kad model sredjuje tekst, dobija ga nedirnutog: skracenice i
            // skidanje kvacica mu otezavaju citanje. Kad NE sredjuje (samo
            // skracuje ili dodaje emotikon), nasa pravila moraju da odrade svoje.
            // Kad model sredjuje tekst ili slusa snimak, dobija ga nedirnutog;
            // pravila se tada primenjuju na kraju, nad ispravljenim tekstom.
            text = if (batch() || (formal() && cfg.polishTidy)) sirov.trim()
            else TextPolish.apply(sirov, cfg)
        } catch (exc: Exception) {
            problem = exc.message ?: "greška u prepoznavanju"
            // Snimak se cuva da izgovoreno ne propadne.
            PendingStore(this).save(pcm)
            problem += " — snimak sačuvan za ponovni pokušaj"
        }
        handler.post { deliver(text, problem, ticket, last, sesija) }
    }

    /**
     * Ubacuje strogo po redosledu snimanja. Prepoznavanja teku paralelno i mogu
     * da se zavrse van reda — kratak drugi segment lako stigne pre dugog prvog.
     */
    private fun deliver(
        text: String,
        problem: String?,
        ticket: Int,
        last: Boolean,
        sesija: Int,
    ) {
        buffered[ticket] = Triple(text, sesija, last)
        if (problem != null) toast(problem)

        // Sesija ciji je POSLEDNJI segment upravo izasao iz reda. Rep je kratak
        // pa se cesto prepozna pre duzeg segmenta ispred sebe; ako bi se kraj
        // obradjivao po dolasku, obrada ne bi ni krenula — pilula bi ostala sa
        // poslednjom cifrom, a tekst se nikad ne bi upisao.
        var zavrsena: Int? = null

        while (buffered.containsKey(expected)) {
            val (ready, cija, jeKraj) = buffered.remove(expected)!!
            expected++
            pending.decrementAndGet()
            synchronized(formalParts) {
                pendingBy[cija] = maxOf(0, (pendingBy[cija] ?: 0) - 1)
            }
            if (ready.isNotBlank()) {
                if (deferred()) {
                    synchronized(formalParts) {
                        formalParts.getOrPut(cija) { mutableListOf() }.add(ready.trim())
                    }
                } else {
                    insertNow(ready)
                }
            }
            if (jeKraj) zavrsena = cija
        }
        // Osigurac po uzoru na macOS verziju: sesija kojoj je sve isporuceno a
        // vise ne snima mora da krene u obradu i onda kad zastavica "poslednji"
        // iz nekog razloga izostane. Bez toga jedan izgubljen kraj znaci pilulu
        // koja stoji zauvek.
        val zaobradu = synchronized(formalParts) {
            formalParts.keys.filter {
                it != (if (isRecording) session else -1) && (pendingBy[it] ?: 0) == 0
            }
        }

        zavrsena?.let { kraj ->
            // Zastavicu gasi SAMO sesija koja se zavrsava. Ranije ju je gasila
            // svaka: kad se prethodni diktat dovrsi dok nov vec snima, tudji
            // kraj bi oborio `isRecording` — tajmer bi stao, `finishSession`
            // bi prosao i ugasio servis usred snimanja.
            if (kraj == session) isRecording = false
            // Gleda se SESIJA, ne "da li mikrofon radi": nov diktat sme da pocne
            // dok se prethodni obradjuje, pa bi cekanje na miran mikrofon spojilo
            // dva diktata u jedan poziv.
            if (deferred() && (pendingBy[kraj] ?: 0) == 0) startPolish(kraj)
            else handler.post { finishSession() }
        }
        if (zavrsena == null && deferred()) {
            for (sesijaZaObradu in zaobradu) startPolish(sesijaZaObradu)
        }
    }

    // Ukljucena obrada bez ijednog alata nema sta da posalje, pa se tekst upisuje
    // odmah kao i inace — bez toga bi diktat visio na praznom pozivu.
    // Nema glavnog prekidaca: izabran alat sam po sebi znaci da se AI koristi.
    private fun formal() = Polish.available(cfg) && Polish.toolCount(cfg) > 0

    /** Ceka li se kraj diktata zbog provere snimka. */
    private fun batch() = Listen.enabled(cfg) || Groq.enabled(cfg)

    /** Ceka li se kraj diktata uopste — zbog modela ili zbog provere. */
    private fun deferred() = formal() || batch()

    /** Ceo diktat ide modelu jednim pozivom, pa tek onda u polje. */
    private fun startPolish(sesija: Int) {
        val tekst = synchronized(formalParts) {
            val moji = formalParts.remove(sesija) ?: mutableListOf()
            pendingBy.remove(sesija)
            moji.filter { it.isNotBlank() }.joinToString(" ").trim()
        }
        if (tekst.isBlank()) {
            // Otkazan ili prazan diktat: zvuk mora da ode, inace bi usao u
            // sledecu proveru i model bi "cuo" prosli diktat.
            takeAudio(sesija)
            handler.post { finishSession() }
            return
        }
        polishing = true
        // Korisnik mora da zna da je otislo modelu i da se ceka odgovor.
        handler.post { updatePill(elapsed(), busy = true) }
        thread {
            var polazni = tekst
            // Ako je model slusao snimak, tekst vec ima interpunkciju i kvacice
            // — sledeci poziv tada nema sta da sredjuje.
            var sredjeno = false
            if (batch()) {
                val delovi = takeAudio(sesija)
                if (delovi.isNotEmpty()) {
                    runCatching {
                        if (Groq.enabled(cfg)) {
                            // Groq ima prednost da se isti audio ne šalje i Gemini-ju.
                            Groq.check(delovi, tekst, cfg).also { cfg.countPolish(); cfg.countPolish() }
                        } else {
                            Listen.check(delovi, tekst, cfg).also { cfg.countPolish() }
                        }
                    }
                        .onSuccess { polazni = it; sredjeno = true }
                }
            }
            if (!formal()) {
                // Tekst je cekao proveru pa je jos sirov — pravila tek sada.
                val konacan = TextPolish.applyBlocks(polazni, cfg)
                polishing = false
                insertNow(if (cfg.trailingSpace) "$konacan " else konacan)
                handler.post { finishSession() }
                return@thread
            }
            val doteran = runCatching {
                var izlaz = Polish.polish(polazni, cfg, sredjeno)
                if (izlaz !== polazni) cfg.countPolish()
                // Kad sredjivanje nije trazeno, model ga svejedno uradi cim
                // prepisuje recenice — skracivanje ih vraca pravopisno uredne.
                // Uputstvo to ne resava pouzdano, pa presudjuju nasa pravila.
                // Uz sredjivanje ostaju bar skracenice: tekst je modelu isao
                // nedirnut, pa bi inace potpuno izostale.
                if (cfg.polishTidy) TextPolish.afterModel(izlaz, cfg)
                else TextPolish.applyBlocks(izlaz, cfg)
            }.getOrElse { exc ->
                // Nedoteran tekst je bolji nego nikakav — model je dodatak.
                handler.post { toast(exc.message ?: "doterivanje nije uspelo") }
                polazni
            }
            polishing = false
            // Uz tacke ide nov red umesto razmaka: sledeci diktat tako pocinje
            // svoju tacku umesto da se nastavi na prethodnu.
            val konacan = if (cfg.polishBullets) doteran.trimEnd() + "\n" else "$doteran "
            insertNow(konacan)
            handler.post { finishSession() }
        }
    }

    private fun insertNow(text: String) {
        // Tekst i dalje zavrsava u clipboard-u kad upis ne prodje — izgubiti ga
        // je gore. Poruka preko ekrana se ne prikazuje: pojavljivala se posle
        // svakog diktata i samo smetala.
        if (!InsertService.isRunning) {
            copyToClipboard(text)
            return
        }
        // Upis ceka da se fokus vrati u polje, pa ne sme na glavnu nit.
        thread { InsertService.insert(text, cfg.restoreClipboard) }
    }

    private fun finishSession() {
        if (isRecording || pending.get() > 0) return
        handler.removeCallbacks(watchdogRunnable)
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
        handler.postDelayed(tickRunnable, 250)
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

    /**
     * U piluli su UVEK cifre; stanje se cita iz boje.
     *
     * Tekst „AI" je ranije gutao sat, pa se nije videlo ni koliko traje ni
     * koliko je ostalo — a bas to je jedini podatak koji pilula nosi.
     */
    private fun updatePill(seconds: Int, busy: Boolean) {
        val view = pill ?: return
        val limit = if (cfg.continuous) cfg.continuousMaxSeconds else cfg.maxSeconds
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
        handler.removeCallbacks(tickRunnable)
        handler.removeCallbacks(watchdogRunnable)
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
