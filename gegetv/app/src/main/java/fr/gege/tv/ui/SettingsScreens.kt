package fr.gege.tv.ui

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
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.tv.material3.Button
import androidx.tv.material3.ListItem
import androidx.tv.material3.ListItemDefaults
import androidx.tv.material3.MaterialTheme
import androidx.tv.material3.Text
import fr.gege.tv.Source
import kotlinx.coroutines.launch
import java.text.DateFormat
import java.util.Date

private val MUTED = Color(0xFF9CA3AF)
private const val PAGE_SOURCES = 0
private const val PAGE_CHANNELS = 1

/** Réglages : deux onglets, « Sources » (les comptes Xtream Codes) et « Chaînes » (la liste chargée). */
@Composable
fun SettingsScreen(state: GegeState) {
    var page by remember { mutableIntStateOf(PAGE_SOURCES) }
    var adding by remember { mutableStateOf(state.sources.isEmpty()) }
    Column(verticalArrangement = Arrangement.spacedBy(14.dp), modifier = Modifier.padding(top = 4.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            PageButton("Sources", page == PAGE_SOURCES) { page = PAGE_SOURCES }
            PageButton("Chaînes", page == PAGE_CHANNELS) { page = PAGE_CHANNELS; adding = false }
        }
        when {
            page == PAGE_CHANNELS -> ChannelsPage(state)
            adding -> AddSourceForm(state, onDone = { adding = false })
            else -> SourcesPage(state, onAdd = { adding = true })
        }
    }
}

/** Onglet des réglages : contour clair quand il est affiché, liseré rouge quand il est sélectionné. */
@Composable
private fun PageButton(label: String, shown: Boolean, onClick: () -> Unit) {
    Button(onClick = onClick, colors = plainButtonColors(), border = plainButtonBorder(),
           modifier = if (shown) Modifier.background(Color(0x33FFFFFF), RoundedCornerShape(50)) else Modifier) {
        Text(if (shown) "▸ $label" else label)
    }
}

@Composable
private fun SourcesPage(state: GegeState, onAdd: () -> Unit) {
    val activeRow = remember { FocusRequester() }
    LaunchedEffect(Unit) { runCatching { activeRow.requestFocus() } } // sélecteur sur la source utilisée
    var chosen by remember { mutableStateOf<Source?>(null) } // source dont on choisit quoi faire
    var deleting by remember { mutableStateOf<Source?>(null) }
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(if (state.sources.isEmpty()) "Aucune source enregistrée."
             else "OK sur une source : l'utiliser ou la supprimer. Une seule source est utilisée à la fois, chacune garde ses favoris.",
             color = MUTED)
        // Marge intérieure : l'élément sélectionné grossit un peu, son liseré rouge ne doit pas être coupé.
        LazyColumn(verticalArrangement = Arrangement.spacedBy(4.dp), contentPadding = PaddingValues(horizontal = 20.dp, vertical = 10.dp)) {
            items(state.sources, key = { it.id }) { source ->
                val used = state.active?.id == source.id
                ListItem(
                    selected = false,
                    onClick = { chosen = source },
                    colors = ListItemDefaults.colors(
                        focusedContainerColor = Color.Transparent, focusedContentColor = Color.White,
                        pressedContainerColor = Color.Transparent, pressedContentColor = Color.White,
                    ),
                    border = ListItemDefaults.border(focusedBorder = selectedBorder(RoundedCornerShape(8.dp)),
                                                     pressedBorder = selectedBorder(RoundedCornerShape(8.dp))),
                    headlineContent = { Text(source.name, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                    supportingContent = { Text(source.host, color = MUTED, maxLines = 1) },
                    modifier = if (used) Modifier.focusRequester(activeRow) else Modifier,
                    trailingContent = {
                        if (used) Text("● Utilisée", color = MaterialTheme.colorScheme.primary)
                    },
                )
            }
            item {
                Button(onClick = onAdd, colors = plainButtonColors(), border = plainButtonBorder(),
                       modifier = Modifier.padding(top = 8.dp)) {
                    Text("+ Ajouter une source")
                }
            }
        }
    }

    chosen?.let { source ->
        val used = state.active?.id == source.id
        ChoiceDialog(
            title = source.name,
            choices = buildList {
                if (!used) add("Utiliser cette source" to {
                    chosen = null
                    state.run { state.use(source) }
                })
                add("Supprimer" to { chosen = null; deleting = source })
                add("Annuler" to { chosen = null })
            },
            onDismiss = { chosen = null },
        )
    }
    deleting?.let { source ->
        ConfirmDialog(
            question = "Supprimer la source « ${source.name} » ? Ses favoris seront effacés.",
            onYes = { deleting = null; state.run { state.removeSource(source) } },
            onNo = { deleting = null },
        )
    }
}

/** Nouvelle source : nom, adresse du serveur, identifiant, mot de passe ; vérifiée avant d'être gardée. */
@Composable
private fun AddSourceForm(state: GegeState, onDone: () -> Unit) {
    val scope = rememberCoroutineScope()
    var name by remember { mutableStateOf(if (state.sources.isEmpty()) "Ma source" else "") }
    var server by remember { mutableStateOf("") }
    var username by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf<String?>(null) }
    val first = remember { FocusRequester() }
    LaunchedEffect(Unit) { runCatching { first.requestFocus() } }
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("Nouvelle source (Xtream Codes)", style = MaterialTheme.typography.titleMedium)
        Field("Nom", name, { name = it }, "ex. : Ma source", Modifier.focusRequester(first))
        Field("Adresse du serveur", server, { server = it }, "ex. : http://monserveur.com:8080", keyboard = KeyboardType.Uri)
        Field("Identifiant", username, { username = it }, "")
        Field("Mot de passe", password, { password = it }, "", secret = true)
        Row(horizontalArrangement = Arrangement.spacedBy(16.dp), verticalAlignment = Alignment.CenterVertically) {
            Button(
                onClick = {
                    busy = true
                    message = null
                    scope.launch {
                        val error = state.addSource(name, server, username, password)
                        busy = false
                        if (error == null) onDone() else message = error
                    }
                },
                enabled = !busy, colors = plainButtonColors(), border = plainButtonBorder(),
            ) { Text(if (busy) "Vérification…" else "Vérifier et enregistrer") }
            if (state.sources.isNotEmpty()) {
                Button(onClick = onDone, enabled = !busy, colors = plainButtonColors(), border = plainButtonBorder()) {
                    Text("Annuler")
                }
            }
        }
        message?.let { Text(it, color = Color(0xFFFCA5A5)) }
        Text("L'identifiant et le mot de passe restent sur cette télé.", color = MUTED)
    }
}

