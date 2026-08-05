package studio.room211.diktat

import android.accessibilityservice.AccessibilityService
import android.os.Bundle
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo

/**
 * Ubacuje tekst u polje koje je trenutno u fokusu.
 *
 * Bez tastature ovo je jedini pouzdan put. Prvo se proba dopisivanje na
 * postojeci sadrzaj (SET_TEXT), jer PASTE u nekim aplikacijama zameni sve
 * sto je vec upisano.
 */
class InsertService : AccessibilityService() {

    companion object {
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

    private fun insertNow(text: String): Boolean {
        val node = findFocusedEditable() ?: return false
        val existing = node.text?.toString() ?: ""
        val args = Bundle().apply {
            putCharSequence(
                AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,
                existing + text,
            )
        }
        val ok = node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
        node.recycle()
        return ok
    }

    private fun findFocusedEditable(): AccessibilityNodeInfo? {
        findFocus(AccessibilityNodeInfo.FOCUS_INPUT)?.let { if (it.isEditable) return it }
        val root = rootInActiveWindow ?: return null
        return firstEditable(root)
    }

    private fun firstEditable(node: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        if (node.isEditable && node.isFocused) return node
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            firstEditable(child)?.let { return it }
        }
        return null
    }
}
