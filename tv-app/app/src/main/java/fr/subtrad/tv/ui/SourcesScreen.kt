package fr.subtrad.tv.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.tv.material3.Button
import androidx.tv.material3.ListItem
import androidx.tv.material3.MaterialTheme
import androidx.tv.material3.OutlinedButton
import androidx.tv.material3.Text
import fr.subtrad.tv.R
import fr.subtrad.tv.SourceInfo
import fr.subtrad.tv.SubtradClient
import kotlinx.coroutines.launch

private val MUTED = Color(0xFF9CA3AF)

/**
 * Onglet « Sources » des réglages : les comptes enregistrés sur le Mac (une seule source utilisée à
 * la fois), « Utiliser », « Supprimer » (avec confirmation), « + Ajouter une source ».
 * `onChanged` : la source utilisée a changé (les listes de l'accueil sont à recharger).
 */
@Composable
fun SourcesScreen(client: SubtradClient, onChanged: () -> Unit) {
    val scope = rememberCoroutineScope()
    var sources by remember { mutableStateOf<List<SourceInfo>?>(null) }
    var adding by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf<String?>(null) } // message pendant une opération
    var error by remember { mutableStateOf<Throwable?>(null) }
    var chosen by remember { mutableStateOf<SourceInfo?>(null) }
    var deleting by remember { mutableStateOf<SourceInfo?>(null) }
    val activeRow = remember { FocusRequester() }
    val switching = stringResource(R.string.source_switching)

    suspend fun reload() {
        sources = runCatching { client.sources() }.onFailure { error = it }.getOrNull() ?: sources
    }
    LaunchedEffect(adding) { if (!adding) reload() }
    LaunchedEffect(sources != null) { if (sources != null) runCatching { activeRow.requestFocus() } }

    fun act(message: String, block: suspend () -> List<SourceInfo>) {
        busy = message
        error = null
        scope.launch {
            try {
                sources = block()
                onChanged()
            } catch (e: Exception) {
                error = e
            } finally {
                busy = null
            }
        }
    }

    if (adding) {
        AddSourceForm(client, onDone = { added -> adding = false; if (added) onChanged() })
        return
    }
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(stringResource(R.string.sources_help), color = MUTED)
        val list = sources
        if (list != null && list.isEmpty()) Text(stringResource(R.string.sources_none), color = MUTED)
        LazyColumn(verticalArrangement = Arrangement.spacedBy(4.dp), contentPadding = PaddingValues(12.dp)) {
            items(list.orEmpty(), key = { it.id }) { source ->
                ListItem(
                    selected = false,
                    enabled = busy == null,
                    onClick = { chosen = source },
                    headlineContent = { Text(source.name, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                    supportingContent = {
                        Text(stringResource(R.string.source_meta, source.kindLabel, source.host, "%,d".format(source.count)),
                             maxLines = 1, overflow = TextOverflow.Ellipsis)
                    },
                    trailingContent = {
                        if (source.active) Text(stringResource(R.string.source_used), color = MaterialTheme.colorScheme.primary)
                    },
                    modifier = if (source.active) Modifier.focusRequester(activeRow) else Modifier,
                )
            }
            item {
                OutlinedButton(onClick = { adding = true }, enabled = busy == null, modifier = Modifier.padding(top = 8.dp)) {
                    Text(stringResource(R.string.source_add))
                }
            }
        }
        busy?.let { Text(it, color = Color(0xFFFCD34D)) }
        error?.let { Text(errorMessage(it), color = Color(0xFFFCA5A5)) }
    }

    chosen?.let { source ->
        ChoiceDialog(
            title = source.name,
            choices = buildList {
                if (!source.active) add(stringResource(R.string.source_use) to {
                    chosen = null
                    act(switching) { client.useSource(source.id) }
                })
                add(stringResource(R.string.cancel) to { chosen = null }) // avant « Supprimer » : choisi d'office
                add(stringResource(R.string.source_delete) to { chosen = null; deleting = source })
            },
            onDismiss = { chosen = null },
        )
    }
    deleting?.let { source ->
        ChoiceDialog(
            title = stringResource(R.string.source_delete_confirm, source.name),
            choices = listOf(
                stringResource(R.string.no) to { deleting = null },
                stringResource(R.string.yes) to {
                    deleting = null
                    act("…") { client.deleteSource(source.id) }
                },
            ),
            onDismiss = { deleting = null },
        )
    }
}

