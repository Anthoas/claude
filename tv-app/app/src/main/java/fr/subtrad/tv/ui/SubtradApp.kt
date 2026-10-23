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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.RectangleShape
import androidx.tv.material3.MaterialTheme
import androidx.tv.material3.Surface
import androidx.tv.material3.SurfaceDefaults
import androidx.tv.material3.darkColorScheme
import fr.subtrad.tv.Prefs
import fr.subtrad.tv.SubtradClient
import fr.subtrad.tv.VideoDetails
import java.io.File

sealed interface Screen {
    data object Setup : Screen
    data object Home : Screen
    data class Detail(val id: Int, val name: String) : Screen
    data class Player(val video: VideoDetails, val subtitles: File) : Screen
}

@Composable
fun SubtradApp(prefs: Prefs) {
    var client by remember { mutableStateOf<SubtradClient?>(prefs.client()) }
    val stack = remember { mutableStateListOf<Screen>(if (client == null) Screen.Setup else Screen.Home) }
    val scope = rememberCoroutineScope()
    // La liste et la recherche survivent à l'ouverture d'une vidéo.
    val home = remember { HomeState(scope) }

    fun push(screen: Screen) = stack.add(screen)
    fun pop() = stack.removeAt(stack.lastIndex)

    BackHandler(enabled = stack.size > 1) { pop() }

    MaterialTheme(colorScheme = darkColorScheme(primary = Color(0xFFF87171))) {
        Surface(
            modifier = Modifier.fillMaxSize(),
            shape = RectangleShape,
            colors = SurfaceDefaults.colors(containerColor = Color(0xFF111827), contentColor = Color.White),
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
                        onOpen = { item -> push(Screen.Detail(item.id, item.name)) },
                        onSettings = { push(Screen.Setup) },
                    )
                }
                is Screen.Detail -> client?.let { c ->
                    DetailScreen(
                        client = c, id = screen.id, name = screen.name,
                        onReady = home::markReady,
                        onWatch = { video, file -> push(Screen.Player(video, file)) },
                        onBack = { pop() },
                    )
                }
                is Screen.Player -> PlayerScreen(screen.video, screen.subtitles, onExit = { pop() })
            }
        }
    }
}
