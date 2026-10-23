package fr.subtrad.tv.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.tv.material3.Button
import androidx.tv.material3.MaterialTheme
import androidx.tv.material3.OutlinedButton
import androidx.tv.material3.Text
import fr.subtrad.tv.CheckResult
import fr.subtrad.tv.Job
import fr.subtrad.tv.R
import fr.subtrad.tv.Sheet
import fr.subtrad.tv.SubtradClient
import fr.subtrad.tv.VideoDetails
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.io.File

@Composable
fun DetailScreen(
    client: SubtradClient,
    id: Int,
    name: String,
    info: DetailInfo?,
    onReady: (Int) -> Unit,
    onDeleted: (Int) -> Unit,
    onWatch: (VideoDetails, File, Long) -> Unit,
    onBack: () -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var details by remember { mutableStateOf<VideoDetails?>(null) }
    var job by remember { mutableStateOf<Job?>(null) }
    var check by remember { mutableStateOf<CheckResult?>(null) }
    var busy by remember { mutableStateOf<Int?>(null) } // texte de l'action en cours
    var error by remember { mutableStateOf<Throwable?>(null) }
    var confirmDelete by remember { mutableStateOf(false) } // suppression : il faut appuyer deux fois
    val mainButton = remember { FocusRequester() }
    var movie by remember { mutableStateOf<Sheet?>(null) }
    LaunchedEffect(info?.vodId) { info?.vodId?.let { movie = runCatching { client.movieSheet(it) }.getOrNull() } }

    fun action(label: Int, block: suspend () -> Unit) {
        if (busy != null) return
        busy = label
        error = null
        scope.launch {
            try {
                block()
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                error = e
            } finally {
                busy = null
            }
        }
    }

    LaunchedEffect(id) {
        try {
            details = client.video(id)
            // Préparation lancée plus tôt et laissée en arrière-plan : on la retrouve.
            if (details?.ready == false) job = client.jobs().firstOrNull { it.videoId == id && it.running }
        } catch (e: Exception) {
            error = e
        }
    }
    LaunchedEffect(details?.ready, job?.running) { if (details != null) runCatching { mainButton.requestFocus() } }

    // Suivi de la préparation : le Mac est interrogé toutes les secondes.
    LaunchedEffect(job?.id) {
        var current = job ?: return@LaunchedEffect
        while (current.running) {
            delay(1_000)
            current = try {
                client.job(current.id)
            } catch (e: Exception) {
                error = e
                continue
            }
            job = current
        }
        if (current.state == "done") {
            try {
                details = client.video(id)
                if (details?.ready == true) onReady(id)
            } catch (e: Exception) {
                error = e
            }
        }
    }

    Column(
        Modifier.fillMaxSize().padding(horizontal = 64.dp, vertical = 36.dp),
        verticalArrangement = Arrangement.spacedBy(18.dp),
    ) {
        val header = movie ?: info?.sheet
        if (header != null) {
            SheetHeader(header, info?.subtitle ?: "", Modifier.height(200.dp))
        } else {
            Text(name, style = MaterialTheme.typography.headlineLarge)
            details?.let { Text(it.group, color = Color(0xFF9CA3AF)) }
        }

        val video = details
        val current = job
        when {
            video == null && error == null -> Text(stringResource(R.string.loading))
            video == null -> Unit
            video.ready -> {
                Text(stringResource(if (video.watched) R.string.status_watched else R.string.status_ready),
                     color = MaterialTheme.colorScheme.primary)
                Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                    fun watch(startMs: Long) = action(R.string.downloading_subs) {
                        val file = File(context.cacheDir, "subtitles/$id.srt")
                        onWatch(video, client.downloadSubtitles(id, file), startMs)
                    }
                    // Commencée et pas finie : on propose de reprendre là où on s'était arrêté.
                    val resume = video.positionMs >= 60_000 && !video.watched
                    Button(
                        onClick = { watch(if (resume) video.positionMs else 0L) },
                        modifier = Modifier.focusRequester(mainButton),
                    ) {
                        Text(if (resume) stringResource(R.string.resume, minutesText(video.positionMs))
                             else stringResource(R.string.watch))
                    }
                    if (resume) {
                        OutlinedButton(onClick = { watch(0L) }) { Text(stringResource(R.string.from_start)) }
                    }
                    OutlinedButton(onClick = onBack) { Text(stringResource(R.string.back)) }
                    OutlinedButton(
                        onClick = {
                            if (!confirmDelete) {
                                confirmDelete = true
                            } else {
                                action(R.string.delete) {
                                    client.forget(id)
                                    File(context.cacheDir, "subtitles/$id.srt").delete()
                                    onDeleted(id)
                                }
                            }
                        },
                        modifier = Modifier.onFocusChanged { if (!it.isFocused) confirmDelete = false },
                    ) {
                        Text(stringResource(if (confirmDelete) R.string.delete_confirm else R.string.delete))
                    }
                }
                if (confirmDelete) Text(stringResource(R.string.delete_help), color = Color(0xFF9CA3AF))
            }
            current != null && current.running -> {
                val translating = current.fetchDone || current.phase >= 2
                Text(stringResource(if (translating) R.string.phase_translate else R.string.phase_fetch))
                if (!current.fetchDone) ProgressBar(current.fraction, Modifier.width(720.dp))
                if (current.found > 0) {
                    Text(
                        if (current.fetchDone) stringResource(R.string.progress_lines, current.translated, current.found)
                        else stringResource(R.string.progress_lines_open, current.translated, current.found),
                        color = Color(0xFFD1D5DB),
                    )
                    ProgressBar(
                        if (current.fetchDone) current.translated.toDouble() / current.found else null,
                        Modifier.width(720.dp),
                    )
                }
                if (current.note.isNotBlank()) Text(current.note, color = Color(0xFFFCD34D))
                Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                    // La préparation continue sur le Mac : on peut regarder autre chose en attendant.
                    Button(onClick = onBack, modifier = Modifier.focusRequester(mainButton)) {
                        Text(stringResource(R.string.close_background))
                    }
                    OutlinedButton(onClick = { action(R.string.cancel) { job = client.cancel(current.id) } }) {
                        Text(stringResource(R.string.cancel))
                    }
                }
            }
            else -> {
                Text(stringResource(R.string.status_not_ready), color = Color(0xFFD1D5DB))
                Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                    Button(
                        onClick = { action(R.string.prepare) { job = client.prepare(id) } },
                        modifier = Modifier.focusRequester(mainButton),
                    ) { Text(stringResource(R.string.prepare)) }
                    OutlinedButton(onClick = { action(R.string.check) { check = client.check(id) } }) {
                        Text(stringResource(R.string.check))
                    }
                    OutlinedButton(onClick = onBack) { Text(stringResource(R.string.back)) }
                }
                check?.let {
                    Text(it.message, color = if (it.ok) MaterialTheme.colorScheme.primary else Color(0xFFFCA5A5))
                }
                when (current?.state) {
                    "error" -> Text(stringResource(R.string.error_prefix, current?.error ?: ""), color = Color(0xFFFCA5A5))
                    "cancelled" -> Text(stringResource(R.string.cancelled), color = Color(0xFF9CA3AF))
                }
            }
        }
        busy?.let {
            Text(stringResource(if (it == R.string.downloading_subs) it else R.string.loading), color = Color(0xFF9CA3AF))
        }
        error?.let { Text(errorMessage(it), color = Color(0xFFFCA5A5)) }
    }
}

/** En-tête d'une fiche venue du catalogue : fiche de la série (épisode) ou numéro du film. */
data class DetailInfo(val sheet: Sheet?, val subtitle: String, val vodId: Int?)

/** « 23 min » ou « 1 h 05 ». */
fun minutesText(ms: Long): String {
    val minutes = ms / 60_000
    return if (minutes >= 60) "${minutes / 60} h ${"%02d".format(minutes % 60)}" else "$minutes min"
}
