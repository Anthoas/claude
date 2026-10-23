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

    fun client(): SubtradClient? =
        if (address.isNotBlank() && code.isNotBlank()) SubtradClient(address, code) else null
}
