package fr.gege.tv

import android.content.Context
import org.json.JSONArray

/** Réglages gardés sur la télé (espace privé de l'application) : les sources et leurs favoris. */
class Prefs(private val context: Context) {
    private val prefs = context.getSharedPreferences("gegetv", Context.MODE_PRIVATE)

    val sources = SourceStore(context)

    /** Favoris de cette source. */
    fun favorites(source: Source) = Favorites(context, source.id)

    /** Lien de playlist des premières versions (remplacé par les sources). */
    private val legacyPlaylist: String get() = prefs.getString("playlist", "") ?: ""

    /** Favoris des toutes premières versions (rangés ici) : repris une fois, puis laissés tels quels. */
    val legacyFavorites: List<Channel>
        get() = try {
            val array = JSONArray(prefs.getString("favorites", "[]"))
            (0 until array.length()).map { Channel.fromJson(array.getJSONObject(it)) }
        } catch (e: Exception) {
            emptyList()
        }

    /**
     * Première ouverture de cette version : l'ancien lien de playlist devient la source « Ma source »,
     * avec sa liste de chaînes et ses favoris. Ne fait rien s'il y a déjà des sources.
     */
    fun migrate(store: ChannelStore) {
        if (sources.sources.isNotEmpty()) return
        val source = Source.fromPlaylistLink(legacyPlaylist, "Ma source") ?: return
        sources.add(source)
        store.adoptLegacy(source)
        Favorites.adoptLegacy(context, source.id)
        val favorites = favorites(source)
        if (favorites.load().isEmpty() && legacyFavorites.isNotEmpty()) favorites.save(legacyFavorites)
    }

    /**
     * Source préinstallée dans cette version de l'appli (voir `source-preinstallee.properties`) :
     * ajoutée et utilisée au premier lancement, une seule fois (supprimée ensuite, elle ne revient pas).
     */
    fun applyPreset() {
        val server = BuildConfig.PRESET_SERVER
        if (server.isBlank() || prefs.getBoolean("preset_done", false)) return
        val source = Source.new(BuildConfig.PRESET_NAME.ifBlank { "Ma source" }, server,
                                BuildConfig.PRESET_USERNAME, BuildConfig.PRESET_PASSWORD)
        val same = sources.sources.firstOrNull { it.server == source.server && it.username == source.username }
        if (same == null) sources.add(source)
        sources.activeId = (same ?: source).id
        prefs.edit().putBoolean("preset_done", true).commit()
    }

    /** Lien `get.php` donné par un ordinateur (adb) : ajouté comme source et utilisé. */
    fun provision(link: String) {
        val source = Source.fromPlaylistLink(link, "Source ${sources.sources.size + 1}") ?: return
        if (sources.sources.any { it.server == source.server && it.username == source.username }) return
        sources.add(source)
        sources.activeId = source.id
    }
}
