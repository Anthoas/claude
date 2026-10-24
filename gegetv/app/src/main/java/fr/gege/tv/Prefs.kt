package fr.gege.tv

import android.content.Context
import org.json.JSONArray

/** Lien de la playlist et chaînes favorites, gardés sur la télé (espace privé de l'application). */
class Prefs(context: Context) {
    private val prefs = context.getSharedPreferences("gegetv", Context.MODE_PRIVATE)

    var playlistUrl: String
        get() = prefs.getString("playlist", "") ?: ""
        set(value) = prefs.edit().putString("playlist", value.trim()).apply()

    /** Favoris (une copie de chaque chaîne : nom, logo, adresse), gardés à l'abri des pertes. */
    val favorites = Favorites(context)

    /** Favoris des premières versions (rangés ici) : repris une fois par `Favorites`, puis laissés tels quels. */
    val legacyFavorites: List<Channel>
        get() = try {
            val array = JSONArray(prefs.getString("favorites", "[]"))
            (0 until array.length()).map { Channel.fromJson(array.getJSONObject(it)) }
        } catch (e: Exception) {
            emptyList()
        }
}
