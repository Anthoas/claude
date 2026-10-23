package fr.subtrad.tv

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/** Une vidéo de la playlist, telle que le Mac la décrit (jamais l'adresse du flux dans les listes). */
data class VideoItem(
    val id: Int,
    val name: String,
    val group: String,
    val kind: String,
    val ready: Boolean,
)

data class Page(val total: Int, val items: List<VideoItem>)

/** Détails d'une vidéo, adresse du flux comprise, pour la lire. */
data class VideoDetails(
    val id: Int,
    val name: String,
    val group: String,
    val ready: Boolean,
    val url: String,
    val subtitleLabel: String,
    val language: String,
)

data class CheckResult(val ok: Boolean, val message: String)

/** Une préparation (récupération et traduction) qui tourne sur le Mac. */
data class Job(
    val id: String,
    val videoId: Int,
    val title: String,
    val state: String, // running | done | error | cancelled
    val phase: Int,
    val fetchDone: Boolean,
    val fraction: Double?,
    val found: Int,
    val translated: Int,
    val note: String,
    val error: String,
) {
    val running get() = state == "running" || state == "playing"

    /** Avancement global en pour cent : lecture du fichier, puis traduction. */
    val percent: Int
        get() = when {
            fetchDone && found > 0 -> 50 + 50 * translated / found
            fraction != null -> (50 * fraction).toInt()
            else -> 0
        }.coerceIn(0, 100)
}

/** Erreur renvoyée par le Mac ; `status` vaut 0 quand le Mac n'a pas pu être joint. */
class SubtradException(val status: Int, message: String) : Exception(message) {
    val badCode get() = status == 401
    val unreachable get() = status == 0
}

/**
 * Parle au programme subtrad du Mac, sur le Wi-Fi de la maison. Le code n'est envoyé qu'au Mac :
 * jamais au serveur des vidéos, qui reçoit directement les requêtes du lecteur.
 */
class SubtradClient(address: String, private val code: String) {
    private val base = "http://" + address.trim().removePrefix("http://").trimEnd('/')

    suspend fun info(): JSONObject = getJson("/tele/api/info")

    suspend fun ready(): Page = page(getJson("/tele/api/ready"))

    suspend fun search(query: String, kind: String, offset: Int, limit: Int = 100): Page =
        page(getJson("/tele/api/search?q=${enc(query)}&kind=${enc(kind)}&offset=$offset&limit=$limit"))

    suspend fun video(id: Int): VideoDetails {
        val o = getJson("/tele/api/video?id=$id")
        return VideoDetails(
            id = o.getInt("id"), name = o.getString("name"), group = o.optString("group"),
            ready = o.getBoolean("ready"), url = o.getString("url"),
            subtitleLabel = o.optString("subtitle_label", "Indonesia"),
            language = o.optString("language", "id"),
        )
    }

    suspend fun check(id: Int): CheckResult {
        val o = postJson("/tele/api/check", JSONObject().put("id", id))
        return CheckResult(o.optBoolean("ok"), o.optString("message"))
    }

    suspend fun prepare(id: Int): Job = job(postJson("/tele/api/prepare", JSONObject().put("id", id)))

    suspend fun job(id: String): Job = job(getJson("/tele/api/job?id=${enc(id)}"))

    /** Préparations demandées par la télé, les plus récentes d'abord. */
    suspend fun jobs(): List<Job> = withContext(Dispatchers.IO) {
        val array = org.json.JSONArray(requestText("/tele/api/jobs"))
        (0 until array.length()).map { job(array.getJSONObject(it)) }
    }

    /** Supprime la traduction gardée sur le Mac (vidéo déjà regardée). */
    suspend fun forget(id: Int) {
        postJson("/tele/api/forget", JSONObject().put("id", id))
    }

    suspend fun cancel(id: String): Job = job(postJson("/tele/api/cancel", JSONObject().put("id", id)))

    /** Télécharge le .srt traduit dans `target` (le lecteur le lit ensuite depuis la télé). */
    suspend fun downloadSubtitles(id: Int, target: File): File = withContext(Dispatchers.IO) {
        val connection = open("/tele/api/subtitles?id=$id", "GET")
        try {
            checkStatus(connection)
            target.parentFile?.mkdirs()
            val staged = File(target.path + ".part")
            connection.inputStream.use { input -> staged.outputStream().use { input.copyTo(it) } }
            if (!staged.renameTo(target)) throw IOException("rename failed")
            target
        } catch (e: IOException) {
            throw SubtradException(0, e.message ?: "réseau")
        } finally {
            connection.disconnect()
        }
    }

    // --- outils ---

    private fun page(o: JSONObject): Page {
        val items = o.getJSONArray("items")
        return Page(o.getInt("total"), (0 until items.length()).map { i ->
            val it = items.getJSONObject(i)
            VideoItem(it.getInt("id"), it.getString("name"), it.optString("group"),
                it.optString("kind"), it.optBoolean("ready"))
        })
    }

    private fun job(o: JSONObject) = Job(
        id = o.getString("id"), videoId = o.optInt("channel_id", -1), title = o.optString("title"),
        state = o.getString("state"), phase = o.optInt("phase", 1),
        fetchDone = o.optBoolean("fetch_done"),
        fraction = if (o.isNull("fraction")) null else o.optDouble("fraction"),
        found = o.optInt("found"), translated = o.optInt("translated"),
        note = o.optString("note"), error = o.optString("error"),
    )

    private suspend fun getJson(path: String): JSONObject = request(path, "GET", null)

    private suspend fun postJson(path: String, body: JSONObject): JSONObject = request(path, "POST", body)

    private suspend fun requestText(path: String): String = withContext(Dispatchers.IO) {
        val connection = open(path, "GET")
        try {
            checkStatus(connection)
            connection.inputStream.bufferedReader().use { it.readText() }
        } catch (e: IOException) {
            throw SubtradException(0, e.message ?: "réseau")
        } finally {
            connection.disconnect()
        }
    }

    private suspend fun request(path: String, method: String, body: JSONObject?): JSONObject =
        withContext(Dispatchers.IO) {
            val connection = open(path, method)
            try {
                if (body != null) {
                    connection.doOutput = true
                    connection.setRequestProperty("Content-Type", "application/json")
                    connection.outputStream.use { it.write(body.toString().toByteArray()) }
                }
                checkStatus(connection)
                JSONObject(connection.inputStream.bufferedReader().use { it.readText() })
            } catch (e: IOException) {
                throw SubtradException(0, e.message ?: "réseau")
            } finally {
                connection.disconnect()
            }
        }

    private fun open(path: String, method: String): HttpURLConnection {
        val connection = try {
            URL(base + path).openConnection() as HttpURLConnection
        } catch (e: Exception) {
            throw SubtradException(0, e.message ?: "adresse invalide")
        }
        connection.requestMethod = method
        connection.connectTimeout = 5_000
        connection.readTimeout = 60_000
        connection.useCaches = false
        connection.setRequestProperty("X-Subtrad-Code", code)
        return connection
    }

    private fun checkStatus(connection: HttpURLConnection) {
        val status = connection.responseCode
        if (status in 200..299) return
        val message = try {
            JSONObject(connection.errorStream?.bufferedReader()?.use { it.readText() } ?: "{}")
                .optString("error", "HTTP $status")
        } catch (e: Exception) {
            "HTTP $status"
        }
        throw SubtradException(status, message)
    }

    private fun enc(value: String) = URLEncoder.encode(value, "UTF-8")
}
