package fr.subtrad.tv.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.ui.Alignment
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusProperties
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.style.TextAlign
import androidx.tv.material3.ClickableSurfaceDefaults
import androidx.tv.material3.Icon
import androidx.tv.material3.Surface
import androidx.compose.ui.focus.FocusDirection
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.input.key.type
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.tv.material3.MaterialTheme
import androidx.tv.material3.Text
import fr.subtrad.tv.R
import fr.subtrad.tv.SubtradException

/** Champ de saisie pour la télécommande : cadre visible quand il a le focus. */
@Composable
fun TvTextField(
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
    modifier: Modifier = Modifier,
    keyboardType: KeyboardType = KeyboardType.Text,
    secret: Boolean = false,
    imeAction: ImeAction = ImeAction.Done,
    onSubmit: () -> Unit = {},
) {
    var focused by remember { mutableStateOf(false) }
    val accent = MaterialTheme.colorScheme.primary
    val focusManager = LocalFocusManager.current
    BasicTextField(
        value = value,
        onValueChange = onValueChange,
        singleLine = true,
        textStyle = TextStyle(color = Color.White, fontSize = 22.sp),
        cursorBrush = SolidColor(accent),
        visualTransformation = if (secret) PasswordVisualTransformation() else VisualTransformation.None,
        keyboardOptions = KeyboardOptions(keyboardType = keyboardType, imeAction = imeAction),
        keyboardActions = KeyboardActions(onAny = { onSubmit() }),
        modifier = modifier
            // À la télécommande, les flèches quittent le champ (sinon on ne peut plus en sortir :
            // gauche et droite déplaçaient seulement le curseur, « Réglages » était inaccessible).
            .onPreviewKeyEvent { event ->
                if (event.type != KeyEventType.KeyDown) return@onPreviewKeyEvent false
                when (event.key) {
                    Key.DirectionDown -> focusManager.moveFocus(FocusDirection.Down)
                    Key.DirectionUp -> focusManager.moveFocus(FocusDirection.Up)
                    Key.DirectionLeft -> focusManager.moveFocus(FocusDirection.Left)
                    Key.DirectionRight -> focusManager.moveFocus(FocusDirection.Right)
                    else -> false
                }
            }
            .onFocusChanged { focused = it.isFocused }
            .background(Color(0xFF1F2937), RoundedCornerShape(8.dp))
            .border(2.dp, if (focused) accent else Color(0xFF374151), RoundedCornerShape(8.dp))
            .padding(horizontal = 16.dp, vertical = 12.dp),
        decorationBox = { inner ->
            Box {
                if (value.isEmpty()) Text(placeholder, color = Color(0xFF9CA3AF), fontSize = 22.sp)
                inner()
            }
        },
    )
}

/** Barre d'avancement ; `fraction` nulle = avancement inconnu (barre à moitié pâle). */
@Composable
fun ProgressBar(fraction: Double?, modifier: Modifier = Modifier) {
    Box(
        modifier
            .fillMaxWidth()
            .height(10.dp)
            .background(Color(0xFF374151), RoundedCornerShape(5.dp)),
    ) {
        Box(
            Modifier
                .fillMaxWidth((fraction ?: 1.0).toFloat().coerceIn(0f, 1f))
                .fillMaxHeight()
                .background(
                    MaterialTheme.colorScheme.primary.copy(alpha = if (fraction == null) 0.35f else 1f),
                    RoundedCornerShape(5.dp),
                ),
        )
    }
}

/** Message lisible pour une erreur venue du Mac ou du réseau. */
@Composable
fun errorMessage(error: Throwable): String = when {
    error is SubtradException && error.unreachable -> stringResource(R.string.error_network)
    error is SubtradException && error.badCode -> stringResource(R.string.error_code)
    else -> stringResource(R.string.error_prefix, error.message ?: error.javaClass.simpleName)
}

/** Un bouton du menu de gauche : une petite icône, son nom ; `page` : ouvre sa page dès qu'on passe dessus. */
data class RailItem(val label: String, val icon: Int, val page: Boolean = true)

/**
 * Menu de gauche (comme ZenIPTV) : une colonne étroite avec de petites icônes ; la page affichée a
 * un fond arrondi. En arrivant dans le menu, le sélecteur va sur la page affichée (`selectedFocus`).
 */
@OptIn(ExperimentalComposeUiApi::class)
@Composable
fun NavRail(
    items: List<RailItem>,
    selected: Int,
    onSelect: (Int) -> Unit,
    selectedFocus: FocusRequester,
    top: @Composable () -> Unit,
) {
    Column(
        Modifier.fillMaxHeight().width(116.dp).background(Color(0xFF0B1120)).padding(vertical = 26.dp)
            .focusProperties { enter = { selectedFocus } },
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        top()
        Spacer(Modifier.height(16.dp))
        items.forEachIndexed { index, item ->
            val shape = RoundedCornerShape(16.dp)
            Surface(
                onClick = { onSelect(index) },
                shape = ClickableSurfaceDefaults.shape(shape),
                colors = ClickableSurfaceDefaults.colors(
                    containerColor = if (index == selected) Color(0xFF1F2937) else Color.Transparent,
                    contentColor = if (index == selected) Color.White else Color(0xFF9CA3AF),
                    focusedContainerColor = Color(0xFFE5E7EB), focusedContentColor = Color(0xFF111827),
                    pressedContainerColor = Color(0xFFE5E7EB), pressedContentColor = Color(0xFF111827),
                ),
                modifier = Modifier.width(92.dp).height(84.dp)
                    .then(if (index == selected) Modifier.focusRequester(selectedFocus) else Modifier)
                    .onFocusChanged { if (it.isFocused && item.page && index != selected) onSelect(index) },
            ) {
                Column(Modifier.fillMaxSize().padding(horizontal = 4.dp), horizontalAlignment = Alignment.CenterHorizontally,
                       verticalArrangement = Arrangement.Center) {
                    Icon(painterResource(item.icon), contentDescription = item.label, modifier = Modifier.size(30.dp))
                    Text(item.label, fontSize = 11.sp, maxLines = 2, lineHeight = 13.sp,
                         textAlign = TextAlign.Center, modifier = Modifier.padding(top = 4.dp))
                }
            }
        }
    }
}
