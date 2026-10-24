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
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusProperties
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.foundation.border
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.RectangleShape
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import androidx.tv.material3.MaterialTheme
import androidx.tv.material3.Surface
import androidx.tv.material3.SurfaceDefaults
import androidx.tv.material3.Tab
import androidx.tv.material3.TabDefaults
import androidx.tv.material3.TabRow
import androidx.tv.material3.TabRowDefaults
import androidx.tv.material3.Text
import androidx.tv.material3.darkColorScheme
import androidx.compose.foundation.Image
import fr.gege.tv.Channel
import fr.gege.tv.ChannelStore
import fr.gege.tv.Guide
import fr.gege.tv.Logos
import fr.gege.tv.Program
import fr.gege.tv.normalize
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

private const val WEEK_MS = 7 * 24 * 3600 * 1000L
private const val SPLASH_MS = 1_500L
private const val ERROR_MS = 4_000L

/** Tout l'état de l'application : liste des chaînes, favoris, chargement. */
class GegeState(private val prefs: Prefs, private val store: ChannelStore) {
    val channels = mutableStateListOf<Channel>()
    val favorites = mutableStateListOf<Channel>().apply { addAll(prefs.favorites.load { prefs.legacyFavorites }) }
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

    /** Dernière chaîne regardée : le sélecteur y revient en quittant la lecture. */
    var lastPlayed by mutableStateOf<Channel?>(null)

    /** Chaîne pour laquelle la question « ajouter / retirer des favoris ? » est posée. */
    var asking by mutableStateOf<Channel?>(null)

    fun isFavorite(channel: Channel) = favorites.any { it.url == channel.url }

    /** Adresses des chaînes de la liste chargée, pour repérer les favoris devenus introuvables. */
    private var known by mutableStateOf(emptySet<String>())

    /** Favori absent de la liste chargée (le fournisseur l'a retiré) : affiché, jamais effacé. */
    fun isUnavailable(channel: Channel) = known.isNotEmpty() && channel.url !in known

    /**
     * Après chargement de la liste : un favori dont l'adresse a changé (le fournisseur a renuméroté
     * ses chaînes) est retrouvé par son nom et mis à jour. Rien n'est jamais supprimé.
     */
    private fun repairFavorites() {
        known = channels.mapTo(HashSet()) { it.url }
        if (known.isEmpty()) return
        val byName = HashMap<String, Channel>()
        channels.forEach { byName.putIfAbsent(normalize(it.name).trim(), it) }
        var changed = false
        favorites.toList().forEachIndexed { i, fav ->
            if (fav.url in known) return@forEachIndexed
            val found = byName[normalize(fav.name).trim()] ?: return@forEachIndexed
            if (favorites.none { it.url == found.url }) { // pas de doublon si elle est déjà en favori
                favorites[i] = found
                changed = true
            }
        }
        if (changed) prefs.favorites.save(favorites.toList())
    }

    fun toggleFavorite(channel: Channel) {
        val i = favorites.indexOfFirst { it.url == channel.url }
        if (i >= 0) favorites.removeAt(i) else favorites.add(channel)
        prefs.favorites.save(favorites.toList(), removedLast = i >= 0 && favorites.isEmpty())
    }

    /** Écran d'accueil (sanglier) affiché au démarrage, pendant les mises à jour. */
    var starting by mutableStateOf(true)
    var loadingPrograms by mutableStateOf(false)

