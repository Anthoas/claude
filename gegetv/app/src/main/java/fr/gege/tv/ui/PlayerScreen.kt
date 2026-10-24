package fr.gege.tv.ui

import androidx.annotation.OptIn
import androidx.compose.foundation.background
import androidx.compose.foundation.focusable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.input.key.type
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.DefaultRenderersFactory
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.ui.PlayerView
import androidx.tv.material3.Button
import androidx.tv.material3.MaterialTheme
import androidx.tv.material3.OutlinedButton
import androidx.tv.material3.Text
import fr.gege.tv.Channel
import kotlinx.coroutines.delay

private const val OVERLAY_MS = 6_000L

/**
 * Une chaîne en direct, en plein écran. Un bandeau (nom de la chaîne, bouton favori) s'affiche à
 * l'ouverture et à chaque appui sur OK, puis se cache tout seul. Retour : revenir à la liste.
 */
@OptIn(UnstableApi::class)
@Composable
fun PlayerScreen(channel: Channel, isFavorite: Boolean, onToggleFavorite: () -> Unit, onExit: () -> Unit) {
    val context = LocalContext.current
    var overlay by remember { mutableStateOf(true) }
    var touched by remember { mutableIntStateOf(0) } // relance le compte à rebours du bandeau
    var buffering by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var attempt by remember { mutableIntStateOf(0) }
    val root = remember { FocusRequester() }
    val favoriteButton = remember { FocusRequester() }

    val player = remember(attempt) {
        val http = DefaultHttpDataSource.Factory()
            .setAllowCrossProtocolRedirects(true) // beaucoup de serveurs IPTV redirigent http ↔ https
            .setUserAgent("GegeTV/1.0")
        ExoPlayer.Builder(context, DefaultRenderersFactory(context).setEnableDecoderFallback(true))
            .setMediaSourceFactory(DefaultMediaSourceFactory(DefaultDataSource.Factory(context, http)))
            .build()
            .apply {
                setMediaItem(mediaItemFor(channel.url))
                prepare()
                playWhenReady = true
            }
    }

    DisposableEffect(player) {
        val listener = object : Player.Listener {
            override fun onPlaybackStateChanged(state: Int) {
                buffering = state == Player.STATE_BUFFERING
                if (state == Player.STATE_READY) error = null
            }

            override fun onPlayerError(e: PlaybackException) {
                error = "La chaîne ne répond pas (${e.errorCodeName.removePrefix("ERROR_CODE_").lowercase()})."
                overlay = true
            }
        }
        player.addListener(listener)
        onDispose {
            player.removeListener(listener)
            player.release()
        }
    }

    // Le bandeau se cache 6 s après la dernière action (sauf en cas d'erreur).
    LaunchedEffect(overlay, touched, error) {
        if (overlay) {
            runCatching { favoriteButton.requestFocus() }
            if (error == null) {
                delay(OVERLAY_MS)
                overlay = false
            }
        } else {
            runCatching { root.requestFocus() }
        }
    }

    Box(
        Modifier
            .fillMaxSize()
            .background(Color.Black)
            .focusRequester(root)
            .focusable()
            .onPreviewKeyEvent { event ->
                if (event.type != KeyEventType.KeyDown) return@onPreviewKeyEvent false
                touched++
                // Bandeau caché : OK ou les flèches le font réapparaître.
                if (!overlay && event.key in listOf(Key.DirectionCenter, Key.Enter, Key.DirectionUp,
                                                    Key.DirectionDown, Key.DirectionLeft, Key.DirectionRight)) {
                    overlay = true
                    true
                } else {
                    false
                }
            },
    ) {
        AndroidView(
            factory = { ctx ->
                PlayerView(ctx).apply {
                    useController = false
                    keepScreenOn = true
                    isFocusable = false
                }
            },
            update = { it.player = player },
            modifier = Modifier.fillMaxSize(),
        )

        if (buffering && error == null) {
            Text("Chargement…", modifier = Modifier.align(Alignment.Center), style = MaterialTheme.typography.titleLarge)
        }

        if (overlay) {
            Row(
                Modifier
                    .align(Alignment.TopCenter)
                    .fillMaxWidth()
                    .background(Brush.verticalGradient(listOf(Color(0xE6000000), Color.Transparent)))
                    .padding(horizontal = 48.dp, vertical = 28.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(24.dp),
            ) {
                ChannelLogo(channel, Modifier.width(120.dp).aspectRatio(16f / 9f))
                Column(Modifier.weight(1f)) {
                    Text(channel.name, style = MaterialTheme.typography.headlineSmall, maxLines = 1,
                         overflow = TextOverflow.Ellipsis)
                    if (channel.group.isNotBlank()) Text(channel.group, color = Color(0xFFD1D5DB), maxLines = 1)
                }
                Button(onClick = { onToggleFavorite(); touched++ }, modifier = Modifier.focusRequester(favoriteButton)) {
                    Text(if (isFavorite) "★ Retirer des favoris" else "☆ Ajouter aux favoris")
                }
                OutlinedButton(onClick = onExit) { Text("Retour") }
            }
        }

        error?.let { message ->
            Column(
                Modifier.align(Alignment.Center).background(Color(0xE6111827)).padding(32.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(message, color = Color(0xFFFCA5A5))
                Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                    Button(onClick = { error = null; attempt++ }) { Text("Réessayer") }
                    OutlinedButton(onClick = onExit) { Text("Retour") }
                }
            }
        }
    }
}

/**
 * Les directs IPTV ont souvent une adresse sans extension (…/12345). Sans indication, le lecteur
 * devine le format et peut ne voir que le son : on lui dit que c'est du MPEG-TS.
 */
fun mediaItemFor(url: String): MediaItem {
    val last = url.substringBefore('?').substringAfterLast('/')
    val builder = MediaItem.Builder().setUri(url)
    if ('.' !in last || last.endsWith(".ts", ignoreCase = true)) builder.setMimeType(MimeTypes.VIDEO_MP2T)
    return builder.build()
}
