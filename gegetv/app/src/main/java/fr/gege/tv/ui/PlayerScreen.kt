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
import androidx.compose.foundation.layout.height
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
import fr.gege.tv.Program
import kotlinx.coroutines.delay
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private const val OVERLAY_MS = 6_000L

/**
 * Une chaîne en direct, en plein écran. Un bandeau d'information (nom de la chaîne, programme),
 * sans bouton, s'affiche à l'ouverture et à chaque appui sur OK, puis se cache tout seul.
 * Retour : revenir à la liste. (Les favoris se gèrent dans les listes, par un appui long.)
 * Pour une chaîne favorite, haut / bas passent à la chaîne précédente / suivante des favoris
 * (`onPrevious` / `onNext` nuls sinon).
 */
@OptIn(UnstableApi::class)
@Composable
fun PlayerScreen(
    channel: Channel,
    programs: List<Program>,
    onOpen: () -> Unit,
    onExit: () -> Unit,
    onPrevious: (() -> Unit)? = null,
    onNext: (() -> Unit)? = null,
) {
    val context = LocalContext.current
    var overlay by remember { mutableStateOf(true) }
    var touched by remember { mutableIntStateOf(0) } // relance le compte à rebours du bandeau
    var buffering by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var attempt by remember { mutableIntStateOf(0) }
    val root = remember { FocusRequester() }
    val retryButton = remember { FocusRequester() }

    val player = remember(attempt) {
        val http = DefaultHttpDataSource.Factory()
            .setAllowCrossProtocolRedirects(true) // beaucoup de serveurs IPTV redirigent http ↔ https
            .setUserAgent("GegeTV/1.0")
        ExoPlayer.Builder(context, DefaultRenderersFactory(context).setEnableDecoderFallback(true))
            .setMediaSourceFactory(DefaultMediaSourceFactory(DefaultDataSource.Factory(context, http)))
            .build()
    }

    LaunchedEffect(channel) { onOpen() } // le programme de la chaîne, pour le bandeau

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
        // Démarré ici, après l'arrêt de la chaîne précédente : l'abonnement n'accepte qu'une
        // vidéo à la fois.
        player.setMediaItem(mediaItemFor(channel.url))
        player.prepare()
        player.playWhenReady = true
        onDispose {
            player.removeListener(listener)
            player.release()
        }
    }

    // Sélection : sur l'image, ou sur « Réessayer » quand la chaîne ne répond pas.
    LaunchedEffect(error) {
        runCatching { if (error != null) retryButton.requestFocus() else root.requestFocus() }
    }
    // Le bandeau se cache 6 s après la dernière touche (sauf en cas d'erreur).
    LaunchedEffect(overlay, touched, error) {
        if (overlay && error == null) {
            delay(OVERLAY_MS)
            overlay = false
        }
    }

    Box(
        Modifier
            .fillMaxSize()
            .background(Color.Black)
            .focusRequester(root)
            .focusable()
            .onPreviewKeyEvent { event ->
                // Retour quitte la chaîne au premier appui.
                if (event.key == Key.Back) {
                    if (event.type == KeyEventType.KeyUp) onExit()
                    return@onPreviewKeyEvent true
                }
                if (event.type != KeyEventType.KeyDown) return@onPreviewKeyEvent false
                // Zapping dans les favoris (un changement par appui, même si la touche reste enfoncée).
                val zap = when (event.key) {
                    Key.DirectionUp -> onPrevious
                    Key.DirectionDown -> onNext
                    else -> null
                }
                if (zap != null) {
                    if (event.nativeKeyEvent.repeatCount == 0) zap()
                    return@onPreviewKeyEvent true
                }
                touched++
                // OK ou les flèches affichent le bandeau (ou le gardent 6 s de plus). En cas
                // d'erreur, les touches vont aux boutons « Réessayer » / « Retour ».
                if (error == null && event.key in listOf(Key.DirectionCenter, Key.Enter, Key.DirectionUp,
                                                         Key.DirectionDown, Key.DirectionLeft, Key.DirectionRight)) {
                    overlay = true
                    true
                } else {
                    false
                }
            },
    ) {
        AndroidView(
            // SurfaceView (par défaut) : la vidéo va directement à l'écran, HDR compris (une
            // TextureView rendait les chaînes HDR sombres et ternes).
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
                    // Sombre jusque sous la dernière ligne, pour rester lisible sur une image claire.
                    .background(Brush.verticalGradient(listOf(Color(0xF0000000), Color(0xD9000000), Color.Transparent)))
                    .padding(start = 48.dp, end = 48.dp, top = 28.dp, bottom = 64.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(24.dp),
            ) {
                ChannelLogo(channel, Modifier.width(120.dp).aspectRatio(16f / 9f))
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(channel.name, style = MaterialTheme.typography.headlineSmall, maxLines = 1,
                         overflow = TextOverflow.Ellipsis)
                    val current = programs.firstOrNull()?.takeIf { it.start <= System.currentTimeMillis() }
                    if (current == null) {
                        if (channel.group.isNotBlank()) Text(channel.group, color = Color(0xFFD1D5DB), maxLines = 1)
                    } else {
                        Text("${hours(current)} · ${current.title}", style = MaterialTheme.typography.titleMedium,
                             maxLines = 1, overflow = TextOverflow.Ellipsis)
                        ProgressBar(current.progress(System.currentTimeMillis()).toDouble(),
                                    Modifier.width(360.dp).height(6.dp))
                        if (current.description.isNotBlank()) {
                            Text(current.description, color = Color(0xFFD1D5DB), maxLines = 2, overflow = TextOverflow.Ellipsis)
                        }
                    }
                    programs.firstOrNull { it.start > System.currentTimeMillis() }?.let { next ->
                        Text("Ensuite ${clock(next.start)} · ${next.title}", color = Color(0xFF9CA3AF),
                             maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                }
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
                    Button(onClick = { error = null; attempt++ }, modifier = Modifier.focusRequester(retryButton),
                           colors = redButtonColors()) {
                        Text("Réessayer")
                    }
                    OutlinedButton(onClick = onExit, colors = redOutlinedButtonColors()) { Text("Retour") }
                }
            }
        }
    }
}

private val CLOCK = SimpleDateFormat("HH:mm", Locale.FRANCE)

fun clock(time: Long): String = CLOCK.format(Date(time))

/** « 11:50 – 12:50 » */
fun hours(program: Program): String = "${clock(program.start)} – ${clock(program.end)}"

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
