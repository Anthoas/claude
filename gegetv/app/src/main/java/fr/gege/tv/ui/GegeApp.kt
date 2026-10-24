package fr.gege.tv.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.RectangleShape
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import androidx.tv.material3.MaterialTheme
import androidx.tv.material3.Surface
import androidx.tv.material3.SurfaceDefaults
import androidx.tv.material3.Tab
import androidx.tv.material3.TabRow
import androidx.tv.material3.Text
import androidx.tv.material3.darkColorScheme
import androidx.compose.foundation.Image
import fr.gege.tv.Channel
import fr.gege.tv.ChannelStore
import fr.gege.tv.Guide
import fr.gege.tv.Program
import fr.gege.tv.Prefs
import fr.gege.tv.R
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

const val TAB_FAVORITES = 0
const val TAB_SEARCH = 1
const val TAB_SETTINGS = 2

/** Tout l'état de l'application : liste des chaînes, favoris, chargement. */
class GegeState(private val prefs: Prefs, private val store: ChannelStore) {
    val channels = mutableStateListOf<Channel>()
    val favorites = mutableStateListOf<Channel>().apply { addAll(prefs.favorites) }
    var loading by mutableStateOf(false)
    var progress by mutableFloatStateOf(-1f)
    var error by mutableStateOf<String?>(null)
    var savedAt by mutableStateOf(store.savedAt)
    var playlistUrl by mutableStateOf(prefs.playlistUrl)
    var query by mutableStateOf("")
    var tab by mutableIntStateOf(TAB_FAVORITES)

    /** Programme connu de chaque chaîne (par adresse) et l'heure, avancée chaque minute. */
    val programs = mutableStateMapOf<String, List<Program>>()
    var now by mutableLongStateOf(System.currentTimeMillis())
    private val guide = Guide()

    fun programsOf(channel: Channel): List<Program> = programs[channel.url].orEmpty().filter { it.end > now }

    /** Demande le programme de ces chaînes (le guide le garde : pas de nouvelle demande s'il est à jour). */
    suspend fun loadPrograms(list: List<Channel>) = coroutineScope {
        list.map { channel -> async { channel.url to guide.programs(channel) } }.awaitAll()
            .forEach { (url, found) -> programs[url] = found }
    }

    fun isFavorite(channel: Channel) = favorites.any { it.url == channel.url }

    fun toggleFavorite(channel: Channel) {
        val i = favorites.indexOfFirst { it.url == channel.url }
        if (i >= 0) favorites.removeAt(i) else favorites.add(channel)
        prefs.favorites = favorites.toList()
    }

    suspend fun start() {
        channels.addAll(store.cached())
        if (channels.isEmpty() && playlistUrl.isNotBlank()) refresh()
        if (playlistUrl.isBlank()) tab = TAB_SETTINGS
    }

    suspend fun refresh(newUrl: String? = null) {
        if (loading) return
        newUrl?.let { prefs.playlistUrl = it; playlistUrl = it.trim() }
        if (playlistUrl.isBlank()) return
        loading = true
        error = null
        progress = -1f
        try {
            val fresh = store.refresh(playlistUrl) { progress = it }
            channels.clear()
            channels.addAll(fresh)
            savedAt = store.savedAt
        } catch (e: Exception) {
            error = e.message ?: e.javaClass.simpleName
        } finally {
            loading = false
        }
    }
}

@Composable
fun GegeApp(prefs: Prefs, store: ChannelStore) {
    val scope = rememberCoroutineScope()
    val state = remember { GegeState(prefs, store) }
    var playing by remember { mutableStateOf<Channel?>(null) }

    LaunchedEffect(Unit) { state.start() }
    // Chaque minute : l'heure avance (barres d'avancement) et le programme des favoris est vérifié.
    LaunchedEffect(Unit) {
        while (true) {
            state.now = System.currentTimeMillis()
            state.loadPrograms(state.favorites.toList() + listOfNotNull(playing))
            delay(60_000)
        }
    }
    BackHandler(enabled = playing != null) { playing = null }

    MaterialTheme(colorScheme = darkColorScheme(primary = Color(0xFFE8B04B))) {
        Surface(
            modifier = Modifier.fillMaxSize(),
            shape = RectangleShape,
            colors = SurfaceDefaults.colors(containerColor = Color(0xFF16201A), contentColor = Color.White),
        ) {
            val channel = playing
            if (channel != null) {
                PlayerScreen(
                    channel = channel,
                    isFavorite = state.isFavorite(channel),
                    programs = state.programsOf(channel),
                    onOpen = { scope.launch { state.loadPrograms(listOf(channel)) } },
                    onToggleFavorite = { state.toggleFavorite(channel) },
                    onExit = { playing = null },
                )
            } else {
                Home(state, onPlay = { playing = it }, onRefresh = { url -> scope.launch { state.refresh(url) } })
            }
        }
    }
}

@Composable
private fun Home(state: GegeState, onPlay: (Channel) -> Unit, onRefresh: (String?) -> Unit) {
    val tabFocus = remember { FocusRequester() }
    LaunchedEffect(Unit) { runCatching { tabFocus.requestFocus() } }
    Column(Modifier.fillMaxSize().padding(horizontal = 48.dp, vertical = 24.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(20.dp)) {
            Image(painterResource(R.mipmap.ic_launcher), contentDescription = null, modifier = Modifier.size(52.dp))
            Text("GégéTV", style = MaterialTheme.typography.headlineMedium)
            Spacer(Modifier.width(12.dp))
            TabRow(selectedTabIndex = state.tab) {
                listOf("★ Favoris", "Rechercher", "Réglages").forEachIndexed { index, label ->
                    Tab(
                        selected = index == state.tab,
                        onFocus = { state.tab = index },
                        modifier = if (index == state.tab) Modifier.focusRequester(tabFocus) else Modifier,
                    ) { Text(label, modifier = Modifier.padding(horizontal = 18.dp, vertical = 8.dp)) }
                }
            }
        }
        Spacer(Modifier.height(16.dp))
        if (state.loading) {
            Text(if (state.progress >= 0) "Chargement des chaînes… ${(state.progress * 100).toInt()} %"
                 else "Chargement des chaînes…", color = Color(0xFFD1D5DB))
            ProgressBar(state.progress.takeIf { it >= 0 }?.toDouble(), Modifier.padding(vertical = 8.dp))
        }
        when (state.tab) {
            TAB_FAVORITES -> FavoritesScreen(state, onPlay)
            TAB_SEARCH -> SearchScreen(state, onPlay)
            else -> SettingsScreen(state, onRefresh)
        }
    }
}