    /**
     * Démarrage, pendant l'écran d'accueil : la liste des chaînes est rechargée si elle a plus
     * d'une semaine (ou s'il n'y en a pas encore ; environ 2 min), puis le programme des favoris
     * est mis à jour (quelques secondes).
     */
    suspend fun start() {
        val began = System.currentTimeMillis()
        channels.addAll(store.cached())
        repairFavorites()
        if (playlistUrl.isBlank()) tab = TAB_SETTINGS
        else if (channels.isEmpty() || System.currentTimeMillis() - store.savedAt > WEEK_MS) refresh()
        if (favorites.isNotEmpty()) {
            loadingPrograms = true
            try { loadPrograms(favorites.toList()) } finally { loadingPrograms = false }
        }
        val shown = System.currentTimeMillis() - began
        if (error != null) delay(ERROR_MS) // le temps de lire le message ; on continue avec l'ancienne liste
        else if (shown < SPLASH_MS) delay(SPLASH_MS - shown)
        starting = false
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
            repairFavorites()
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
    val context = LocalContext.current
    val logos = remember { Logos(context) }
    LaunchedEffect(Unit) { logos.load() }
    // Chaque minute : l'heure avance (barres d'avancement) et le programme des favoris est vérifié.
    LaunchedEffect(Unit) {
        while (true) {
            state.now = System.currentTimeMillis()
            state.loadPrograms(state.favorites.toList() + listOfNotNull(playing))
            delay(60_000)
        }
    }
    BackHandler(enabled = playing != null) { state.lastPlayed = playing; playing = null }

    CompositionLocalProvider(LocalLogos provides logos) {
    MaterialTheme(colorScheme = darkColorScheme(primary = Color(0xFFE8B04B))) {
        Surface(
            modifier = Modifier.fillMaxSize(),
            shape = RectangleShape,
            // Pendant la lecture, fond transparent : la vidéo est affichée derrière l'application.
            colors = SurfaceDefaults.colors(
                containerColor = if (playing != null) Color.Transparent else Color(0xFF16201A),
                contentColor = Color.White,
            ),
        ) {
            val channel = playing
            if (state.starting) {
                SplashScreen(state)
            } else if (channel != null) {
                // Chaîne favorite : haut / bas passent à la précédente / suivante (en boucle).
                val index = state.favorites.indexOfFirst { it.url == channel.url }
                val zap: ((Int) -> Unit)? = if (index < 0 || state.favorites.size < 2) null else { step ->
                    val n = state.favorites.size
                    playing = state.favorites[(index + step + n) % n]
                }
                key(channel.url) { // nouvelle chaîne : lecteur et bandeau repartent de zéro
                    PlayerScreen(
                        channel = channel,
                        programs = state.programsOf(channel),
                        onOpen = { scope.launch { state.loadPrograms(listOf(channel)) } },
                        onExit = { state.lastPlayed = playing; playing = null },
                        onPrevious = zap?.let { { it(-1) } },
                        onNext = zap?.let { { it(1) } },
                    )
                }
            } else {
                Home(state, onPlay = { playing = it }, onRefresh = { url -> scope.launch { state.refresh(url) } })
                // Appui long sur une chaîne : on demande avant d'ajouter ou de retirer un favori.
                state.asking?.let { asked ->
                    val remove = state.isFavorite(asked)
                    ConfirmDialog(
                        question = if (remove) "Voulez-vous retirer « ${asked.name} » des favoris ?"
                                   else "Voulez-vous ajouter « ${asked.name} » à la liste des favoris ?",
                        onYes = {
                            state.toggleFavorite(asked)
                            state.asking = null
                            if (!remove) scope.launch { state.loadPrograms(listOf(asked)) }
                        },
                        onNo = { state.asking = null },
                    )
                }
            }
        }
    }
    }
}

@OptIn(ExperimentalComposeUiApi::class)
@Composable
private fun Home(state: GegeState, onPlay: (Channel) -> Unit, onRefresh: (String?) -> Unit) {
    val tabFocus = remember { FocusRequester() }
    val channelFocus = remember { FocusRequester() }
    var focusedTab by remember { mutableIntStateOf(-1) } // onglet entouré du liseré rouge
    // Sélecteur de départ : sur une chaîne des favoris s'il y en a, sinon sur l'onglet.
    LaunchedEffect(Unit) {
        val onChannel = state.tab == TAB_FAVORITES && state.favorites.isNotEmpty() &&
            runCatching { channelFocus.requestFocus() }.isSuccess
        if (!onChannel) runCatching { tabFocus.requestFocus() }
    }
    Column(Modifier.fillMaxSize().padding(horizontal = 48.dp, vertical = 24.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(20.dp)) {
            Image(painterResource(R.mipmap.ic_launcher), contentDescription = null, modifier = Modifier.size(52.dp))
            Text("GégéTV", style = MaterialTheme.typography.headlineMedium)
            Spacer(Modifier.width(12.dp))
            TabRow(
                selectedTabIndex = state.tab,
                // En arrivant sur les onglets (par exemple en montant depuis une chaîne), le
                // sélecteur va sur l'onglet affiché, pas sur celui qui se trouve juste au-dessus.
                modifier = Modifier.focusProperties { enter = { tabFocus } },
                indicator = { positions, rowFocused ->
                    positions.getOrNull(state.tab)?.let {
                        TabRowDefaults.PillIndicator(currentTabPosition = it, doesTabRowHaveFocus = rowFocused,
                                                     activeColor = Color(0xFF2B3830), inactiveColor = Color(0xFF2B3830))
                    }
                },
            ) {
                listOf("★ Favoris", "Rechercher", "Réglages").forEachIndexed { index, label ->
                    Tab(
                        selected = index == state.tab,
                        onFocus = { state.tab = index },
                        colors = TabDefaults.pillIndicatorTabColors(focusedContentColor = Color.White,
                                                                    selectedContentColor = Color.White),
                        modifier = (if (index == state.tab) Modifier.focusRequester(tabFocus) else Modifier)
                            .onFocusChanged { focusedTab = if (it.isFocused) index else if (focusedTab == index) -1 else focusedTab }
                            .then(if (focusedTab == index) Modifier.border(3.dp, SELECT_RED, CircleShape) else Modifier),
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
            TAB_FAVORITES -> FavoritesScreen(state, onPlay, channelFocus)
            TAB_SEARCH -> SearchScreen(state, onPlay)
            else -> SettingsScreen(state, onRefresh)
        }
    }
}

/** Écran d'accueil : la tête de sanglier, « GégéTV », et l'avancement de la mise à jour s'il y en a une. */
@Composable
private fun SplashScreen(state: GegeState) {
    Column(
        Modifier.fillMaxSize().padding(48.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Image(painterResource(R.drawable.sanglier), contentDescription = null, modifier = Modifier.size(260.dp))
        Spacer(Modifier.height(24.dp))
        Text("GégéTV", style = MaterialTheme.typography.displayMedium)
        Spacer(Modifier.height(32.dp))
        Column(Modifier.width(560.dp).height(90.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            val error = state.error
            when {
                error != null -> {
                    Text("Mise à jour impossible ($error).", color = Color(0xFFFCA5A5))
                    Text("La liste déjà enregistrée sur la télé est utilisée.", color = Color(0xFFD1D5DB))
                }
                state.loading -> {
                    Text(if (state.progress >= 0) "Mise à jour de la liste des chaînes… ${(state.progress * 100).toInt()} %"
                         else "Mise à jour de la liste des chaînes…", color = Color(0xFFD1D5DB))
                    ProgressBar(state.progress.takeIf { it >= 0 }?.toDouble(), Modifier.padding(top = 12.dp))
                }
                state.loadingPrograms -> Text("Mise à jour des programmes…", color = Color(0xFFD1D5DB))
            }
        }
    }
}
