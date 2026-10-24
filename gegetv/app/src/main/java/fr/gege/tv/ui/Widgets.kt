package fr.gege.tv.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.window.Dialog
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
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.tv.material3.Button
import androidx.tv.material3.ButtonDefaults
import androidx.tv.material3.OutlinedButtonDefaults
import androidx.tv.material3.MaterialTheme
import androidx.tv.material3.Text

/** Couleur du sélecteur (élément choisi à la télécommande), partout dans l'application. */
val SELECT_RED = Color(0xFFE53935)

@Composable
fun redButtonColors() = ButtonDefaults.colors(focusedContainerColor = SELECT_RED, focusedContentColor = Color.White)

@Composable
fun redOutlinedButtonColors() =
    OutlinedButtonDefaults.colors(focusedContainerColor = SELECT_RED, focusedContentColor = Color.White)

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
        keyboardActions = KeyboardActions(onAny = { onSubmit(); focusManager.moveFocus(FocusDirection.Down) }),
        modifier = modifier
            // À la télécommande, haut et bas quittent le champ (sinon on ne peut plus en sortir).
            .onPreviewKeyEvent { event ->
                if (event.type != KeyEventType.KeyDown) return@onPreviewKeyEvent false
                when (event.key) {
                    Key.DirectionDown -> focusManager.moveFocus(FocusDirection.Down)
                    Key.DirectionUp -> focusManager.moveFocus(FocusDirection.Up)
                    else -> false
                }
            }
            .onFocusChanged { focused = it.isFocused }
            .background(Color(0xFF1F2937), RoundedCornerShape(8.dp))
            .border(if (focused) 3.dp else 2.dp, if (focused) SELECT_RED else Color(0xFF374151), RoundedCornerShape(8.dp))
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


/**
 * Question Oui / Non par-dessus l'écran. « Non » est sélectionné d'office : un appui de trop sur
 * OK ne change rien. Retour = Non.
 */
@Composable
fun ConfirmDialog(question: String, onYes: () -> Unit, onNo: () -> Unit) {
    val no = remember { FocusRequester() }
    Dialog(onDismissRequest = onNo) {
        Column(
            Modifier
                .background(Color(0xFF1F2A22), RoundedCornerShape(16.dp))
                .border(2.dp, Color(0xFF374151), RoundedCornerShape(16.dp))
                .padding(36.dp)
                .widthIn(max = 720.dp),
            verticalArrangement = Arrangement.spacedBy(28.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(question, style = MaterialTheme.typography.headlineSmall, color = Color.White, textAlign = TextAlign.Center)
            Row(horizontalArrangement = Arrangement.spacedBy(24.dp)) {
                Button(onClick = onYes, modifier = Modifier.width(160.dp), colors = redButtonColors()) {
                    Text("Oui", modifier = Modifier.fillMaxWidth(), textAlign = TextAlign.Center)
                }
                Button(onClick = onNo, modifier = Modifier.width(160.dp).focusRequester(no), colors = redButtonColors()) {
                    Text("Non", modifier = Modifier.fillMaxWidth(), textAlign = TextAlign.Center)
                }
            }
        }
    }
    LaunchedEffect(Unit) { runCatching { no.requestFocus() } }
}