@Composable
private fun Field(
    label: String, value: String, onChange: (String) -> Unit, placeholder: String,
    modifier: Modifier = Modifier, keyboard: KeyboardType = KeyboardType.Text, secret: Boolean = false,
) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
        Text(label, modifier = Modifier.width(200.dp), color = Color(0xFFD1D5DB))
        TvTextField(value = value, onValueChange = onChange, placeholder = placeholder, keyboardType = keyboard,
                    secret = secret, modifier = modifier.width(560.dp))
    }
}

@Composable
private fun ChannelsPage(state: GegeState) {
    val source = state.active
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        if (source == null) {
            Text("Aucune source utilisée : ajoute une source dans l'onglet « Sources ».", color = MUTED)
            return@Column
        }
        Text("Source utilisée : ${source.name}", style = MaterialTheme.typography.titleMedium)
        val date = if (state.savedAt > 0) DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT).format(Date(state.savedAt)) else ""
        Text(if (state.channels.isEmpty()) "Aucune chaîne chargée."
             else "${state.channels.size} chaînes en direct · liste du $date (rechargée chaque semaine)", color = MUTED)
        Button(onClick = { state.run { state.refresh() } }, enabled = !state.loading,
               colors = plainButtonColors(), border = plainButtonBorder()) {
            Text(if (state.loading) "Chargement…" else "Recharger la liste des chaînes maintenant")
        }
        state.error?.let { Text("Erreur : $it", color = Color(0xFFFCA5A5)) }
    }
}

/** Fenêtre de choix (plusieurs boutons les uns sous les autres) ; Retour = fermer. */
@Composable
private fun ChoiceDialog(title: String, choices: List<Pair<String, () -> Unit>>, onDismiss: () -> Unit) {
    val first = remember { FocusRequester() }
    Dialog(onDismissRequest = onDismiss) {
        Column(
            Modifier.background(Color(0xFF1F2A22), RoundedCornerShape(16.dp)).padding(32.dp).width(460.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(title, style = MaterialTheme.typography.headlineSmall, color = Color.White, textAlign = TextAlign.Center)
            choices.forEachIndexed { index, (label, action) ->
                Button(onClick = action, colors = plainButtonColors(), border = plainButtonBorder(),
                       modifier = Modifier.width(320.dp).then(if (index == 0) Modifier.focusRequester(first) else Modifier)) {
                    Text(label, modifier = Modifier.width(280.dp), textAlign = TextAlign.Center)
                }
            }
        }
    }
    LaunchedEffect(Unit) { runCatching { first.requestFocus() } }
}
