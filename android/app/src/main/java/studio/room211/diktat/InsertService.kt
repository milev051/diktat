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

        @Volatile
        private var instance: InsertService? = null

        val isRunning: Boolean get() = instance != null

        /** Vraca true ako je tekst zaista negde upisan. */
        fun insert(text: String): Boolean = instance?.insertNow(text) ?: false
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

    private fun insertNow(text: String): Boolean {
        // PASTE cita iz clipboard-a, pa mora da bude popunjen pre pokusaja.
        putOnClipboard(text)

        repeat(TRIES) {
            val node = findEditable()
            if (node != null) {
                val done = paste(node) || setText(node, text)
                runCatching { @Suppress("DEPRECATION") node.recycle() }
                if (done) return true
            }
            Thread.sleep(WAIT_MS)
        }
        return false
    }

    private fun paste(node: AccessibilityNodeInfo): Boolean =
        runCatching {
            node.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
            node.performAction(AccessibilityNodeInfo.ACTION_PASTE)
        }.getOrDefault(false)

    private fun setText(node: AccessibilityNodeInfo, text: String): Boolean =
        runCatching {
            val merged = (node.text?.toString() ?: "") + text
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
    private fun findEditable(): AccessibilityNodeInfo? {
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
