package studio.room211.diktat

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
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
        // Isti prag tisine kao rezerva.PRAG_TISINE na Macu.
        private const val PRAG_GLASA = 0.03
        const val ACTION_TOGGLE = "studio.room211.diktat.TOGGLE"
        const val ACTION_START = "studio.room211.diktat.START"
        const val ACTION_STOP = "studio.room211.diktat.STOP"
        private const val CHANNEL = "diktat"
        private const val NOTIFICATION_ID = 1
        // OpenAI prima ceo uobičajeni diktat jednim pozivom. Tek veoma dug
        // snimak se deli na petominutne komade da WAV i radna memorija ostanu
        // bezbedno ispod granice od 25 MB.
        private const val OPENAI_CHUNK_SECONDS = 5 * 60.0

        @Volatile
        var isActive = false
            private set

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
    private lateinit var pilula: Pilula
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
    // Kasnjenje prepisa za okvir: kad je poslednji glas cut i kad je stigao tekst.
    @Volatile private var glasAt = 0L
    @Volatile private var tekstAt = 0L
    private var prepis = LivePrenos()
    private val liveVeza = java.util.concurrent.atomic.AtomicReference<WSock?>(null)
    private val sesijaZavrsena = java.util.concurrent.atomic.AtomicBoolean(false)
    @Volatile private var prijemZaustavljen = false
    private var poslednjeCuvanje = 0L
    private val salvageRunnable = Runnable { prisilnoZavrsi() }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        isActive = true
        cfg = Config(this)
        pilula = Pilula(this, cfg, ::limitSeconds) { zaustaviIliPrekini() }
        // Isto pravilo kao na Macu: glas se cuje (poslednjih 1 s), a novog
        // teksta nema vise od 4 s. Google salje tek posle pauze, pa glasAt
        // ostaje 0 i okvir ne pozuti.
        pilula.proveraKasnjenja = {
            val now = android.os.SystemClock.elapsedRealtime()
            glasAt > 0 && now - glasAt < 1000 && now - tekstAt > 4000
        }
        startForeground(NOTIFICATION_ID, buildNotification())
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_TOGGLE -> if (isRecording) stopRecording() else startRecording()
            ACTION_START -> if (!isRecording) startRecording()
            ACTION_STOP -> if (isRecording) stopRecording()
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
        prepis = LivePrenos()
        sesijaZavrsena.set(false)
        prijemZaustavljen = false
        liveVeza.set(null)
        poslednjeCuvanje = 0L
        cfg.nedovrseniPrepis = ""
        handler.removeCallbacks(salvageRunnable)
        if (pending.get() == 0) {
            buffered.clear()
            expected = nextTicket
        }
        try {
            recorder = Recorder(cfg.sampleRate, Tisina.za(this, cfg)).also { it.start() }
        } catch (exc: Exception) {
            toast("Mikrofon: ${exc.message}")
            stopSelf()
            return
        }
        isRecording = true
        session = ++sessionSeq
        startedAt = System.currentTimeMillis()
        glasAt = 0L
        tekstAt = android.os.SystemClock.elapsedRealtime()
        pilula.prikazi()
        tick()
        if (cfg.longRecording) {
            if (GeminiStt.enabled(cfg)) thread { geminiLiveLoop() } else thread { segmentLoop() }
        }
    }

    private fun zaustaviIliPrekini() {
        if (isRecording) {
            stopRecording()
            return
        }
        if (GeminiStt.enabled(cfg) && (busy || prepis.vidjeno().isNotEmpty())) prisilnoZavrsi()
    }

    private fun stopRecording() {
        if (!isRecording) return
        // Zastavica pre skidanja tajmera: `tick` koji je vec u toku ne sme
        // ponovo da zakaze brojanje.
        prijemZaustavljen = true
        isRecording = false
        // Skida se SAMO tajmer. Ranije je ovde stajalo removeCallbacksAndMessages(null),
        // sto je brisalo i `deliver` poruke koje su radne niti vec postavile u red:
        // prepoznat segment bi nestao, `expected` bi zauvek stao, `pending` nikad
        // ne bi pao na nulu — pa bi pilula ostala narandzasta sa poslednjom cifrom
        // i servis se ne bi ugasio dok ga korisnik rucno ne prekine.
        handler.removeCallbacks(tickRunnable)
        handler.postDelayed(watchdogRunnable, 240_000)
        busy = true
        pilula.osvezi(elapsed(), busy = true, polishing = polishing)
        zapamtiOdmah()

        if (cfg.longRecording) {
            // Petlja sama pokupi ostatak iz reda i posalje rep; ovde se samo
            // trazi kraj, da se poslednji komadi ne izgube.
            recorder?.requestStop()
            if (GeminiStt.enabled(cfg)) handler.postDelayed(salvageRunnable, 8_000)
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
        // Jedna nit cuva redosled delova. Accessibility upis moze da saceka
        // fokus, pa ne sme da blokira nit koja cita Gemini odgovore.
        // Ako se prethodni diktat jos obradjuje, novi ceka svoj tiket. Inace
        // bi njegov potvrdeni deo mogao da pretekne stariji tekst u polju.
        val liveInsert = cfg.geminiLiveInsert && pending.get() == 1 && !formal() &&
            InsertService.isRunning && InsertService.hasInputField()
        val liveWriter = if (liveInsert) java.util.concurrent.Executors.newSingleThreadExecutor()
            else null
        val liveParts = mutableListOf<Pair<String, java.util.concurrent.Future<Boolean>>>()
        val liveFailed = java.util.concurrent.atomic.AtomicBoolean(false)

        try {
            var zavrseno = false
            val onUpdate: (String) -> Unit = { raw ->
                val text = GeminiStt.postProcess(raw, cfg).trim()
                tekstAt = android.os.SystemClock.elapsedRealtime()
                zapamtiPrikaz(text)
                if (cfg.geminiLivePreview) {
                    val rep = text.takeLast(450)
                    handler.post {
                        if (session == mojaSesija) pilula.pregled(rep)
                    }
                }
            }
            val onFinal: ((String) -> Unit)? = if (liveWriter != null) { raw ->
                val result = liveWriter.submit<Boolean> {
                    if (liveFailed.get() || sesijaZavrsena.get()) false else {
                        val written = runCatching {
                            val sirovo = GeminiStt.postProcess(raw, cfg).trim()
                            val chunk = TextPolish.glasovneKomande(sirovo)
                            val ok = chunk.isBlank() ||
                                InsertService.commitLive(chunk, cfg.restoreClipboard)
                            if (ok && sirovo.isNotBlank()) prepis.potvrdi(sirovo)
                            ok
                        }.getOrDefault(false)
                        if (!written) liveFailed.set(true)
                        written
                    }
                }
                synchronized(liveParts) { liveParts.add(raw to result) }
            } else null
            val onInterim: ((String) -> Unit)? = if (liveWriter != null) { raw ->
                if (raw.isNotBlank()) liveWriter.execute {
                    if (!liveFailed.get() && !sesijaZavrsena.get()) {
                        val temporary = GeminiStt.postProcess(raw, cfg).trim()
                        InsertService.previewLive(temporary)
                    }
                }
            } else null
            val sirov = GeminiStt.recognizeStream(
                cfg, onUpdate = onUpdate, onFinal = onFinal, onInterim = onInterim,
                veza = liveVeza,
            ) {
                val chunk = rec.nextChunk()
                when {
                    chunk != null -> {
                        totalBytes += chunk.size
                        if (peakLevel(chunk) >= PRAG_GLASA) glasAt = android.os.SystemClock.elapsedRealtime()
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
            liveWriter?.shutdown()
        }

        liveWriter?.let { writer ->
            val parts = synchronized(liveParts) { liveParts.toList() }
            for ((_, result) in parts) {
                if (!runCatching { result.get() }.getOrDefault(false)) break
            }
            // I privremeni poslovi bez Future-a moraju da zavrse pre ciscenja.
            writer.awaitTermination(8, java.util.concurrent.TimeUnit.SECONDS)
        }
        // Spasavanje je moglo da preuzme kraj dok smo cekali odgovor.
        if (!sesijaZavrsena.compareAndSet(false, true)) return
        handler.post { handler.removeCallbacks(salvageRunnable) }

        if (liveWriter != null) {
            val parts = synchronized(liveParts) { liveParts.toList() }
            InsertService.finishLive()
            val rawParts = parts.map { it.first }
            val full = if (tekst.isNotBlank()) tekst else
                GeminiStt.postProcess(rawParts.joinToString(" "), cfg)
            val missing = prepis.ostatak(full)
            val zaIstoriju = if (full.isNotBlank()) full else missing
            if (zaIstoriju.isNotBlank()) cfg.addHistory(TextPolish.glasovneKomande(zaIstoriju))
            if (missing.isNotBlank()) {
                val rest = TextPolish.glasovneKomande(missing)
                if (!InsertService.insert(rest, cfg.restoreClipboard)) {
                    problem = listOfNotNull(problem, "Upis nije uspeo; ostatak je u clipboard-u")
                        .joinToString(". ")
                    cfg.nedovrseniPrepis = rest
                } else {
                    cfg.nedovrseniPrepis = ""
                }
            } else {
                cfg.nedovrseniPrepis = ""
            }
            // Uspesno upisani delovi su vec u polju i istoriji.
            tekst = ""
        } else {
            val missing = prepis.ostatak(tekst)
            if (missing.isNotBlank()) {
                tekst = missing
                if (problem == "Ništa nije prepoznato") problem = null
            }
        }

        cfg.addRecordedSeconds(totalBytes / 2.0 / cfg.sampleRate)
        val poruka = problem
        handler.post {
            deliver(tekst, poruka, myTicket, last = true, sesija = mojaSesija)
        }
    }

    private fun zapamtiPrikaz(tekst: String) {
        if (tekst.isBlank() || sesijaZavrsena.get()) return
        prepis.vidi(tekst)
        val sada = System.currentTimeMillis()
        if (sada - poslednjeCuvanje >= 500) {
            poslednjeCuvanje = sada
            cfg.nedovrseniPrepis = tekst
        }
    }

    private fun zapamtiOdmah() {
        val tekst = prepis.vidjeno()
        if (tekst.isBlank()) return
        poslednjeCuvanje = System.currentTimeMillis()
        cfg.nedovrseniPrepis = tekst
    }

    /**
     * Tok nije završio posle Stop-a, ili je korisnik ponovo pritisnuo Završi.
     * U polje ide tekst koji je već bio na prikazu, pa se veza seče.
     */
    private fun prisilnoZavrsi() {
        if (!sesijaZavrsena.compareAndSet(false, true)) return
        handler.removeCallbacks(salvageRunnable)
        handler.removeCallbacks(tickRunnable)
        prijemZaustavljen = true
        isRecording = false
        liveVeza.get()?.abort()
        runCatching { recorder?.stop() }
        recorder = null
        val tekst = prepis.ostatak("")
        InsertService.finishLive()
        if (tekst.isNotBlank()) {
            val clean = TextPolish.glasovneKomande(tekst)
            cfg.nedovrseniPrepis = clean
            cfg.addHistory(clean)
            thread {
                if (InsertService.insert(clean, cfg.restoreClipboard)) cfg.nedovrseniPrepis = ""
            }
            toast("Veza je stala. Prikazan tekst je upisan.")
        }
        pending.set(0)
        busy = false
        finishSession()
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
        handler.post { pilula.osvezi(elapsed(), busy = true, polishing = polishing) }
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

    private fun insertNow(sirov: String) {
        val text = TextPolish.glasovneKomande(sirov)
        if (text.isBlank()) return
        cfg.addHistory(text)
        // Tekst i dalje zavrsava u clipboard-u kad upis ne prodje — izgubiti ga
        // je gore. Poruka preko ekrana se ne prikazuje: pojavljivala se posle
        // svakog diktata i samo smetala.
        if (!InsertService.isRunning) {
            copyToClipboard(text)
            cfg.nedovrseniPrepis = ""
            return
        }
        // Upis ceka da se fokus vrati u polje, pa ne sme na glavnu nit.
        thread {
            if (InsertService.insert(text, cfg.restoreClipboard)) cfg.nedovrseniPrepis = ""
            else cfg.nedovrseniPrepis = text
        }
    }

    private fun finishSession() {
        if (isRecording || pending.get() > 0) return
        handler.removeCallbacks(watchdogRunnable)
        busy = false
        pilula.sakrij()
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
    private fun limitSeconds(): Int = Prepoznaj.granica(cfg)

    private fun tick() {
        if (!isRecording || prijemZaustavljen) return
        val sec = elapsed()
        val limit = limitSeconds()
        if (sec >= limit) {
            // Bez granice bi slucajno pokrenut diktat mogao da snima satima.
            // Nastavak trazi nov pritisak.
            toast("Granica od ${limit}s — snimanje zaustavljeno")
            stopRecording()
            return
        }
        if (!isRecording || prijemZaustavljen) return
        pilula.osvezi(sec, busy = false, polishing = polishing)
        handler.postDelayed(tickRunnable, 250)
    }

    override fun onDestroy() {
        handler.removeCallbacks(tickRunnable)
        handler.removeCallbacks(watchdogRunnable)
        handler.removeCallbacks(salvageRunnable)
        if (!sesijaZavrsena.get()) zapamtiOdmah()
        liveVeza.get()?.abort()
        recorder?.stop()
        pilula.sakrij()
        isRecording = false
        isActive = false
        super.onDestroy()
    }

    // ------------------------------------------------------- sitnice

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
