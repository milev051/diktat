package studio.room211.diktat

import android.accessibilityservice.AccessibilityService
import android.content.ClipData
import android.content.ClipboardManager
import android.os.Bundle
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo

/**
 * Upisuje prepoznat tekst u polje u kome je kursor.
 *
 * Dve stvari koje nisu ocigledne:
 *
 *   * ACTION_PASTE ide PRE ACTION_SET_TEXT. Paste postuje poziciju kursora i
 *     prolazi u aplikacijama koje SET_TEXT tiho odbijaju, a SET_TEXT zamenjuje
 *     ceo sadrzaj polja pa mora rucno da vraca kursor na kraj.
 *
 *   * Trazi se u vise pokusaja. Aktivnost pokrenuta bocnim tasterom tek sto se
 *     zatvorila, pa fokus jos nije stigao nazad u polje — prvi pokusaj skoro
 *     uvek promasi. To je bio razlog zasto je tekst zavrsavao u clipboard-u.
 *
 * Zove se iz radne niti, jer ceka izmedju pokusaja.
 */
class InsertService : AccessibilityService() {

    companion object {
        private const val TRIES = 12
        private const val WAIT_MS = 120L
        private const val CLIP_RESTORE_MS = 450L

        @Volatile
        private var instance: InsertService? = null

        val isRunning: Boolean get() = instance != null

        /** Vraca true ako je tekst zaista negde upisan. */
        fun insert(text: String, restoreClipboard: Boolean = false): Boolean =
            instance?.insertNow(text, restoreClipboard) ?: false

        /**
         * Ima li uopste polja u koje bi tekst mogao da udje.
         * Bez pokusaja i cekanja — zove se pre snimanja, mora da bude trenutno.
         */
        fun hasInputField(): Boolean = instance?.findEditable()?.let {
            runCatching { @Suppress("DEPRECATION") it.recycle() }
            true
        } ?: false
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
    }

    override fun onDestroy() {
        instance = null
        super.onDestroy()
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {}
    override fun onInterrupt() {}

    // ------------------------------------------------------------------

    /**
     * SET_TEXT ide PRVI, PASTE tek ako on ne prodje.
     *
     * Android od 13 prikaze sistemsko obavestenje „kopirano" cim neka aplikacija
     * upise u clipboard, a PASTE bez toga ne radi — pa se posle svakog diktata
     * javljala poruka koja se ne moze ugasiti. SET_TEXT ne dira clipboard.
     * Polje se ne prepisuje: postojeci tekst se cita i novi se nadovezuje.
     */
    private fun insertNow(text: String, restoreClipboard: Boolean): Boolean {
        repeat(TRIES) {
            val node = findEditable()
            if (node != null) {
                if (setText(node, text)) {
                    runCatching { @Suppress("DEPRECATION") node.recycle() }
                    return true
                }
                // Neke aplikacije (WebView, deo Compose polja) odbijaju SET_TEXT;
                // tu ostaje clipboard, uz sistemsku poruku koju ne kontrolisemo.
                val previous = if (restoreClipboard) currentClip() else null
                putOnClipboard(text)
                val done = paste(node)
                runCatching { @Suppress("DEPRECATION") node.recycle() }
                if (done) {
                    if (restoreClipboard) {
                        // Ciljna aplikacija jos cita iz clipboard-a kad PASTE
                        // prodje, pa se ne sme vratiti odmah.
                        Thread.sleep(CLIP_RESTORE_MS)
                        putOnClipboard(previous ?: "")
                    }
                    return true
                }
            }
            Thread.sleep(WAIT_MS)
        }
        // Upis nije prosao — tekst ide u clipboard i kad je vracanje ukljuceno,
        // jer je izgubiti ga gore od toga da ostane zapisan.
        putOnClipboard(text)
        return false
    }

    private fun currentClip(): String =
        getSystemService(ClipboardManager::class.java)
            ?.primaryClip?.takeIf { it.itemCount > 0 }
            ?.getItemAt(0)?.coerceToText(this)?.toString()
            ?: ""

    private fun paste(node: AccessibilityNodeInfo): Boolean =
        runCatching {
            node.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
            node.performAction(AccessibilityNodeInfo.ACTION_PASTE)
        }.getOrDefault(false)

    /**
     * Postojeci tekst polja, ili prazno.
     *
     * `node.text` na PRAZNOM polju vraca njegov hint ("Ovde probaj diktat"), pa
     * bi nadovezivanje upisalo taj natpis ispred izdiktiranog teksta. Zato se
     * gleda `isShowingHintText`, uz poredjenje sa `hintText` kao rezervu za
     * uredjaje koji tu zastavicu ne postavljaju.
     */
    private fun postojeci(node: AccessibilityNodeInfo): String {
        val tekst = node.text?.toString() ?: return ""
        if (node.isShowingHintText) return ""
        val hint = runCatching { node.hintText?.toString() }.getOrNull()
        if (!hint.isNullOrEmpty() && hint == tekst) return ""
        return tekst
    }

    private fun setText(node: AccessibilityNodeInfo, text: String): Boolean =
        runCatching {
            val merged = postojeci(node) + text
            val args = Bundle().apply {
                putCharSequence(
                    AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, merged
                )
            }
            if (!node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)) {
                return@runCatching false
            }
            // SET_TEXT ostavi kursor na pocetku; vrati ga na kraj.
            node.performAction(
                AccessibilityNodeInfo.ACTION_SET_SELECTION,
                Bundle().apply {
                    putInt(
                        AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_START_INT, merged.length
                    )
                    putInt(
                        AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_END_INT, merged.length
                    )
                },
            )
            true
        }.getOrDefault(false)

    // ------------------------------------------------------------------

    /** Prvo pravi fokus unosa, pa tek onda trazenje po stablu prozora. */
    internal fun findEditable(): AccessibilityNodeInfo? {
        runCatching { findFocus(AccessibilityNodeInfo.FOCUS_INPUT) }
            .getOrNull()
            ?.let { if (it.isEditable) return it }

        // Fokus ume da bude u prozoru koji nije "aktivan" — npr. iznad tastature.
        runCatching { windows }.getOrNull().orEmpty().forEach { window ->
            val root = runCatching { window.root }.getOrNull() ?: return@forEach
            focusedEditable(root)?.let { return it }
        }

        val root = runCatching { rootInActiveWindow }.getOrNull() ?: return null
        return focusedEditable(root)
    }

    private fun focusedEditable(node: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        if (node.isEditable && (node.isFocused || node.isAccessibilityFocused)) return node
        for (i in 0 until node.childCount) {
            val child = runCatching { node.getChild(i) }.getOrNull() ?: continue
            focusedEditable(child)?.let { return it }
        }
        return null
    }

    private fun putOnClipboard(text: String) {
        getSystemService(ClipboardManager::class.java)
            ?.setPrimaryClip(ClipData.newPlainText("diktat", text))
    }
}
