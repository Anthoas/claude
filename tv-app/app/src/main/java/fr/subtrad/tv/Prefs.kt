package fr.subtrad.tv

import android.content.Context

/** Adresse du Mac et code, gardés sur la télé (espace privé de l'application). */
class Prefs(context: Context) {
    private val prefs = context.getSharedPreferences("subtrad", Context.MODE_PRIVATE)

    var address: String
        get() = prefs.getString("address", "") ?: ""
        set(value) = prefs.edit().putString("address", value.trim()).apply()

    var code: String
        get() = prefs.getString("code", "") ?: ""
        set(value) = prefs.edit().putString("code", value.trim()).apply()

    /** Dernières recherches, la plus récente d'abord. */
    var recentSearches: List<String>
        get() = (prefs.getString("recent_searches", "") ?: "").split("\n").filter { it.isNotBlank() }
        set(value) = prefs.edit().putString("recent_searches", value.joinToString("\n")).apply()

    fun addRecentSearch(query: String, keep: Int = 6) {
        val q = query.trim()
        if (q.isEmpty()) return
        recentSearches = (listOf(q) + recentSearches.filter { !it.equals(q, ignoreCase = true) }).take(keep)
    }

    fun client(): SubtradClient? =
        if (address.isNotBlank() && code.isNotBlank()) SubtradClient(address, code) else null
}
