package fr.gege.tv

import android.content.Context
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.setValue
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

/**
 * Logos nets pour les chaînes : ceux de la playlist sont souvent petits (220 à 256 pixels, en JPEG
 * flou). La collection publique « tv-logos » (github.com/tv-logo/tv-logos) en a de 512 pixels,
 * détourés. Le logo est retrouvé par le nom de la chaîne (« |FR| TF1 FHD » → `tf1-fr.png`) ; sans
 * correspondance, le logo de la playlist reste.
 */
class Logos(context: Context) {
    private val dir = File(context.filesDir, "logos").apply { mkdirs() }

    /** Pays de la collection → noms de fichiers disponibles (sans « .png »). */
    private val known = HashMap<String, Set<String>>()

    /** Change quand la liste est chargée : les logos affichés sont alors redemandés. */
    private var revision by mutableIntStateOf(0)

    /** Charge (ou relit sur la télé) la liste des logos des pays utiles. Sans réseau : rien. */
    suspend fun load() = withContext(Dispatchers.IO) {
        for (country in COUNTRIES.values.toSet()) {
            val file = File(dir, "$country.json")
            val fresh = file.exists() && System.currentTimeMillis() - file.lastModified() < MONTH_MS
            val names = (if (fresh) null else fetch(country)?.also { file.writeText(it) })
                ?: file.takeIf { it.exists() }?.readText()
            names?.let { text ->
                runCatching {
                    val array = JSONArray(text)
                    synchronized(known) {
                        known[country] = (0 until array.length())
                            .map { array.getJSONObject(it).optString("name") }
                            .filter { it.endsWith(".png") }
                            .mapTo(HashSet()) { it.removeSuffix(".png") }
                    }
                }
            }
        }
        withContext(Dispatchers.Main) { revision++ }
    }

    /** Adresse du logo net de cette chaîne, ou null. */
    fun of(channel: Channel): String? {
        if (revision < 0) return null // lecture de `revision` : nouvel affichage une fois la liste chargée
        val (country, slugs) = candidates(channel.name) ?: return null
        val available = synchronized(known) { known[country] } ?: return null
        val suffix = SUFFIX[country] ?: return null
        val found = slugs.firstOrNull { "$it-$suffix" in available } ?: return null
        return "$RAW/$country/$found-$suffix.png"
    }

    private fun fetch(country: String): String? = try {
        val connection = URL("https://api.github.com/repos/tv-logo/tv-logos/contents/countries/$country")
            .openConnection() as HttpURLConnection
        connection.connectTimeout = 10_000
        connection.readTimeout = 20_000
        connection.setRequestProperty("User-Agent", "GegeTV/1.0")
        try {
            if (connection.responseCode == 200) connection.inputStream.bufferedReader().readText() else null
        } finally {
            connection.disconnect()
        }
    } catch (e: Exception) {
        null
    }

    companion object {
        private const val RAW = "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries"
        private const val MONTH_MS = 30L * 24 * 3600 * 1000

        /** Préfixe de la playlist (|FR|, |BE|…) → dossier de la collection. */
        private val COUNTRIES = mapOf(
            "FR" to "france", "BE" to "belgium", "CH" to "switzerland", "SW" to "switzerland",
            "UK" to "united-kingdom", "DE" to "germany", "IT" to "italy", "ES" to "spain",
        )
        private val SUFFIX = mapOf(
            "france" to "fr", "belgium" to "be", "switzerland" to "ch", "united-kingdom" to "uk",
            "germany" to "de", "italy" to "it", "spain" to "es",
        )

        /** Mentions de qualité ou de version à ignorer dans le nom. */
        private val NOISE = Regex(
            """\b(fhd|uhd|hd|sd|4k|8k|hdr|hevc|h265|h264|backup|multi|vip|raw|50fps|60fps|low|ᴴᴰ|ᵁᴴᴰ|⁴ᴷ)\b""",
            RegexOption.IGNORE_CASE,
        )

        /**
         * `|FR| LIGUE 1+ 1 FHD` → ("france", ["ligue-1plus-1", "ligue-1plus"]) : le nom en minuscules,
         * sans accents ni mentions de qualité, « + » écrit « plus » ; puis sans le numéro final.
         */
        fun candidates(name: String): Pair<String, List<String>>? {
            val prefix = Regex("""^\W*([A-Z]{2})\W""").find(name.trim())
            val country = COUNTRIES[prefix?.groupValues?.get(1) ?: "FR"] ?: return null
            val bare = name.trim().removePrefix(prefix?.value ?: "").replace(Regex("""^[\s|:\-]+"""), "")
            val words = normalize(bare).replace("+", " plus ").replace("&", " and ").replace(NOISE, " ")
                .replace(Regex("[^a-z0-9]+"), "-").trim('-')
                .replace(Regex("""(\d)-plus"""), "$1plus").replace(Regex("""plus-(\d)"""), "plus-$1")
            if (words.isEmpty()) return null
            val slugs = linkedSetOf(words)
            Regex("""-\d+$""").find(words)?.let { slugs += words.removeRange(it.range) }
            return country to slugs.toList()
        }
    }
}
