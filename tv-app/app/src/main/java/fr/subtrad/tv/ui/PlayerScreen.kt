package fr.subtrad.tv.ui

import android.net.Uri
import androidx.annotation.OptIn
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.ui.PlayerView
import androidx.media3.ui.SubtitleView
import androidx.tv.material3.Button
import androidx.tv.material3.Text
import fr.subtrad.tv.R
import fr.subtrad.tv.VideoDetails
import java.io.File

/**
 * Lecture avec ExoPlayer. Le .srt traduit, déjà téléchargé sur la télé, est ajouté comme piste
 * « Indonésien (traduit) » et choisi d'office. Le flux vidéo est lu directement depuis son
 * serveur (pas par le Mac), sans jamais recevoir le code de la maison.
 */
@OptIn(UnstableApi::class)
@Composable
fun PlayerScreen(video: VideoDetails, subtitles: File, onExit: () -> Unit) {
    val context = LocalContext.current
    var error by remember { mutableStateOf<String?>(null) }
    val exitButton = remember { FocusRequester() }

    val player = remember {
        val http = DefaultHttpDataSource.Factory()
            .setAllowCrossProtocolRedirects(true) // beaucoup de serveurs IPTV redirigent http ↔ https
            .setUserAgent("SubtradTV/0.1")
        ExoPlayer.Builder(context)
            .setMediaSourceFactory(DefaultMediaSourceFactory(DefaultDataSource.Factory(context, http)))
            .build()
            .apply {
                trackSelectionParameters = trackSelectionParameters.buildUpon()
                    .setPreferredTextLanguage(video.language)
                    .build()
                val track = MediaItem.SubtitleConfiguration.Builder(Uri.fromFile(subtitles))
                    .setMimeType(MimeTypes.APPLICATION_SUBRIP)
                    .setLanguage(video.language)
                    .setLabel(video.subtitleLabel)
                    .setSelectionFlags(C.SELECTION_FLAG_DEFAULT)
                    .build()
                setMediaItem(MediaItem.Builder().setUri(video.url).setSubtitleConfigurations(listOf(track)).build())
                prepare()
                playWhenReady = true
            }
    }

    DisposableEffect(player) {
        val listener = object : Player.Listener {
            override fun onPlayerError(e: PlaybackException) {
                error = "${e.errorCodeName} (${e.cause?.javaClass?.simpleName ?: e.message})"
            }
        }
        player.addListener(listener)
        onDispose {
            player.removeListener(listener)
            player.release()
        }
    }

    Box(Modifier.fillMaxSize().background(Color.Black)) {
        AndroidView(
            factory = { ctx ->
                PlayerView(ctx).apply {
                    this.player = player
                    keepScreenOn = true
                    setShowSubtitleButton(true)
                    subtitleView?.setFractionalTextSize(SubtitleView.DEFAULT_TEXT_SIZE_FRACTION * 1.15f)
                    isFocusable = true
                    requestFocus()
                }
            },
            modifier = Modifier.fillMaxSize(),
        )
        error?.let { message ->
            LaunchedEffect(message) { runCatching { exitButton.requestFocus() } }
            Column(
                Modifier.align(Alignment.Center).background(Color(0xE6111827)).padding(32.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(stringResource(R.string.player_error, message), color = Color(0xFFFCA5A5))
                Button(onClick = onExit, modifier = Modifier.focusRequester(exitButton)) {
                    Text(stringResource(R.string.back))
                }
            }
        }
    }
}
