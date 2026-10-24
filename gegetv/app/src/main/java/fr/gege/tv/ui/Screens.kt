package fr.gege.tv.ui

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
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.itemsIndexed
import androidx.compose.foundation.lazy.grid.rememberLazyGridState
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.tv.material3.CardDefaults
import androidx.tv.material3.ListItemDefaults
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.tv.material3.Button
import androidx.tv.material3.Card
import androidx.tv.material3.ListItem
import androidx.tv.material3.MaterialTheme
import androidx.tv.material3.Text
import coil.compose.AsyncImage
import fr.gege.tv.Channel
import fr.gege.tv.Logos
import androidx.compose.runtime.staticCompositionLocalOf
import fr.gege.tv.normalize
import java.text.DateFormat
import java.util.Date

private val GRAY = Color(0xFF9CA3AF)

/** Logos nets des chaînes (null : seulement ceux de la playlist). */
val LocalLogos = staticCompositionLocalOf<Logos?> { null }

/** Logo de la chaîne sur un fond sombre, ou ses initiales s'il n'y en a pas. */
@Composable
fun ChannelLogo(channel: Channel, modifier: Modifier = Modifier) {
    Box(modifier.clip(RoundedCornerShape(8.dp)).background(Color(0xFF243127)), contentAlignment = Alignment.Center) {
        // Logo net de la collection tv-logos s'il existe, sinon (ou s'il ne se charge pas) celui de la playlist.
        val better = LocalLogos.current?.of(channel)
        var failed by remember(better) { mutableStateOf(false) }
        val model = better?.takeUnless { failed } ?: channel.logo
        if (model.isNotBlank()) {
            AsyncImage(model = model, contentDescription = null, contentScale = ContentScale.Fit,
                       onError = { if (model == better) failed = true },
                       modifier = Modifier.fillMaxSize().padding(if (model == better) 14.dp else 8.dp))
        } else {
            Text(channel.name.take(3).uppercase(), style = MaterialTheme.typography.titleMedium, color = GRAY)
        }
    }
}

