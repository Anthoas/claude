package fr.gege.tv

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.text.Normalizer

/** Une chaîne en direct de la playlist. */
data class Channel(val name: String, val group: String, val logo: String, val url: String) {
    /** Nom et catégorie sans accents ni majuscules, pour la recherche. */
    val haystack: String by lazy { normalize("$name $group") }

    fun toJson(): JSONObject = JSONObject().put("name", name).put("group", group).put("logo", logo).put("url", url)

    companion object {
        fun fromJson(o: JSONObject) = Channel(o.optString("name"), o.optString("group"), o.optString("logo"), o.optString("url"))
    }
}

fun normalize(text: String): String =
    Normalizer.normalize(text, Normalizer.Form.NFD).replace(Regex("\\p{M}+"), "").lowercase()

/**
 * La liste des directs de chaque source, demandée au serveur Xtream Codes (`get_live_streams` :
 * quelques secondes, au lieu de la playlist M3U complète qui contient aussi des centaines de
 * milliers de films et d'épisodes), puis gardée sur la télé.
 */
class ChannelStore(context: Context) {
    private val dir = context.filesDir

    private fun file(source: Source) = File(dir, "chaines-${source.id}.json")

    fun savedAt(source: Source): Long = file(source).let { if (it.exists()) it.lastModified() else 0L }

    suspend fun cached(source: Source): List<Channel> = withContext(Dispatchers.IO) {
        val file = file(source)
        if (!file.exists()) return@withContext emptyList()
        try {
            val array = JSONArray(file.readText())
            (0 until array.length()).map { Channel.fromJson(array.getJSONObject(it)) }
        } catch (e: Exception) {
            emptyList()
        }
    }

    suspend fun refresh(source: Source): List<Channel> {
        val categories = JSONArray(source.api("get_live_categories")).let { array ->
            (0 until array.length()).associate { i ->
                array.getJSONObject(i).let { it.optString("category_id") to it.optString("category_name") }
            }
        }
        val streams = JSONArray(source.api("get_live_streams"))
        val channels = withContext(Dispatchers.Default) {
            (0 until streams.length()).mapNotNull { i ->
                val o = streams.getJSONObject(i)
                val id = o.optString("stream_id").takeIf { it.isNotBlank() } ?: return@mapNotNull null
                Channel(o.optString("name").trim(), categories[o.optString("category_id")].orEmpty(),
                        o.optString("stream_icon"), source.streamUrl(id))
            }
        }
        if (channels.isEmpty()) throw IOException("aucune chaîne en direct chez cette source")
        withContext(Dispatchers.IO) {
            val array = JSONArray()
            channels.forEach { array.put(it.toJson()) }
            val staged = File(file(source).path + ".part")
            staged.writeText(array.toString())
            staged.renameTo(file(source))
        }
        return channels
    }

    /** Efface la liste gardée d'une source supprimée. */
    fun forget(source: Source) {
        file(source).delete()
    }

    /** Première ouverture de cette version : la liste de l'ancienne version devient celle de la source. */
    fun adoptLegacy(source: Source) {
        val legacy = File(dir, "chaines.json")
        if (legacy.exists() && !file(source).exists()) legacy.renameTo(file(source))
    }
}
