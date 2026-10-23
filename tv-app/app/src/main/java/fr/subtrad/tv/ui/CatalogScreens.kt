package fr.subtrad.tv.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyGridState
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.itemsIndexed
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.tv.material3.Card
import androidx.tv.material3.ExperimentalTvMaterial3Api
import androidx.tv.material3.FilterChip
import androidx.tv.material3.ListItem
import androidx.tv.material3.MaterialTheme
import androidx.tv.material3.Text
import coil.compose.AsyncImage
import fr.subtrad.tv.Category
import fr.subtrad.tv.Episode
import fr.subtrad.tv.Job
import fr.subtrad.tv.Poster
import fr.subtrad.tv.R
import fr.subtrad.tv.Sheet
import fr.subtrad.tv.SubtradClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

/** Une grille d'affiches (séries ou films) avec ses catégories, gardée quand on ouvre une fiche. */
class CatalogState(private val scope: CoroutineScope, val type: String) {
    var client: SubtradClient? = null
    val categories = mutableStateListOf<Category>()
    var category by mutableStateOf("")
        private set
    var query = ""
    val items = mutableStateListOf<Poster>()
    var total by mutableIntStateOf(0)
        private set
    var loading by mutableStateOf(false)
        private set
    var error by mutableStateOf<Throwable?>(null)
        private set
    val gridState = LazyGridState()
    var lastOpened = -1
    private var job: kotlinx.coroutines.Job? = null

    fun ensureLoaded() {
        if (items.isEmpty() && !loading) load(reset = true)
        if (categories.isEmpty()) scope.launch {
            runCatching { client?.categories(type) }.getOrNull()?.let { categories.addAll(it) }
        }
    }

    fun selectCategory(id: String) {
        if (id == category) return
        category = id
        load(reset = true)
    }

    fun search(text: String) {
        query = text
        load(reset = true)
    }

    fun loadMore() {
        if (!loading && items.size < total) load(reset = false)
    }

    fun markReady(id: Int) {
        val i = items.indexOfFirst { it.id == id }
        if (i >= 0) items[i] = items[i].copy(ready = true)
    }

