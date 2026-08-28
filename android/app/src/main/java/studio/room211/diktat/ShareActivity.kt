package studio.room211.diktat

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.media.MediaMetadataRetriever
import android.os.Bundle
import android.provider.OpenableColumns
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.color.DynamicColors
import studio.room211.diktat.Ui.body
import studio.room211.diktat.Ui.button
import studio.room211.diktat.Ui.card
import studio.room211.diktat.Ui.dp
import kotlin.concurrent.thread

/** Ekran koji dobija audio preko Android opcije „Deli sa…“. */
class ShareActivity : AppCompatActivity() {

    private lateinit var cfg: Config
    private lateinit var status: TextView
    private lateinit var result: TextView
    private lateinit var copy: View
    private var resultText = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        DynamicColors.applyToActivityIfAvailable(this)
        super.onCreate(savedInstanceState)

        cfg = Config(this)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            val side = dp(16)
            setPadding(side, dp(18), side, dp(28))
        }
        root.addView(TextView(this).apply {
            text = "Diktat — audio fajl"
            setTextAppearance(com.google.android.material.R.style.TextAppearance_Material3_TitleLarge)
            setPadding(dp(4), 0, 0, dp(12))
        })
        val (card, box) = card(this, "Transkripcija")
        status = body(this, "Pripremam audio…")
        box.addView(status)
        result = TextView(this).apply {
            setTextAppearance(com.google.android.material.R.style.TextAppearance_Material3_BodyLarge)
            setPadding(0, dp(10), 0, dp(10))
            setTextIsSelectable(true)
            visibility = View.GONE
        }
        box.addView(result)
        copy = button(this, "Kopiraj tekst") { copyResult() }.apply {
            isEnabled = false
        }
        box.addView(copy)
        box.addView(button(this, "Zatvori") { finish() })
        root.addView(card)
        setContentView(ScrollView(this).apply { addView(root) })

        val uri = sharedUri()
        if (uri == null) {
            showError("Nisam dobio audio fajl iz druge aplikacije.")
        } else {
            transcribe(uri)
        }
    }

    private fun sharedUri() =
        intent.getParcelableExtra<android.net.Uri>(Intent.EXTRA_STREAM)
            ?: intent.clipData?.getItemAt(0)?.uri
            ?: intent.data

    private fun transcribe(uri: android.net.Uri) {
        thread(name = "shared-audio-transcription") {
            runCatching { transcribeFile(uri) }
                .onSuccess { text ->
                    runOnUiThread { showResult(text) }
                }
                .onFailure { error ->
                    runOnUiThread {
                        showError(error.message ?: "Transkripcija audio fajla nije uspela.")
                    }
                }
        }
    }

    private fun transcribeFile(uri: android.net.Uri): String {
        val name = displayName(uri)
        val mime = contentResolver.getType(uri)
        return if (cfg.transcriptionProvider == "openai") {
            val bytes = contentResolver.openInputStream(uri)?.use { it.readBytes() }
                ?: throw IllegalArgumentException("Ne mogu da pročitam audio fajl.")
            val seconds = durationSeconds(uri)
            if (seconds > 0) cfg.addRecordedSeconds(seconds)
            val raw = OpenAiTranscription.recognizeFile(bytes, name, mime, seconds, cfg)
            finishText(OpenAiTranscription.postProcess(raw, cfg))
        } else {
            statusOnWorker("Pretvaram audio u format za Google…")
            val pcm = AudioDecoder.decode(this, uri)
            if (pcm.isEmpty()) throw IllegalArgumentException("Audio fajl je prazan.")
            val seconds = pcm.size / 2.0 / cfg.sampleRate
            cfg.addRecordedSeconds(seconds)
            val partBytes = cfg.sampleRate * 2 * cfg.maxRequestSeconds
            val pieces = mutableListOf<String>()
            var start = 0
            while (start < pcm.size) {
                val end = minOf(pcm.size, start + partBytes)
                val part = pcm.copyOfRange(start, end)
                statusOnWorker("Transkribujem audio… ${pieces.size + 1}. deo")
                val raw = WebStt.recognize(part, cfg).trim()
                if (raw.isNotBlank()) pieces += raw
                start = end
            }
            val combined = pieces.joinToString(" ")
            val prepared = if (Polish.available(cfg) && Polish.toolCount(cfg) > 0 && cfg.polishTidy) {
                combined
            } else {
                TextPolish.apply(combined, cfg, trailing = false)
            }
            finishText(prepared)
        }
    }

    /** Isti redosled lokalnih pravila i AI obrade kao kod dikтирања. */
    private fun finishText(raw: String): String {
        val base = raw.trim()
        if (base.isBlank()) throw IllegalArgumentException("Model nije prepoznao govor.")
        val formal = Polish.available(cfg) && Polish.toolCount(cfg) > 0
        if (!formal) return base

        val polished = runCatching {
            Polish.polish(base, cfg).also { cfg.countPolish() }
        }.getOrElse { base }
        val afterModel = if (cfg.polishTidy) {
            TextPolish.afterModel(polished, cfg)
        } else {
            TextPolish.applyBlocks(polished, cfg)
        }
        return when {
            cfg.polishBullets -> afterModel.trimEnd() + "\n"
            cfg.polishParagraphs -> afterModel.trimEnd() + "\n\n"
            else -> afterModel.trimEnd()
        }
    }

    private fun durationSeconds(uri: android.net.Uri): Double = runCatching {
        val retriever = MediaMetadataRetriever()
        try {
            retriever.setDataSource(this, uri)
            retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)
                ?.toDoubleOrNull()?.div(1000.0) ?: 0.0
        } finally {
            retriever.release()
        }
    }.getOrDefault(0.0)

    private fun displayName(uri: android.net.Uri): String {
        val queried = runCatching {
            contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)
                ?.use { cursor ->
                    if (cursor.moveToFirst()) cursor.getString(0) else null
                }
        }.getOrNull()
        return queried?.takeIf { it.isNotBlank() }
            ?: uri.lastPathSegment?.substringAfterLast('/')?.ifBlank { null }
            ?: "shared-audio"
    }

    private fun statusOnWorker(text: String) = runOnUiThread { status.text = text }

    private fun showResult(text: String) {
        resultText = text.trimEnd()
        cfg.addHistory(resultText)
        copyToClipboard(resultText)
        status.text = "Transkripcija je završena i automatski kopirana u clipboard."
        result.text = resultText
        result.visibility = View.VISIBLE
        copy.isEnabled = true
    }

    private fun showError(message: String) {
        status.text = "Greška: $message"
        result.visibility = View.GONE
        copy.isEnabled = false
    }

    private fun copyResult() {
        if (resultText.isBlank()) return
        copyToClipboard(resultText)
        Toast.makeText(this, "Tekst je kopiran u clipboard.", Toast.LENGTH_SHORT).show()
    }

    private fun copyToClipboard(text: String) {
        getSystemService(ClipboardManager::class.java)?.setPrimaryClip(
            ClipData.newPlainText("Diktat", text)
        )
    }
}
