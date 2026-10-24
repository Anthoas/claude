package fr.gege.tv

import android.content.Context
import org.json.JSONArray

/** Lien de la playlist et chaînes favorites, gardés sur la télé (espace privé de l'application). */
class Prefs(context: Context) {
    private val prefs = context.getSharedPreferences("gegetv", Context.MODE_PRIVATE)

    var playlistUrl: String
        get() = prefs.getString("playlist", "") ?: ""
        set(value) = prefs.edit().putString("playlist", value.trim()).apply()

    /** Favoris dans l'ordre où ils ont été ajoutés (une copie de la chaîne : nom, logo, adresse). */
    var favorites: List<Channel>
        get() = try {
            val array = JSONArray(prefs.getString("favorites", "[]"))
            (0 until array.length()).map { Channel.fromJson(array.getJSONObject(it)) }
        } catch (e: Exception) {
            emptyList()
        }
        set(value) {
            val array = JSONArray()
            value.forEach { array.put(it.toJson()) }
            prefs.edit().putString("favorites", array.toString()).apply()
        }
}
