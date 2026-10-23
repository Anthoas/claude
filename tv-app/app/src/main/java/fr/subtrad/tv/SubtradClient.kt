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
    val watched: Boolean = false,
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
    val positionMs: Long = 0, // où la lecture s'était arrêtée
    val watched: Boolean = false,
)

data class CheckResult(val ok: Boolean, val message: String)

// --- Catalogue Xtream Codes (affiches, séries par saison) ---

data class Category(val id: String, val name: String, val count: Int)

/** Une affiche de la grille : une série (seriesId) ou un film (vodId, id = vidéo de la playlist). */
data class Poster(
    val seriesId: Int?,
    val vodId: Int?,
    val id: Int,
    val name: String,
    val cover: String,
    val year: String,
    val rating: String,
    val ready: Boolean,
    val watched: Boolean = false,
    val progress: Double = 0.0,
)

data class PosterPage(val total: Int, val items: List<Poster>)

data class Episode(
    val id: Int, // vidéo de la playlist, -1 si absente
    val number: Int,
    val title: String,
    val duration: String,
    val airDate: String,
    val image: String,
    val ready: Boolean,
    val plot: String = "",
    val watched: Boolean = false,
    val progress: Double = 0.0,
)

data class Season(val number: Int, val name: String, val episodes: List<Episode>)

/** Fiche d'une série ou d'un film (seasons vide pour un film). */
data class Sheet(
    val name: String,
    val cover: String,
    val backdrop: String,
    val plot: String,
    val genre: String,
    val year: String,
    val rating: String,
    val duration: String,
    val id: Int, // film : vidéo de la playlist
    val seasons: List<Season>,
    val nextSeason: Int = 0, // saison et épisode (indices) à proposer
    val nextEpisode: Int = 0,
)

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
            positionMs = o.optLong("position"), watched = o.optBoolean("watched"),
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

    // --- catalogue ---

    suspend fun catalogAvailable(): Boolean = getJson("/tele/api/catalog").optBoolean("available")

    suspend fun categories(type: String): List<Category> = withContext(Dispatchers.IO) {
        val array = org.json.JSONArray(requestText("/tele/api/catalog/categories?type=${enc(type)}"))
        (0 until array.length()).map {
            val o = array.getJSONObject(it)
            Category(o.getString("id"), o.getString("name"), o.optInt("count"))
        }
    }

    suspend fun posters(type: String, category: String, query: String, offset: Int, limit: Int = 60): PosterPage {
        val path = if (type == "series") "series" else "movies"
        val o = getJson("/tele/api/catalog/$path?category=${enc(category)}&q=${enc(query)}&offset=$offset&limit=$limit")
        val items = o.getJSONArray("items")
        return PosterPage(o.getInt("total"), (0 until items.length()).map { i ->
            val p = items.getJSONObject(i)
            Poster(
                seriesId = if (p.has("series_id")) p.optInt("series_id") else null,
                vodId = if (p.has("vod_id")) p.optInt("vod_id") else null,
                id = p.optInt("id", -1), name = p.optString("name"), cover = p.optString("cover"),
                year = p.optString("year"), rating = p.optString("rating"), ready = p.optBoolean("ready"),
                watched = p.optBoolean("watched"), progress = p.optDouble("progress", 0.0),
            )
        })
    }

    suspend fun seriesSheet(seriesId: Int): Sheet {
        val o = getJson("/tele/api/catalog/series/info?id=$seriesId")
        val seasons = o.getJSONArray("seasons")
        return sheet(o, (0 until seasons.length()).map { i ->
            val s = seasons.getJSONObject(i)
            val eps = s.getJSONArray("episodes")
            Season(s.optInt("season"), s.optString("name"), (0 until eps.length()).map { j ->
                val e = eps.getJSONObject(j)
                Episode(e.optInt("id", -1), e.optInt("episode"), e.optString("title"), e.optString("duration"),
                    e.optString("air_date"), e.optString("image"), e.optBoolean("ready"), e.optString("plot"),
                    e.optBoolean("watched"), e.optDouble("progress", 0.0))
            })
        })
    }

    suspend fun movieSheet(vodId: Int): Sheet = sheet(getJson("/tele/api/catalog/movie?id=$vodId"), emptyList())

    /** Où en est la lecture (le Mac s'en souvient : « Vu », reprise). */
    suspend fun saveProgress(id: Int, positionMs: Long, durationMs: Long, ended: Boolean) {
        postJson("/tele/api/progress", JSONObject().put("id", id).put("position", positionMs)
            .put("duration", durationMs).put("ended", ended))
    }

    private fun sheet(o: JSONObject, seasons: List<Season>) = Sheet(
        name = o.optString("name"), cover = o.optString("cover"), backdrop = o.optString("backdrop"),
        plot = o.optString("plot"), genre = o.optString("genre"), year = o.optString("year"),
        rating = o.optString("rating"), duration = o.optString("duration"), id = o.optInt("id", -1),
        seasons = seasons,
        nextSeason = o.optJSONObject("next")?.optInt("season") ?: 0,
        nextEpisode = o.optJSONObject("next")?.optInt("episode") ?: 0,
    )

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
                it.optString("kind"), it.optBoolean("ready"), it.optBoolean("watched"))
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
