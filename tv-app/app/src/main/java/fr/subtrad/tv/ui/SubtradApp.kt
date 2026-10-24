package fr.subtrad.tv.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.RectangleShape
import androidx.tv.material3.MaterialTheme
import androidx.tv.material3.Surface
import androidx.tv.material3.SurfaceDefaults
import androidx.tv.material3.darkColorScheme
import fr.subtrad.tv.Prefs
import fr.subtrad.tv.R
import fr.subtrad.tv.SubtradClient
import fr.subtrad.tv.VideoDetails
import java.io.File
import kotlinx.coroutines.launch

sealed interface Screen {
    data object Setup : Screen
    data object Home : Screen
    data class Detail(val id: Int, val name: String, val info: DetailInfo? = null) : Screen
    data class Series(val seriesId: Int, val name: String) : Screen
    data class Player(val video: VideoDetails, val subtitles: File?, val startMs: Long) : Screen
}

@Composable
fun SubtradApp(prefs: Prefs) {
    var client by remember { mutableStateOf<SubtradClient?>(prefs.client()) }
    val stack = remember { mutableStateListOf<Screen>(if (client == null) Screen.Setup else Screen.Home) }
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    // « Saison 6 » (ou le nom donné par le fournisseur pour les épisodes spéciaux).
    fun seasonText(s: fr.subtrad.tv.ReadyEpisode): String =
        if (s.season == 0) s.seasonName.ifBlank { context.getString(R.string.season_specials) }
        else context.getString(R.string.season_label, s.season)
    // La liste et la recherche survivent à l'ouverture d'une vidéo.
    val home = remember { HomeState(scope, prefs) }
    val seriesMemory = remember { mutableMapOf<Int, SeriesMemory>() }

    fun push(screen: Screen) = stack.add(screen)
    fun pop() = stack.removeAt(stack.lastIndex)

    BackHandler(enabled = stack.size > 1) { pop() }

    MaterialTheme(colorScheme = darkColorScheme(primary = Color(0xFFF87171))) {
        Surface(
            modifier = Modifier.fillMaxSize(),
            shape = RectangleShape,
            // Pendant la lecture, fond transparent : la vidéo (SurfaceView) est affichée derrière
            // l'application ; sur les télés Philips (MediaTek), un fond opaque la cachait.
            colors = SurfaceDefaults.colors(
                containerColor = if (stack.last() is Screen.Player) Color.Transparent else Color(0xFF111827),
                contentColor = Color.White,
            ),
        ) {
            when (val screen = stack.last()) {
                Screen.Setup -> SetupScreen(prefs) { connected ->
                    client = connected
                    home.reset(connected)
                    stack.clear()
                    stack.add(Screen.Home)
                }
                Screen.Home -> client?.let { c ->
                    home.attach(c)
                    HomeScreen(
                        state = home,
                        onOpen = { item ->
                            val s = item.series
                            // Épisode de série : la même fiche que depuis l'onglet Séries.
                            if (s == null) push(Screen.Detail(item.id, item.name))
                            else push(Screen.Detail(item.id, s.seriesName, DetailInfo(null, seasonText(s), null, s.episode)))
                        },
                        onOpenPoster = { p ->
                            if (p.seriesId != null) push(Screen.Series(p.seriesId, p.name))
                            else push(Screen.Detail(p.id, p.name, DetailInfo(null, "", p.vodId)))
                        },
                        onSettings = { push(Screen.Setup) },
                    )
                }
                is Screen.Detail -> client?.let { c ->
                    DetailScreen(
                        client = c, id = screen.id, name = screen.name, info = screen.info,
                        onReady = home::markReady,
                        onDeleted = { id -> home.markDeleted(id); pop() },
                        onWatch = { video, file, startMs -> push(Screen.Player(video, file, startMs)) },
                        onBack = { pop() },
                    )
                }
                is Screen.Series -> client?.let { c ->
                    SeriesScreen(
                        client = c, seriesId = screen.seriesId, name = screen.name,
                        memory = seriesMemory.getOrPut(screen.seriesId) { SeriesMemory() },
                        preparing = home.preparing,
                        onEpisode = { episode, sheet, seasonText ->
                            push(Screen.Detail(episode.id, sheet.name, DetailInfo(sheet, seasonText, null, episode)))
                        },
                    )
                }
                is Screen.Player -> PlayerScreen(
                    screen.video, screen.subtitles, screen.startMs,
                    onProgress = { position, duration, ended ->
                        val c = client
                        scope.launch { runCatching { c?.saveProgress(screen.video.id, position, duration, ended) } }
                    },
                    onExit = { pop() },
                )
            }
        }
    }
}
