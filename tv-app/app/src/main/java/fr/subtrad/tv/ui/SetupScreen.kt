package fr.subtrad.tv.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.tv.material3.Button
import androidx.tv.material3.MaterialTheme
import androidx.tv.material3.Text
import fr.subtrad.tv.Prefs
import fr.subtrad.tv.R
import fr.subtrad.tv.SubtradClient
import kotlinx.coroutines.launch

@Composable
fun SetupScreen(prefs: Prefs, onConnected: (SubtradClient) -> Unit) {
    var address by remember { mutableStateOf(prefs.address) }
    var code by remember { mutableStateOf(prefs.code) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<Throwable?>(null) }
    val scope = rememberCoroutineScope()
    val first = remember { FocusRequester() }

    fun connect() {
        if (busy) return
        busy = true
        error = null
        scope.launch {
            val client = SubtradClient(address, code)
            try {
                client.info()
                prefs.address = address
                prefs.code = code
                onConnected(client)
            } catch (e: Exception) {
                error = e
            } finally {
                busy = false
            }
        }
    }

    LaunchedEffect(Unit) { runCatching { first.requestFocus() } }

    Column(
        modifier = Modifier.fillMaxSize().padding(horizontal = 96.dp, vertical = 48.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text(stringResource(R.string.setup_title), style = MaterialTheme.typography.headlineLarge)
        Text(stringResource(R.string.setup_help), color = Color(0xFFD1D5DB))
        TvTextField(
            value = address, onValueChange = { address = it },
            placeholder = stringResource(R.string.setup_address),
            keyboardType = KeyboardType.Uri, imeAction = ImeAction.Next,
            modifier = Modifier.width(560.dp).focusRequester(first),
        )
        TvTextField(
            value = code, onValueChange = { code = it.filter(Char::isDigit).take(6) },
            placeholder = stringResource(R.string.setup_code),
            keyboardType = KeyboardType.NumberPassword, secret = true,
            onSubmit = ::connect, modifier = Modifier.width(560.dp),
        )
        Button(onClick = ::connect, enabled = !busy && address.isNotBlank() && code.length == 6) {
            Text(stringResource(if (busy) R.string.setup_checking else R.string.setup_connect))
        }
        error?.let { Text(errorMessage(it), color = Color(0xFFFCA5A5)) }
    }
}
