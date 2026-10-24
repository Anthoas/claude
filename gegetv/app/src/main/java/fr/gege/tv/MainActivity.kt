package fr.gege.tv

import android.graphics.Color
import android.graphics.drawable.ColorDrawable
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import fr.gege.tv.ui.GegeApp

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Fenêtre sans fond (les écrans dessinent le leur) : la vidéo, affichée derrière
        // l'application, n'est cachée par rien (sur Philips/MediaTek, le fond gris la recouvrait).
        window.setBackgroundDrawable(ColorDrawable(Color.TRANSPARENT))
        val prefs = Prefs(this)
        val store = ChannelStore(this)
        prefs.migrate(store)
        prefs.applyPreset()
        // Réglage depuis un ordinateur, pour ne pas taper la source à la télécommande :
        // adb shell am start -S -n fr.gege.tv/.MainActivity --es playlist LIEN_GET_PHP
        intent?.getStringExtra("playlist")?.takeIf { it.startsWith("http") }?.let { prefs.provision(it) }
        setContent { GegeApp(prefs, store) }
    }
}