/** Nouvelle source Xtream Codes, vérifiée et téléchargée par le Mac avant d'être gardée. */
@Composable
private fun AddSourceForm(client: SubtradClient, onDone: (added: Boolean) -> Unit) {
    val scope = rememberCoroutineScope()
    var name by remember { mutableStateOf("") }
    var server by remember { mutableStateOf("") }
    var username by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf<String?>(null) }
    val first = remember { FocusRequester() }
    val fillAll = stringResource(R.string.source_fill_all)
    LaunchedEffect(Unit) { runCatching { first.requestFocus() } }
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(stringResource(R.string.source_new_title), style = MaterialTheme.typography.titleMedium)
        Field(stringResource(R.string.source_name), name, { name = it }, "", Modifier.focusRequester(first))
        Field(stringResource(R.string.source_server), server, { server = it }, stringResource(R.string.source_server_hint),
              keyboard = KeyboardType.Uri)
        Field(stringResource(R.string.source_user), username, { username = it }, "")
        Field(stringResource(R.string.source_password), password, { password = it }, "", secret = true)
        Row(horizontalArrangement = Arrangement.spacedBy(16.dp), verticalAlignment = Alignment.CenterVertically) {
            Button(
                onClick = {
                    if (listOf(name, server, username, password).any { it.isBlank() }) {
                        message = fillAll
                        return@Button
                    }
                    busy = true
                    message = null
                    scope.launch {
                        try {
                            client.addSource(name.trim(), server.trim(), username.trim(), password.trim())
                            onDone(true)
                        } catch (e: Exception) {
                            message = e.message
                        } finally {
                            busy = false
                        }
                    }
                },
                enabled = !busy,
            ) { Text(stringResource(R.string.source_save)) }
            OutlinedButton(onClick = { onDone(false) }, enabled = !busy) { Text(stringResource(R.string.cancel)) }
        }
        if (busy) Text(stringResource(R.string.source_saving), color = Color(0xFFFCD34D))
        message?.let { Text(it, color = Color(0xFFFCA5A5)) }
        Text(stringResource(R.string.source_secret_note), color = MUTED)
    }
}

@Composable
private fun Field(
    label: String, value: String, onChange: (String) -> Unit, placeholder: String,
    modifier: Modifier = Modifier, keyboard: KeyboardType = KeyboardType.Text, secret: Boolean = false,
) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
        Text(label, modifier = Modifier.width(220.dp), color = Color(0xFFD1D5DB))
        TvTextField(value = value, onValueChange = onChange, placeholder = placeholder, keyboardType = keyboard,
                    secret = secret, modifier = modifier.width(560.dp))
    }
}

/** Fenêtre de choix : un bouton par choix, le premier sélectionné ; Retour = fermer. */
@Composable
private fun ChoiceDialog(title: String, choices: List<Pair<String, () -> Unit>>, onDismiss: () -> Unit) {
    val first = remember { FocusRequester() }
    Dialog(onDismissRequest = onDismiss) {
        Column(
            Modifier.background(Color(0xFF1F2937), RoundedCornerShape(16.dp)).padding(32.dp).width(520.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(title, style = MaterialTheme.typography.titleLarge, color = Color.White, textAlign = TextAlign.Center)
            choices.forEachIndexed { index, (label, action) ->
                Button(onClick = action, modifier = Modifier.width(360.dp)
                    .then(if (index == 0) Modifier.focusRequester(first) else Modifier)) {
                    Text(label, modifier = Modifier.width(320.dp), textAlign = TextAlign.Center)
                }
            }
        }
    }
    LaunchedEffect(Unit) { runCatching { first.requestFocus() } }
}
