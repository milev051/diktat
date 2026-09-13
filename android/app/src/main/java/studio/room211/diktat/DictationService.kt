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
import android.view.View
import android.widget.LinearLayout
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
        // OpenAI prima ceo uobičajeni diktat jednim pozivom. Tek veoma dug
        // snimak se deli na petominutne komade da WAV i radna memorija ostanu
        // bezbedno ispod granice od 25 MB.
        private const val OPENAI_CHUNK_SECONDS = 5 * 60.0

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
    // Granica je iznad najdužeg transkripcionog poziva (OpenAI čeka do 180 s).
    private val watchdogRunnable = Runnable {
        if (!isRecording) {
            pending.set(0)
            toast("Obrada nije stigla — prekidam")
            finishSession()
        }
    }
    private var recorder: Recorder? = null
    private var pill: View? = null
    private var pillCounter: TextView? = null
    private var pillToggle: TextView? = null
    private var pillPreview: TextView? = null
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
    // OpenAI se ne poziva dok snimanje traje. U neprekidnom rezimu gotovi
    // segmenti idu na disk, pa telefon ne gomila sat vremena PCM-a u RAM-u;
    // svi se salju tek kad korisnik pritisne Stop.
    private val openAiParts = HashMap<Int, MutableList<java.io.File>>()
    @Volatile private var polishing = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        cfg = Config(this)
        windows = getSystemService(WindowManager::class.java)
        startForeground(NOTIFICATION_ID, buildNotification())
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_TOGGLE -> if (isRecording) stopRecording() else startRecording()
        }
        return START_NOT_STICKY
    }

    // ------------------------------------------------------------------

    private fun startRecording() {
        cfg = Config(this)
        if (cfg.transcriptionProvider == "openai" && cfg.openAiApiKey.isBlank()) {
            toast("OpenAI API ključ nije podešen — unesi ga u aplikaciji")
            stopSelf()
            return
        }
        if (GeminiStt.enabled(cfg) && cfg.polishApiKey.isBlank()) {
            toast("Gemini API ključ nije podešen — unesi ga u aplikaciji")
            stopSelf()
            return
        }
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
        if (cfg.longRecording) {
            if (GeminiStt.enabled(cfg)) thread { geminiLiveLoop() } else thread { segmentLoop() }
        }
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

        if (cfg.longRecording) {
            // Petlja sama pokupi ostatak iz reda i posalje rep; ovde se samo
            // trazi kraj, da se poslednji komadi ne izgube.
            recorder?.requestStop()
            return
        }

        val pcm = recorder?.stop() ?: ByteArray(0)
        recorder = null
        cfg.addRecordedSeconds(pcm.size / 2.0 / cfg.sampleRate)
        // Kroz `ship` zbog tiketa: raniji diktat u istom servisu je vec pomerio
        // `expected`, pa bi tvrdo zakucana nula zauvek cekala svoj red — pilula
        // bi ostala sa poslednjom cifrom dok se servis rucno ne prekine.
        ship(pcm, last = true)
    }

    /**
     * Neprekidni režim: Google seče na pauzama i šalje delove tokom snimanja.
     * OpenAI ignoriše pauze i čuva veće komade koje šalje tek posle Stop-a.
     * Segment se pušta iz memorije čim ode na mrežu ili u privremeni fajl.
     */
    private fun segmentLoop() {
        val rec = recorder ?: return
        val openAi = cfg.transcriptionProvider == "openai"
        val detector = PauseDetector(pauseSeconds = cfg.pauseSeconds)
        val cutAfter = cfg.segmentAfterSeconds.toDouble()
        val hardCut = if (openAi) OPENAI_CHUNK_SECONDS else cfg.maxRequestSeconds.toDouble()
        var frames = java.io.ByteArrayOutputStream()
        var seconds = 0.0
        var bytesInSegment = 0
        var totalBytes = 0L

        while (true) {
            val chunk = rec.nextChunk() ?: break
            if (chunk.isEmpty()) continue
            frames.write(chunk)
            totalBytes += chunk.size
            bytesInSegment += chunk.size
            val step = chunk.size / 2.0 / cfg.sampleRate
            seconds += step
            // Google-ov endpoint traži kratke delove, pa koristi pauze. OpenAI
            // dobija ceo uobičajeni diktat u jednom zahtevu: ranije je svaka
            // pauza pravila novi API poziv i posle Stop-a nepotrebno množila
            // vreme čekanja.
            val paused = !openAi && detector.feed(peakLevel(chunk), step)
            // Google ima tvrdu granicu od oko 30 s; OpenAI se deli tek na pet
            // minuta zbog veličine fajla i potrošnje memorije.
            if (bytesInSegment > 0 &&
                ((!openAi && paused && seconds >= cutAfter) || seconds >= hardCut)
            ) {
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
        totalBytes += rest.size
        cfg.addRecordedSeconds(totalBytes / 2.0 / cfg.sampleRate)
        ship(frames.toByteArray(), last = true)
    }

    /**
     * Gemini Live: zvuk ide na mrezu DOK snimanje traje.
     *
     * Izmereno na 64.7s zvuka: slanje posle Stop-a ostavlja 15.6s cekanja,
     * slanje u toku 0.0s — server stize u realnom vremenu, pa je prepis gotov
     * u trenutku kad pustis taster. Ceo diktat je jedna sesija i jedan tiket:
     * model tako vidi celinu umesto krhotina odsecenih na pauzama.
     *
     * Komadi sa mikrofona se citaju samo jednom, pa drugi pokusaj nema sta da
     * posalje: neuspeo Live diktat propada. Kopija se namerno nigde ne pise —
     * zvuk ne sme da ostane na uredjaju posle diktata.
     */
    private fun geminiLiveLoop() {
        val rec = recorder ?: return
        val myTicket = nextTicket++
        val mojaSesija = session
        pending.incrementAndGet()
        synchronized(formalParts) { pendingBy[mojaSesija] = (pendingBy[mojaSesija] ?: 0) + 1 }

        var totalBytes = 0L
        var tekst = ""
        var problem: String? = null

        try {
            var zavrseno = false
            val preview: ((String) -> Unit)? = if (cfg.geminiLivePreview) { raw ->
                val text = GeminiStt.postProcess(raw, cfg).trim().takeLast(450)
                handler.post {
                    if (session == mojaSesija) pillPreview?.text = text.ifBlank { "Slušam…" }
                }
            } else null
            val sirov = GeminiStt.recognizeStream(cfg, onUpdate = preview) {
                val chunk = rec.nextChunk()
                when {
                    chunk != null -> {
                        totalBytes += chunk.size
                        chunk
                    }
                    !zavrseno -> {
                        // Mikrofon je stao; ostatak iz reda mora jos da prodje.
                        zavrseno = true
                        val rest = rec.stop()
                        recorder = null
                        if (rest.isNotEmpty()) {
                            totalBytes += rest.size
                            rest
                        } else {
                            null
                        }
                    }
                    else -> null
                }
            }
            tekst = GeminiStt.postProcess(sirov, cfg)
            if (tekst.isBlank()) problem = "Ništa nije prepoznato"
        } catch (e: Exception) {
            problem = e.message ?: "Gemini Transcribe Live nije uspeo"
        } finally {
            if (recorder === rec) {
                runCatching { rec.stop() }
                recorder = null
            }
        }

        cfg.addRecordedSeconds(totalBytes / 2.0 / cfg.sampleRate)
        val poruka = problem
        handler.post {
            deliver(tekst, poruka, myTicket, last = true, sesija = mojaSesija)
        }
    }

    private fun ship(pcm: ByteArray, last: Boolean) {
        if (cfg.transcriptionProvider == "openai") {
            shipOpenAiPart(pcm, last)
            return
        }
        if (pcm.isEmpty()) {
            if (!last) return
            // U neprekidnom režimu korisnik često pritisne Stop tokom tišine,
            // pa je završni rep prazan iako je raniji segment već poslat.
            // I prazan rep mora da bude tiket: bez njega prethodni segment
            // nema oznaku „poslednji“, pa se tekst može ispisati, ali pilula
            // ostane narandžasta i servis nikad ne završi.
            val myTicket = nextTicket++
            val mojaSesija = session
            pending.incrementAndGet()
            synchronized(formalParts) {
                pendingBy[mojaSesija] = (pendingBy[mojaSesija] ?: 0) + 1
            }
            handler.post {
                deliver("", null, myTicket, last = true, sesija = mojaSesija)
            }
            return
        }
        val myTicket = nextTicket++
        val mojaSesija = session
        pending.incrementAndGet()
        synchronized(formalParts) { pendingBy[mojaSesija] = (pendingBy[mojaSesija] ?: 0) + 1 }
        thread {
            recognizeAndDeliver(pcm, last = last, ticket = myTicket, sesija = mojaSesija)
        }
    }

    /**
     * Sacuva jedan zavrseni segment, ali ga ne salje dok korisnik ne pritisne
     * Stop. Za obican rezim lista ima jedan fajl; za neprekidni rezim svaki
     * rez na pauzi ostaje zaseban upload posle kraja snimanja.
     */
    private fun shipOpenAiPart(pcm: ByteArray, last: Boolean) {
        val mojaSesija = session
        if (pcm.isNotEmpty()) {
            val file = java.io.File(cacheDir, "openai-${mojaSesija}-${System.nanoTime()}.pcm")
            runCatching {
                file.writeBytes(pcm)
                synchronized(openAiParts) {
                    openAiParts.getOrPut(mojaSesija) { mutableListOf() }.add(file)
                }
            }.onFailure {
                file.delete()
                handler.post { toast("Ne mogu da sačuvam OpenAI audio snimak") }
            }
        }
        if (!last) return

        val files = synchronized(openAiParts) {
            openAiParts.remove(mojaSesija)?.toList() ?: emptyList()
        }
        if (files.isEmpty()) {
            handler.post {
                toast("Snimak je prazan ili prekratak")
                finishSession()
            }
            return
        }
        val myTicket = nextTicket++
        pending.incrementAndGet()
        synchronized(formalParts) { pendingBy[mojaSesija] = 1 }
        thread {
            recognizeOpenAiAndDeliver(files, ticket = myTicket, sesija = mojaSesija)
        }
    }

    private fun recognizeOpenAiAndDeliver(
        files: List<java.io.File>,
        ticket: Int,
        sesija: Int,
    ) {
        val pieces = mutableListOf<String>()
        var problem: String? = null
        try {
            for (file in files) {
                val pcm = runCatching { file.readBytes() }.getOrElse {
                    throw OpenAiTranscription.OpenAiException("Ne mogu da pročitam audio snimak.")
                }
                try {
                    val piece = OpenAiTranscription.postProcess(
                        OpenAiTranscription.recognize(pcm, cfg), cfg,
                    ).trim()
                    if (piece.isNotBlank()) pieces += piece
                } catch (exc: Exception) {
                    // Ako je prethodni segment uspeo, njega ne bacamo: korisnik
                    // dobija delimican tekst i jasan problem. Ako nije uspeo
                    // nijedan, deliver prikazuje samo grešku.
                    problem = exc.message ?: "OpenAI transkripcija nije uspela"
                    break
                }
            }
        } catch (exc: Exception) {
            problem = exc.message ?: "OpenAI transkripcija nije uspela"
        }
        files.forEach { it.delete() }
        val joined = pieces.joinToString(" ").trim()
        val text = if (joined.isNotBlank() && cfg.trailingSpace) "$joined " else joined
        handler.post { deliver(text, problem, ticket, last = true, sesija = sesija) }
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
            val sirov = when {
                cfg.transcriptionProvider == "openai" -> OpenAiTranscription.recognize(pcm, cfg)
                GeminiStt.enabled(cfg) -> GeminiStt.recognize(pcm, cfg)
                else -> WebStt.recognize(pcm, cfg)
            }
            // Kad model sredjuje tekst, dobija ga nedirnutog: skracenice i
            // skidanje kvacica mu otezavaju citanje. Kad NE sredjuje (samo
            // skracuje ili dodaje emotikon), nasa pravila moraju da odrade svoje.
            // Kad model sredjuje tekst, dobija ga nedirnutog; pravila se tada
            // primenjuju na kraju, nad ispravljenim tekstom.
            text = if (cfg.transcriptionProvider == "openai") {
                OpenAiTranscription.postProcess(sirov, cfg)
            } else if (GeminiStt.enabled(cfg)) {
                GeminiStt.postProcess(sirov, cfg)
            } else if (formal() && cfg.polishTidy) sirov.trim()
            else TextPolish.apply(sirov, cfg)
        } catch (exc: Exception) {
            problem = exc.message ?: "greška u prepoznavanju"
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

    /** Ceka li se kraj diktata zbog tekstualne obrade. */
    private fun deferred() = formal()

    /** Ceo diktat ide modelu jednim pozivom, pa tek onda u polje. */
    private fun startPolish(sesija: Int) {
        val tekst = synchronized(formalParts) {
            val moji = formalParts.remove(sesija) ?: mutableListOf()
            pendingBy.remove(sesija)
            moji.filter { it.isNotBlank() }.joinToString(" ").trim()
        }
        if (tekst.isBlank()) {
            handler.post { finishSession() }
            return
        }
        polishing = true
        // Korisnik mora da zna da je otislo modelu i da se ceka odgovor.
        handler.post { updatePill(elapsed(), busy = true) }
        thread {
            val polazni = tekst
            val doteran = runCatching {
                val izlaz = Polish.polish(polazni, cfg)
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
            // Uz tacke ide nov red, a uz podelu na pasuse dva nova reda:
            // sledeci diktat se tako ne lepi za poslednji pasus.
            val konacan = when {
                cfg.polishBullets -> doteran.trimEnd() + "\n"
                cfg.polishParagraphs -> doteran.trimEnd() + "\n\n"
                else -> "$doteran "
            }
            insertNow(konacan)
            handler.post { finishSession() }
        }
    }

    private fun insertNow(text: String) {
        cfg.addHistory(text)
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

    /**
     * Koliko sme da traje JEDAN pritisak.
     *
     * Racunica je bila prepisana na dva mesta, u tajmeru i u piluli, pa je
     * pilula mogla da pokazuje jednu granicu dok se snimanje seklo na drugoj.
     * Sada je na jednom mestu.
     */
    private fun limitSeconds(): Int = Granica.sekundi(
        provider = cfg.transcriptionProvider,
        dugoSnimanje = cfg.longRecording,
        geminiLive = cfg.geminiLiveMaxSeconds,
        openAi = cfg.openAiMaxSeconds,
        neprekidno = cfg.continuousMaxSeconds,
        kratko = cfg.maxSeconds,
    )

    private fun tick() {
        if (!isRecording) return
        val sec = elapsed()
        val limit = limitSeconds()
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

        val brojac = TextView(this).apply {
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
        val prekidac = TextView(this).apply {
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 17f)
            gravity = Gravity.CENTER
            // Sirok dodir: prst ide na dugme dok govoris, ne gledajuci.
            minWidth = dp(46)
            minHeight = dp(44)
            setPadding(dp(12), dp(10), dp(12), dp(10))
            isClickable = true
            setOnClickListener { togglePravilno() }
        }

        val red = LinearLayout(this).apply {
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

        val preview = TextView(this).apply {
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 16f)
            setTextColor(Color.WHITE)
            setPadding(dp(14), dp(12), dp(14), dp(12))
            maxWidth = resources.displayMetrics.widthPixels - dp(28)
            maxLines = 6
            text = "Slušam…"
            background = GradientDrawable().apply {
                cornerRadius = dp(16).toFloat()
                setColor(Color.parseColor("#E61F2933"))
            }
            visibility = if (GeminiStt.enabled(cfg) && cfg.geminiLivePreview) {
                View.VISIBLE
            } else View.GONE
        }
        val view: View = LinearLayout(this).apply {
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
        runCatching { windows?.addView(view, params) }
            .onSuccess {
                pill = view
                pillCounter = brojac
                pillToggle = prekidac
                pillPreview = preview
                updateToggle()
            }
            .onFailure { toast("Nema dozvolu za prikaz preko drugih aplikacija") }
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
    private fun updatePill(seconds: Int, busy: Boolean) {
        val view = pillCounter ?: return
        val limit = limitSeconds()
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

    private fun hidePill() {
        pill?.let { runCatching { windows?.removeView(it) } }
        pill = null
        pillCounter = null
        pillToggle = null
        pillPreview = null
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
