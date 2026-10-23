package fr.subtrad.tv.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.tv.material3.Button
import androidx.tv.material3.ListItem
import androidx.tv.material3.MaterialTheme
import androidx.tv.material3.OutlinedButton
import androidx.tv.material3.Tab
import androidx.tv.material3.TabRow
import androidx.tv.material3.Text
import fr.subtrad.tv.Prefs
import fr.subtrad.tv.R
import fr.subtrad.tv.SubtradClient
import fr.subtrad.tv.VideoItem
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private const val TAB_READY = 0
private val TAB_KINDS = listOf("", "film", "serie")

/** Liste et recherche de l'accueil, gardées pendant qu'une vidéo est ouverte. */
class HomeState(private val scope: CoroutineScope, private val prefs: Prefs) {
    private var client: SubtradClient? = null
    private var loadJob: Job? = null
    val items = mutableStateListOf<VideoItem>()
    val listState = LazyListState()
    var tab by mutableIntStateOf(TAB_READY)
        private set
    var query by mutableStateOf("")
    var total by mutableIntStateOf(0)
        private set
    var loading by mutableStateOf(false)
        private set
    var error by mutableStateOf<Throwable?>(null)
        private set
    var lastOpened = -1 // ligne à qui rendre le focus au retour d'une vidéo
    val recent = mutableStateListOf<String>().apply { addAll(prefs.recentSearches) }
    /** Catalogue Xtream Codes : null = pas encore vérifié, false = absent (listes simples). */
    var catalog by mutableStateOf<Boolean?>(null)
        private set
    val seriesGrid = CatalogState(scope, "series")
    val moviesGrid = CatalogState(scope, "movie")

    /** Grille de l'onglet affiché (null : onglet « prêtes » ou pas de catalogue). */
    fun grid(): CatalogState? = when {
        catalog != true -> null
        tab == 1 -> moviesGrid
        tab == 2 -> seriesGrid
        else -> null
    }
    /** Préparations en cours sur le Mac, par vidéo (suivies même fiche fermée). */
    val preparing = mutableStateMapOf<Int, fr.subtrad.tv.Job>()

    /** Met à jour les préparations ; une vidéo qui vient d'être prête passe en « ✓ ». */
    suspend fun refreshJobs(): Boolean {
        val c = client ?: return false
        val jobs = try { c.jobs() } catch (e: Exception) { return preparing.isNotEmpty() }
        val running = jobs.filter { it.running }.associateBy { it.videoId }
        val finished = preparing.keys - running.keys
        preparing.clear()
        preparing.putAll(running)
        for (id in finished) {
            if (jobs.any { it.videoId == id && it.state == "done" }) markReady(id)
        }
        if (finished.isNotEmpty() && tab == TAB_READY) load()
        return running.isNotEmpty()
    }

    /** Lignes « en préparation » ajoutées en tête de « Siap ditonton ». */
    fun preparingItems(): List<VideoItem> =
        if (tab != TAB_READY) emptyList()
        else preparing.values.filter { j -> items.none { it.id == j.videoId } }
            .map { VideoItem(it.videoId, it.title, "", "", ready = false) }

    fun searchRecent(query: String) {
        this.query = query
        search()
    }

    fun attach(c: SubtradClient) {
        client = c
        seriesGrid.client = c
        moviesGrid.client = c
    }

    fun reset(c: SubtradClient) {
        attach(c)
        catalog = null
        for (g in listOf(seriesGrid, moviesGrid)) {
            g.items.clear()
            g.categories.clear()
        }
        tab = TAB_READY
        items.clear()
        lastOpened = -1
    }

    /** À chaque affichage de l'accueil : « Siap ditonton » est rechargé (une vidéo a pu être préparée). */
    fun onShown() {
        if (catalog == null) scope.launch { catalog = runCatching { client?.catalogAvailable() }.getOrNull() ?: false }
        if (tab == TAB_READY || (grid() == null && items.isEmpty())) load()
    }

    fun selectTab(index: Int) {
        if (index == tab) return
        tab = index
        lastOpened = -1
        if (grid() == null) load()
    }

    fun search() {
        if (tab == TAB_READY) tab = 1
        lastOpened = -1
        if (query.isNotBlank()) {
            prefs.addRecentSearch(query)
            recent.clear()
            recent.addAll(prefs.recentSearches)
        }
        val g = grid()
        if (g != null) g.search(query) else load()
    }

    fun loadMore() = load(append = true)

    fun markReady(id: Int) {
        moviesGrid.markReady(id)
        val i = items.indexOfFirst { it.id == id }
        if (i >= 0) items[i] = items[i].copy(ready = true)
    }

    fun markDeleted(id: Int) {
        val i = items.indexOfFirst { it.id == id }
        if (i < 0) return
        if (tab == TAB_READY) {
            items.removeAt(i)
            total = (total - 1).coerceAtLeast(0)
            lastOpened = if (items.isEmpty()) -1 else i.coerceAtMost(items.lastIndex)
        } else {
            items[i] = items[i].copy(ready = false)
        }
    }

