package studio.room211.diktat

/** Fixed settings shared by the compact screen and the recording service. */
object MobilePolicy {
    const val MAX_SECONDS = 600
    val providers = setOf("google", "gemini_live")
    fun provider(value: String?) = if (value == "google") "google" else "gemini_live"
}