@Composable
fun FavoritesScreen(state: GegeState, onPlay: (Channel) -> Unit, startFocus: FocusRequester? = null) {
    if (state.favorites.isEmpty()) {
        Column(Modifier.padding(top = 32.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("Aucune chaîne en favori pour l'instant.", style = MaterialTheme.typography.titleLarge)
            Text("Va dans « Rechercher », trouve une chaîne et garde le doigt appuyé sur OK : GégéTV propose de l'ajouter.",
                 color = GRAY)
        }
        return
    }
    Text("OK : regarder · OK appuyé longtemps : retirer des favoris", color = GRAY,
         style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(bottom = 4.dp))
    // Sélecteur de départ : la chaîne qu'on vient de quitter, sinon la première.
    val start = state.favorites.indexOfFirst { it.url == state.lastPlayed?.url }.coerceAtLeast(0)
    val grid = rememberLazyGridState(initialFirstVisibleItemIndex = start)
    LazyVerticalGrid(
        state = grid,
        columns = GridCells.Fixed(5),
        horizontalArrangement = Arrangement.spacedBy(18.dp),
        verticalArrangement = Arrangement.spacedBy(18.dp),
        contentPadding = PaddingValues(vertical = 12.dp, horizontal = 4.dp),
    ) {
        itemsIndexed(state.favorites, key = { _, c -> c.url }) { index, channel ->
            Column {
                Card(
                    onClick = { onPlay(channel) },
                    onLongClick = { state.asking = channel },
                    shape = CardDefaults.shape(RoundedCornerShape(8.dp)),
                    border = CardDefaults.border(
                        focusedBorder = selectedBorder(RoundedCornerShape(8.dp)),
                        pressedBorder = selectedBorder(RoundedCornerShape(8.dp)),
                    ),
                    modifier = Modifier.fillMaxWidth().aspectRatio(16f / 9f)
                        .then(if (index == start && startFocus != null) Modifier.focusRequester(startFocus) else Modifier),
                ) {
                    ChannelLogo(channel, Modifier.fillMaxSize())
                }
                Text(channel.name, maxLines = 1, overflow = TextOverflow.Ellipsis, textAlign = TextAlign.Center,
                     modifier = Modifier.fillMaxWidth().padding(top = 6.dp))
                if (state.isUnavailable(channel)) {
                    Text("Indisponible", color = Color(0xFFFCA5A5), maxLines = 1,
                         overflow = TextOverflow.Ellipsis, textAlign = TextAlign.Center,
                         style = MaterialTheme.typography.bodySmall, modifier = Modifier.fillMaxWidth().padding(top = 2.dp))
                }
                // L'émission en cours, avec une petite barre qui montre où elle en est.
                state.programsOf(channel).firstOrNull()?.takeIf { it.start <= state.now }?.let { current ->
                    Text(current.title, color = GRAY, maxLines = 1, overflow = TextOverflow.Ellipsis,
                         textAlign = TextAlign.Center, style = MaterialTheme.typography.bodySmall,
                         modifier = Modifier.fillMaxWidth().padding(top = 2.dp, bottom = 4.dp))
                    ProgressBar(current.progress(state.now).toDouble(), Modifier.height(4.dp))
                }
            }
        }
    }
}

@Composable
fun SearchScreen(state: GegeState, onPlay: (Channel) -> Unit) {
    val results by remember {
        derivedStateOf {
            val words = normalize(state.query).split(" ").filter { it.isNotBlank() }
            if (words.isEmpty()) emptyList()
            else state.channels.filter { c -> words.all { it in c.haystack } }
                .sortedBy { if (it.name.trimStart('|', ' ').startsWith("FR")) 0 else 1 } // chaînes françaises d'abord
                .take(300)
        }
    }
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        TvTextField(
            value = state.query, onValueChange = { state.query = it },
            placeholder = "Nom de la chaîne (ex. : TF1, France 2, BFM…)",
            imeAction = ImeAction.Search, modifier = Modifier.width(620.dp),
        )
        Text(
            when {
                state.channels.isEmpty() && !state.loading -> "Aucune chaîne chargée : vérifie le lien dans « Réglages »."
                state.query.isBlank() -> "${state.channels.size} chaînes en direct. Tape le début d'un nom."
                results.isEmpty() -> "Aucune chaîne trouvée."
                else -> "${results.size}${if (results.size == 300) "+" else ""} chaîne(s) · OK : regarder · " +
                        "OK appuyé longtemps : ajouter aux favoris"
            },
            color = GRAY,
        )
        LazyColumn(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            items(results, key = { it.url }) { channel ->
                ListItem(
                    selected = false,
                    onClick = { onPlay(channel) },
                    onLongClick = { state.asking = channel },
                    colors = ListItemDefaults.colors(
                        focusedContainerColor = Color.Transparent, focusedContentColor = Color.White,
                        pressedContainerColor = Color.Transparent, pressedContentColor = Color.White,
                    ),
                    border = ListItemDefaults.border(focusedBorder = selectedBorder(RoundedCornerShape(8.dp)),
                                                     pressedBorder = selectedBorder(RoundedCornerShape(8.dp))),
                    leadingContent = { ChannelLogo(channel, Modifier.width(96.dp).aspectRatio(16f / 9f)) },
                    headlineContent = { Text(channel.name, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                    supportingContent = { Text(channel.group, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                    trailingContent = {
                        if (state.isFavorite(channel)) Text("★", color = MaterialTheme.colorScheme.primary,
                                                             style = MaterialTheme.typography.titleLarge)
                    },
                )
            }
        }
    }
}

@Composable
fun SettingsScreen(state: GegeState, onRefresh: (String?) -> Unit) {
    var url by remember { mutableStateOf(state.playlistUrl) }
    Column(verticalArrangement = Arrangement.spacedBy(14.dp), modifier = Modifier.padding(top = 8.dp)) {
        Text("Lien de la playlist (M3U)", style = MaterialTheme.typography.titleMedium)
        TvTextField(value = url, onValueChange = { url = it }, placeholder = "http://…",
                    keyboardType = KeyboardType.Uri, secret = true, modifier = Modifier.width(720.dp))
        Text("Le lien contient l'identifiant et le mot de passe : il reste sur cette télé.", color = GRAY)
        Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            Button(onClick = { onRefresh(url) }, enabled = !state.loading && url.isNotBlank(), colors = plainButtonColors(), border = plainButtonBorder()) {
                Text("Enregistrer et actualiser la liste des chaînes")
            }
        }
        val when_ = if (state.savedAt > 0) DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT).format(Date(state.savedAt)) else ""
        Text(if (state.channels.isEmpty()) "Aucune chaîne chargée."
             else "${state.channels.size} chaînes en direct · liste du $when_", color = GRAY)
        state.error?.let { Text("Erreur : $it", color = Color(0xFFFCA5A5)) }
    }
}