    private fun load(append: Boolean = false) {
        val c = client ?: return
        loadJob?.cancel()
        loading = true
        error = null
        loadJob = scope.launch {
            try {
                val page = if (tab == TAB_READY) c.ready()
                           else c.search(query, TAB_KINDS[tab], if (append) items.size else 0)
                if (!append) {
                    items.clear()
                    listState.scrollToItem(0)
                }
                items.addAll(page.items)
                total = page.total
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                error = e
            } finally {
                loading = false
            }
        }
    }
}

@Composable
fun HomeScreen(
    state: HomeState,
    onOpen: (VideoItem) -> Unit,
    onOpenPoster: (fr.subtrad.tv.Poster) -> Unit,
    onSettings: () -> Unit,
) {
    val tabFocus = remember { FocusRequester() }
    val rowFocus = remember { FocusRequester() }
    val tabs = listOf(R.string.tab_ready, R.string.tab_films, R.string.tab_series)

    LaunchedEffect(Unit) {
        state.onShown()
        runCatching { if (state.lastOpened >= 0) rowFocus.requestFocus() else tabFocus.requestFocus() }
    }
    // Avancement des préparations : toutes les 3 s s'il y en a, sinon toutes les 20 s.
    LaunchedEffect(Unit) {
        while (true) {
            delay(if (state.refreshJobs()) 3_000 else 20_000)
        }
    }

    Column(Modifier.fillMaxSize().padding(horizontal = 48.dp, vertical = 27.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            TabRow(selectedTabIndex = state.tab) {
                tabs.forEachIndexed { index, label ->
                    Tab(
                        selected = index == state.tab,
                        onFocus = { state.selectTab(index) },
                        modifier = if (index == state.tab) Modifier.focusRequester(tabFocus) else Modifier,
                    ) {
                        Text(stringResource(label), modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp))
                    }
                }
            }
            TvTextField(
                value = state.query, onValueChange = { state.query = it },
                placeholder = stringResource(R.string.search_hint),
                imeAction = ImeAction.Search, onSubmit = state::search,
                modifier = Modifier.weight(1f),
            )
            Button(onClick = state::search) { Text(stringResource(R.string.search_button)) }
            OutlinedButton(onClick = onSettings) { Text(stringResource(R.string.settings_button)) }
        }

        if (state.recent.isNotEmpty()) {
            Row(Modifier.padding(top = 12.dp), verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(stringResource(R.string.recent_searches), color = Color(0xFF9CA3AF))
                state.recent.forEach { q ->
                    OutlinedButton(onClick = { state.searchRecent(q) }) { Text(q, maxLines = 1) }
                }
            }
        }

        val grid = state.grid()
        if (grid != null) {
            PosterGrid(grid, state.preparing, onOpenPoster)
            return@Column
        }

        val status = when {
            state.loading && state.items.isEmpty() -> stringResource(R.string.loading)
            state.error != null -> errorMessage(state.error!!)
            state.items.isEmpty() && state.tab == TAB_READY -> stringResource(R.string.nothing_ready)
            state.items.isEmpty() -> stringResource(R.string.no_results)
            else -> stringResource(R.string.results_count, state.total)
        }
        Row(Modifier.padding(vertical = 12.dp), verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            Text(status, color = if (state.error != null) Color(0xFFFCA5A5) else Color(0xFF9CA3AF))
            if (state.error != null) {
                OutlinedButton(onClick = state::onShown) { Text(stringResource(R.string.retry)) }
            }
        }

        LazyColumn(state = state.listState, verticalArrangement = Arrangement.spacedBy(4.dp)) {
            items(state.preparingItems(), key = { "p${it.id}" }) { item ->
                ListItem(
                    selected = false,
                    onClick = { onOpen(item) },
                    headlineContent = { Text(item.name, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                    supportingContent = { Text(stringResource(R.string.preparing_hint), maxLines = 1) },
                    trailingContent = { PreparingBadge(state.preparing[item.id]) },
                )
            }
            itemsIndexed(state.items, key = { _, item -> item.id }) { index, item ->
                ListItem(
                    selected = false,
                    onClick = {
                        state.lastOpened = index
                        onOpen(item)
                    },
                    headlineContent = { Text(item.name, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                    supportingContent = { Text(item.group, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                    trailingContent = {
                        val job = state.preparing[item.id]
                        when {
                            item.watched -> Text(stringResource(R.string.badge_watched), color = Color(0xFF9CA3AF))
                            item.ready -> Text(stringResource(R.string.badge_ready), color = MaterialTheme.colorScheme.primary)
                            job != null -> PreparingBadge(job)
                        }
                    },
                    modifier = if (index == state.lastOpened) Modifier.focusRequester(rowFocus) else Modifier,
                )
            }
            if (state.tab != TAB_READY && state.items.size < state.total) {
                item {
                    OutlinedButton(onClick = state::loadMore, enabled = !state.loading,
                                   modifier = Modifier.padding(vertical = 8.dp)) {
                        Text(stringResource(R.string.load_more))
                    }
                }
            }
        }
    }
}

@Composable
private fun PreparingBadge(job: fr.subtrad.tv.Job?) {
    Text(stringResource(R.string.badge_preparing, job?.percent ?: 0), color = Color(0xFFFCD34D))
}
