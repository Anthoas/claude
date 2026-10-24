package fr.gege.tv

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.util.UUID

/** Une source Xtream Codes : un nom choisi, l'adresse du serveur, l'identifiant et le mot de passe. */
data class Source(
    val id: String,
    val name: String,
    val server: String, // http(s)://hôte[:port], sans « / » final
    val username: String,
    val password: String,
) {
    /** Hôte seul (sans identifiant ni mot de passe), pour l'affichage. */
    val host: String get() = server.substringAfter("://").substringBefore('/')

    fun toJson(): JSONObject = JSONObject().put("id", id).put("name", name).put("server", server)
        .put("username", username).put("password", password)

    /** Adresse d'une chaîne en direct : serveur/identifiant/mot de passe/numéro. */
    fun streamUrl(streamId: String) = "$server/${enc(username)}/${enc(password)}/$streamId"

    /** Réponse JSON de `player_api.php` (action vide : vérification du compte). */
    suspend fun api(action: String? = null): String = withContext(Dispatchers.IO) {
        val query = buildList {
            add("username=${enc(username)}")
            add("password=${enc(password)}")
            action?.let { add("action=$it") }
        }.joinToString("&")
        val connection = URL("$server/player_api.php?$query").openConnection() as HttpURLConnection
        connection.connectTimeout = 15_000
        connection.readTimeout = 60_000
        connection.setRequestProperty("User-Agent", "GegeTV/1.0")
        try {
            if (connection.responseCode !in 200..299) throw HttpStatus(connection.responseCode)
            connection.inputStream.bufferedReader().readText()
        } finally {
            connection.disconnect()
        }
    }

    /** null si le serveur accepte l'identifiant et le mot de passe, sinon un message clair. */
    suspend fun check(): String? = try {
        val info = JSONObject(api()).optJSONObject("user_info")
        when {
            info == null -> "ce serveur ne répond pas comme un serveur Xtream Codes"
            info.optInt("auth") != 1 -> "identifiant ou mot de passe refusé"
            info.optString("status").let { it.isNotBlank() && it != "Active" } -> "abonnement ${info.optString("status")}"
            else -> null
        }
    } catch (e: HttpStatus) {
        // Beaucoup de serveurs répondent 401, 403 ou 404 à un mauvais identifiant.
        if (e.code in listOf(401, 403, 404)) "identifiant ou mot de passe refusé (ou adresse du serveur incorrecte)"
        else "le serveur a répondu ${e.code}"
    } catch (e: Exception) {
        "serveur injoignable (${e.message ?: e.javaClass.simpleName})"
    }

    companion object {
        fun fromJson(o: JSONObject) = Source(o.optString("id"), o.optString("name"), o.optString("server"),
                                             o.optString("username"), o.optString("password"))

        fun new(name: String, server: String, username: String, password: String) =
            Source(UUID.randomUUID().toString().take(8), name.trim(), normalizeServer(server),
                   username.trim(), password.trim())

        /** « monserveur.com:8080 » → « http://monserveur.com:8080 » (sans « / » ni chemin final). */
        fun normalizeServer(server: String): String {
            val s = server.trim().trimEnd('/')
            val withScheme = if (s.startsWith("http://") || s.startsWith("https://")) s else "http://$s"
            val scheme = withScheme.substringBefore("://")
            return "$scheme://" + withScheme.substringAfter("://").substringBefore('/')
        }

        /** Lien `…/get.php?username=…&password=…` (ancienne version de GégéTV) → source, ou null. */
        fun fromPlaylistLink(link: String, name: String): Source? = try {
            val url = URL(link.trim())
            val params = url.query.orEmpty().split('&').associate {
                it.substringBefore('=') to java.net.URLDecoder.decode(it.substringAfter('=', ""), "UTF-8")
            }
            val user = params["username"].orEmpty()
            val pass = params["password"].orEmpty()
            if (user.isBlank() || pass.isBlank()) null
            else new(name, "${url.protocol}://${url.authority}", user, pass)
        } catch (e: Exception) {
            null
        }

        private fun enc(text: String) = URLEncoder.encode(text, "UTF-8")
    }
}

/** Réponse HTTP autre que 2xx du serveur. */
class HttpStatus(val code: Int) : IOException("le serveur a répondu $code")

/** Les sources enregistrées sur la télé (espace privé de l'application) et celle qui est utilisée. */
class SourceStore(context: Context) {
    private val prefs = context.getSharedPreferences("sources", Context.MODE_PRIVATE)

    var sources: List<Source>
        get() = try {
            val array = JSONArray(prefs.getString("list", "[]"))
            (0 until array.length()).map { Source.fromJson(array.getJSONObject(it)) }
        } catch (e: Exception) {
            emptyList()
        }
        private set(value) {
            val array = JSONArray().apply { value.forEach { put(it.toJson()) } }
            prefs.edit().putString("list", array.toString()).commit()
        }

    var activeId: String
        get() = prefs.getString("active", "") ?: ""
        set(value) { prefs.edit().putString("active", value).commit() }

    val active: Source? get() = sources.firstOrNull { it.id == activeId } ?: sources.firstOrNull()

    fun add(source: Source) {
        sources = sources + source
        if (sources.size == 1) activeId = source.id
    }

    /** Retire la source ; si c'était celle utilisée, la suivante le devient. */
    fun remove(id: String) {
        sources = sources.filter { it.id != id }
        if (activeId == id) activeId = sources.firstOrNull()?.id ?: ""
    }
}
