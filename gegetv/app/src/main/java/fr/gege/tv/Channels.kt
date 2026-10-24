package fr.gege.tv

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
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
 * La liste des directs : lue une fois depuis la playlist M3U (qui contient aussi des centaines de
 * milliers de films et d'épisodes), puis gardée sur la télé.
 */
class ChannelStore(context: Context) {
    private val file = File(context.filesDir, "chaines.json")

    val savedAt: Long get() = if (file.exists()) file.lastModified() else 0L

    suspend fun cached(): List<Channel> = withContext(Dispatchers.IO) {
        if (!file.exists()) return@withContext emptyList()
        try {
            val array = JSONArray(file.readText())
            (0 until array.length()).map { Channel.fromJson(array.getJSONObject(it)) }
        } catch (e: Exception) {
            emptyList()
        }
    }

    /**
     * Télécharge la playlist ligne par ligne (jamais entière en mémoire : elle peut peser
     * plusieurs centaines de Mo) et ne garde que les directs. `onProgress` reçoit 0 à 1, ou -1
     * si la taille est inconnue.
     */
    suspend fun refresh(playlistUrl: String, onProgress: (Float) -> Unit): List<Channel> = withContext(Dispatchers.IO) {
        val connection = URL(playlistUrl.trim()).openConnection() as HttpURLConnection
        connection.connectTimeout = 15_000
        connection.readTimeout = 60_000
        connection.setRequestProperty("User-Agent", "GegeTV/1.0")
        try {
            if (connection.responseCode !in 200..299) throw IOException("le serveur a répondu ${connection.responseCode}")
            val total = connection.contentLengthLong
            var read = 0L
            var lastShown = -1
            val channels = ArrayList<Channel>()
            var pending: Pair<String, Map<String, String>>? = null
            connection.inputStream.bufferedReader(Charsets.UTF_8).useLines { lines ->
                for (raw in lines) {
                    read += raw.length + 1
                    if (total > 0) {
                        val percent = (100 * read / total).toInt()
                        if (percent != lastShown) { lastShown = percent; onProgress(percent / 100f) }
                    }
                    val line = raw.trim()
                    when {
                        line.startsWith("#EXTINF") -> pending = parseExtinf(line)
                        line.isEmpty() || line.startsWith("#") -> Unit
                        else -> {
                            val info = pending
                            pending = null
                            if (info != null && isLive(line)) {
                                val (name, attrs) = info
                                channels += Channel(name, attrs["group-title"].orEmpty(), attrs["tvg-logo"].orEmpty(), line)
                            }
                        }
                    }
                }
            }
            if (channels.isEmpty()) throw IOException("aucune chaîne en direct dans cette playlist")
            val array = JSONArray()
            channels.forEach { array.put(it.toJson()) }
            val staged = File(file.path + ".part")
            staged.writeText(array.toString())
            staged.renameTo(file)
            onProgress(1f)
            channels
        } finally {
            connection.disconnect()
        }
    }

    companion object {
        private val ATTR = Regex("""([\w-]+)="([^"]*)"""")

        /** `#EXTINF:-1 tvg-logo="…" group-title="…",Nom` → (nom, attributs). */
        fun parseExtinf(line: String): Pair<String, Map<String, String>> {
            val comma = line.lastIndexOf(',')
            val name = if (comma >= 0) line.substring(comma + 1).trim() else ""
            val head = if (comma >= 0) line.substring(0, comma) else line
            return name to ATTR.findAll(head).associate { it.groupValues[1] to it.groupValues[2] }
        }

        /** Les films et épisodes des serveurs IPTV sont sous /movie/ et /series/ : le reste est du direct. */
        fun isLive(url: String): Boolean {
            val path = try { URL(url).path.lowercase() } catch (e: Exception) { return false }
            return "/movie/" !in path && "/series/" !in path
        }
    }
}