    fun load(reset: Boolean) {
        val c = client ?: return
        job?.cancel()
        loading = true
        error = null
        job = scope.launch {
            try {
                val page = c.posters(type, category, query, if (reset) 0 else items.size)
                if (reset) {
                    items.clear()
                    lastOpened = -1
                    gridState.scrollToItem(0)
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

@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
fun PosterGrid(state: CatalogState, preparing: Map<Int, Job>, onOpen: (Poster) -> Unit) {
    val restore = remember { FocusRequester() }
    LaunchedEffect(state.type) {
        state.ensureLoaded()
        if (state.lastOpened >= 0) runCatching { restore.requestFocus() }
    }
    Column(Modifier.fillMaxSize()) {
        if (state.categories.isNotEmpty()) {
            LazyRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                contentPadding = PaddingValues(vertical = 8.dp),
            ) {
                item {
                    FilterChip(selected = state.category == "", onClick = { state.selectCategory("") }) {
                        Text(stringResource(R.string.all_categories))
                    }
                }
                itemsIndexed(state.categories) { _, cat ->
                    FilterChip(selected = state.category == cat.id, onClick = { state.selectCategory(cat.id) }) {
                        Text(cat.name, maxLines = 1)
                    }
                }
            }
        }
        val status = when {
            state.loading && state.items.isEmpty() -> stringResource(R.string.loading)
            state.error != null -> errorMessage(state.error!!)
            state.items.isEmpty() -> stringResource(R.string.no_results)
            else -> stringResource(R.string.results_count, state.total)
        }
        Text(status, color = if (state.error != null) Color(0xFFFCA5A5) else Color(0xFF9CA3AF),
             modifier = Modifier.padding(vertical = 6.dp))
        LazyVerticalGrid(
            columns = GridCells.Fixed(7),
            state = state.gridState,
            horizontalArrangement = Arrangement.spacedBy(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
            contentPadding = PaddingValues(bottom = 32.dp, top = 4.dp, start = 4.dp, end = 4.dp),
        ) {
            itemsIndexed(state.items, key = { _, p -> "${p.seriesId}-${p.vodId}" }) { index, poster ->
                // Arrivé près de la fin : la suite se charge toute seule.
                if (index >= state.items.size - 14) LaunchedEffect(state.items.size) { state.loadMore() }
                PosterCard(
                    poster = poster,
                    job = preparing[poster.id],
                    onClick = {
                        state.lastOpened = index
                        onOpen(poster)
                    },
                    modifier = if (index == state.lastOpened) Modifier.focusRequester(restore) else Modifier,
                )
            }
        }
    }
}

@Composable
private fun PosterCard(poster: Poster, job: Job?, onClick: () -> Unit, modifier: Modifier = Modifier) {
    Column(modifier) {
        Card(onClick = onClick, modifier = Modifier.fillMaxWidth().aspectRatio(2f / 3f)) {
            Box(Modifier.fillMaxSize().background(Color(0xFF1F2937))) {
                if (poster.cover.isNotBlank()) {
                    AsyncImage(model = poster.cover, contentDescription = poster.name,
                               contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
                } else {
                    Text(poster.name, modifier = Modifier.padding(8.dp), maxLines = 5)
                }
                val badge = when {
                    poster.watched -> stringResource(R.string.badge_watched)
                    poster.ready -> stringResource(R.string.badge_ready)
                    job != null -> stringResource(R.string.badge_preparing, job.percent)
                    else -> null
                }
                if (poster.progress > 0 && !poster.watched) {
                    Box(Modifier.align(Alignment.BottomStart).fillMaxWidth(poster.progress.toFloat())
                        .height(4.dp).background(MaterialTheme.colorScheme.primary))
                }
                badge?.let {
                    Text(it, color = Color.White, modifier = Modifier.align(Alignment.TopEnd).padding(6.dp)
                        .background(Color(0xCC111827), RoundedCornerShape(6.dp)).padding(horizontal = 6.dp, vertical = 2.dp))
                }
            }
        }
        Text(poster.name, maxLines = 2, overflow = TextOverflow.Ellipsis,
             style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp))
        val meta = listOf(poster.year, poster.rating.takeIf { it.isNotBlank() && it != "0" }?.let { "★ $it" })
            .filter { !it.isNullOrBlank() }.joinToString(" · ")
        if (meta.isNotEmpty()) Text(meta, color = Color(0xFF9CA3AF), style = MaterialTheme.typography.labelSmall)
    }
}

/** Affiche, année, genre, note et résumé : en tête des fiches de série, de film et d'épisode. */
@Composable
fun SheetHeader(sheet: Sheet, subtitle: String = "", modifier: Modifier = Modifier, posterWidth: Int = 130) {
    Row(modifier, horizontalArrangement = Arrangement.spacedBy(28.dp)) {
        if (sheet.cover.isNotBlank()) {
            AsyncImage(model = sheet.cover, contentDescription = sheet.name, contentScale = ContentScale.Crop,
                       modifier = Modifier.width(posterWidth.dp).aspectRatio(2f / 3f).clip(RoundedCornerShape(8.dp)))
        }
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(sheet.name, style = MaterialTheme.typography.headlineMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
            if (subtitle.isNotBlank()) Text(subtitle, color = MaterialTheme.colorScheme.primary)
            val meta = listOf(sheet.year, sheet.duration, sheet.genre,
                              sheet.rating.takeIf { it.isNotBlank() && it != "0" }?.let { "★ $it" })
                .filter { !it.isNullOrBlank() }.joinToString(" · ")
            if (meta.isNotEmpty()) Text(meta, color = Color(0xFF9CA3AF))
            if (sheet.plot.isNotBlank()) {
                Text(sheet.plot, color = Color(0xFFD1D5DB), maxLines = 4, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

/** Ce qu'on retient d'une série quand on ouvre un épisode : saison et épisode à retrouver. */
class SeriesMemory {
    var season by mutableIntStateOf(-1)
    var episode = -1
}

@OptIn(ExperimentalTvMaterial3Api::class)
@Composable
fun SeriesScreen(
    client: SubtradClient,
    seriesId: Int,
    name: String,
    memory: SeriesMemory,
    preparing: Map<Int, Job>,
    onEpisode: (Episode, Sheet, String) -> Unit,
) {
    var sheet by remember { mutableStateOf<Sheet?>(null) }
    var error by remember { mutableStateOf<Throwable?>(null) }
    val firstFocus = remember { FocusRequester() }

    // Rechargée à chaque retour : un épisode a pu être préparé ou supprimé entre-temps.
    LaunchedEffect(seriesId) {
        try {
            sheet = client.seriesSheet(seriesId)
            val seasons = sheet!!.seasons
            if (memory.season !in seasons.indices) {
                // Première ouverture : saison et épisode à regarder ensuite.
                memory.season = sheet!!.nextSeason.coerceIn(0, maxOf(0, seasons.lastIndex))
                memory.episode = sheet!!.nextEpisode
            }
        } catch (e: Exception) {
            error = e
        }
    }
    LaunchedEffect(sheet != null) { if (sheet != null) runCatching { firstFocus.requestFocus() } }

    Column(Modifier.fillMaxSize().padding(horizontal = 64.dp, vertical = 36.dp),
           verticalArrangement = Arrangement.spacedBy(16.dp)) {
        val s = sheet
        when {
            s == null && error == null -> Text(stringResource(R.string.loading))
            s == null -> {
                Text(name, style = MaterialTheme.typography.headlineMedium)
                Text(errorMessage(error!!), color = Color(0xFFFCA5A5))
            }
            else -> {
                SheetHeader(s, modifier = Modifier.height(170.dp), posterWidth = 113)
                LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    itemsIndexed(s.seasons) { index, season ->
                        FilterChip(selected = index == memory.season, onClick = { memory.season = index; memory.episode = -1 }) {
                            Text(seasonLabel(season.number, season.name))
                        }
                    }
                }
                val season = s.seasons.getOrNull(memory.season)
                if (season == null || season.episodes.isEmpty()) {
                    Text(stringResource(R.string.no_results), color = Color(0xFF9CA3AF))
                } else {
                    // Ouvre la liste sur l'épisode à regarder (sinon il serait hors de l'écran).
                    val listState = remember(memory.season) {
                        LazyListState(firstVisibleItemIndex = maxOf(memory.episode, 0))
                    }
                    LazyColumn(state = listState, verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        itemsIndexed(season.episodes) { index, episode ->
                            val label = listOf(seasonLabel(season.number, season.name),
                                               stringResource(R.string.episode_label, episode.number), episode.title,
                                               episode.duration)
                                .filter { it.isNotBlank() }.joinToString(" · ")
                            val focus = if (index == maxOf(memory.episode, 0)) Modifier.focusRequester(firstFocus) else Modifier
                            ListItem(
                                selected = false,
                                enabled = episode.id >= 0,
                                onClick = {
                                    memory.episode = index
                                    onEpisode(episode, s, label)
                                },
                                leadingContent = {
                                    Box(Modifier.width(128.dp).aspectRatio(16f / 9f).clip(RoundedCornerShape(6.dp))
                                        .background(Color(0xFF1F2937))) {
                                        if (episode.image.isNotBlank()) {
                                            AsyncImage(model = episode.image, contentDescription = null,
                                                       contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
                                        }
                                        // Avancement de la lecture, en bas de l'image.
                                        val seen = if (episode.watched) 1.0 else episode.progress
                                        if (seen > 0) {
                                            Box(Modifier.align(Alignment.BottomStart).fillMaxWidth(seen.toFloat())
                                                .height(4.dp).background(MaterialTheme.colorScheme.primary))
                                        }
                                    }
                                },
                                headlineContent = {
                                    val title = listOf(stringResource(R.string.episode_label, episode.number), episode.title)
                                        .filter { it.isNotBlank() }.joinToString(" · ")
                                    Text(title, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                },
                                supportingContent = {
                                    val meta = listOf(episode.duration, episode.airDate)
                                        .filter { it.isNotBlank() }.joinToString(" · ")
                                    Text(if (episode.id < 0) stringResource(R.string.episode_unavailable) else meta)
                                },
                                trailingContent = {
                                    val job = preparing[episode.id]
                                    Column(horizontalAlignment = Alignment.End) {
                                        when {
                                            episode.ready -> Text(stringResource(R.string.badge_ready), color = MaterialTheme.colorScheme.primary)
                                            job != null -> Text(stringResource(R.string.badge_preparing, job.percent), color = Color(0xFFFCD34D))
                                        }
                                        when {
                                            episode.watched -> Text(stringResource(R.string.badge_watched), color = Color(0xFF9CA3AF))
                                            episode.progress > 0 -> Text(stringResource(R.string.badge_progress, (episode.progress * 100).toInt()),
                                                                         color = Color(0xFF9CA3AF))
                                        }
                                    }
                                },
                                modifier = focus,
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun seasonLabel(number: Int, providerName: String): String =
    if (number == 0) providerName.ifBlank { stringResource(R.string.season_specials) }
    else stringResource(R.string.season_label, number)
