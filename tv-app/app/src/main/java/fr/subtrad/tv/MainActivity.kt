package fr.subtrad.tv

import android.content.Intent
import android.graphics.Color
import android.graphics.drawable.ColorDrawable
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import fr.subtrad.tv.ui.SubtradApp

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Fenêtre sans fond (les écrans dessinent le leur) : la vidéo, affichée derrière
        // l'application, n'est cachée par rien (sur Philips/MediaTek, le fond gris la recouvrait).
        window.setBackgroundDrawable(ColorDrawable(Color.TRANSPARENT))
        val prefs = Prefs(this)
        applyProvisioning(intent, prefs)
        setContent { SubtradApp(prefs) }
    }

    /**
     * Réglage depuis le Mac, pour ne pas taper l'adresse et le code à la télécommande :
     * adb shell am start -S -n fr.subtrad.tv/.MainActivity --es address IP:PORT --es code CODE
     * Les deux sont exigés ensemble : une autre application ne peut pas détourner le code
     * enregistré vers une autre adresse.
     */
    private fun applyProvisioning(intent: Intent?, prefs: Prefs) {
        val address = intent?.getStringExtra("address")
        val code = intent?.getStringExtra("code")
        if (!address.isNullOrBlank() && !code.isNullOrBlank()) {
            prefs.address = address
            prefs.code = code
        }
    }
}
