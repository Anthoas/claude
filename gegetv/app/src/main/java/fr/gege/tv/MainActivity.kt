package fr.gege.tv

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import fr.gege.tv.ui.GegeApp

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val prefs = Prefs(this)
        // Réglage depuis un ordinateur, pour ne pas taper le lien à la télécommande :
        // adb shell am start -S -n fr.gege.tv/.MainActivity --es playlist LIEN
        intent?.getStringExtra("playlist")?.takeIf { it.startsWith("http") }?.let { prefs.playlistUrl = it }
        setContent { GegeApp(prefs, ChannelStore(this)) }
    }
}
