package fr.gege.tv

import android.util.Base64
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.util.concurrent.ConcurrentHashMap

/** Une émission : heures en millisecondes (temps universel, donc sans souci de fuseau horaire). */
data class Program(val title: String, val description: String, val start: Long, val end: Long) {
    fun progress(now: Long): Float = if (end > start) ((now - start).toFloat() / (end - start)).coerceIn(0f, 1f) else 0f
}

/** L'émission en cours et les suivantes, ou rien si l'heure est passée. */
fun List<Program>.fromNow(now: Long): List<Program> = filter { it.end > now }

/**
 * Le programme des chaînes, demandé au serveur Xtream Codes de la playlist (le même compte que
 * les adresses des chaînes : …/utilisateur/motdepasse/numéro). Une chaîne à la fois, et seulement
 * pour celles qu'on regarde ou les favoris : le guide complet pèse des dizaines de Mo.
 */
class Guide {
    private class Entry(val programs: List<Program>, val fetchedAt: Long)

    private val cache = ConcurrentHashMap<String, Entry>()

    /** Programme de la chaîne, redemandé après 30 min ou quand les émissions connues sont finies. */
    suspend fun programs(channel: Channel, now: Long = System.currentTimeMillis()): List<Program> {
        cache[channel.url]?.let { entry ->
            val upcoming = entry.programs.fromNow(now)
            if (now - entry.fetchedAt < REFRESH_MS && (upcoming.size >= 2 || now - entry.fetchedAt < RETRY_MS)) {
                return upcoming
            }
        }
        val fresh = try { fetch(channel) } catch (e: Exception) { null }
            ?: return cache[channel.url]?.programs?.fromNow(now).orEmpty()
        cache[channel.url] = Entry(fresh, now)
        return fresh.fromNow(now)
    }

    private suspend fun fetch(channel: Channel): List<Program>? = withContext(Dispatchers.IO) {
        val account = account(channel.url) ?: return@withContext null
        val query = listOf("username" to account.user, "password" to account.password,
                           "action" to "get_short_epg", "stream_id" to account.streamId, "limit" to "6")
            .joinToString("&") { (k, v) -> "$k=${URLEncoder.encode(v, "UTF-8")}" }
        val connection = URL("${account.base}/player_api.php?$query").openConnection() as HttpURLConnection
        connection.connectTimeout = 10_000
        connection.readTimeout = 15_000
        connection.setRequestProperty("User-Agent", "GegeTV/1.0")
        try {
            if (connection.responseCode !in 200..299) return@withContext null
            parse(connection.inputStream.bufferedReader().readText())
        } finally {
            connection.disconnect()
        }
    }

    data class Account(val base: String, val user: String, val password: String, val streamId: String)

    companion object {
        private const val REFRESH_MS = 30 * 60_000L
        private const val RETRY_MS = 5 * 60_000L

        /** `http://hôte:port[/live]/utilisateur/motdepasse/123[.ts]` → compte et numéro de la chaîne. */
        fun account(url: String): Account? = try {
            val u = URL(url)
            val parts = u.path.split('/').filter { it.isNotEmpty() }
            if (parts.size < 3) null
            else {
                val id = parts.last().substringBefore('.')
                if (id.isEmpty() || !id.all { it.isDigit() }) null
                else Account("${u.protocol}://${u.authority}", parts[parts.size - 3], parts[parts.size - 2], id)
            }
        } catch (e: Exception) {
            null
        }

        /** Réponse de `get_short_epg` : titres et résumés en base64, heures en secondes. */
        fun parse(json: String): List<Program> {
            val listings = JSONObject(json).optJSONArray("epg_listings") ?: return emptyList()
            return (0 until listings.length()).mapNotNull { i ->
                val o = listings.optJSONObject(i) ?: return@mapNotNull null
                val start = o.optString("start_timestamp").toLongOrNull() ?: return@mapNotNull null
                val end = (o.optString("stop_timestamp").toLongOrNull() ?: return@mapNotNull null)
                val title = decode(o.optString("title")).removePrefix("Live: ").trim()
                if (title.isEmpty()) null else Program(title, decode(o.optString("description")).trim(), start * 1000, end * 1000)
            }.sortedBy { it.start }
        }

        private fun decode(text: String): String = try {
            String(Base64.decode(text, Base64.DEFAULT), Charsets.UTF_8)
        } catch (e: IllegalArgumentException) {
            text
        }
    }
}
