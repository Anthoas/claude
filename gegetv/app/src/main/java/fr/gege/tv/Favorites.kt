package fr.gege.tv

import android.content.Context
import android.util.Log
import org.json.JSONArray
import java.io.File
import java.io.FileOutputStream

/**
 * Les favoris, gardés à l'abri des pertes (d'autres applis IPTV les « perdent » de temps en temps) :
 * - enregistrés tout de suite, dans un fichier écrit à côté puis mis à la place de l'ancien
 *   seulement une fois complet (une coupure de courant ne laisse jamais un fichier à moitié écrit) ;
 * - les 5 versions précédentes sont gardées ; si le fichier est illisible, la plus récente version
 *   saine est reprise ;
 * - une liste vide ne remplace jamais une liste pleine, sauf si on vient de retirer soi-même le
 *   dernier favori.
 */
class Favorites(context: Context) {
    private val dir = File(context.filesDir, "favoris").apply { mkdirs() }
    private val main = File(dir, "favoris.json")
    private fun backup(n: Int) = File(dir, "favoris-$n.json")

    /** Favoris dans l'ordre où ils ont été ajoutés ; `legacy` = anciens favoris (version précédente). */
    fun load(legacy: () -> List<Channel> = { emptyList() }): List<Channel> {
        read(main)?.let { return it }
        for (n in 1..BACKUPS) {
            val saved = read(backup(n)) ?: continue
            Log.w(TAG, "favoris illisibles : reprise de la sauvegarde $n (${saved.size} chaînes)")
            write(saved)
            return saved
        }
        val old = legacy()
        if (old.isNotEmpty()) write(old) // première ouverture de cette version : on reprend les anciens
        return old
    }

    /**
     * Enregistre la liste. `removedLast` : on vient de retirer le dernier favori (seul cas où une
     * liste vide est enregistrée à la place d'une liste pleine).
     */
    fun save(list: List<Channel>, removedLast: Boolean = false) {
        if (list.isEmpty() && !removedLast && !read(main).isNullOrEmpty()) {
            Log.w(TAG, "liste vide non enregistrée : les favoris existants sont gardés")
            return
        }
        write(list)
    }

    private fun write(list: List<Channel>) {
        val text = JSONArray().apply { list.forEach { put(it.toJson()) } }.toString()
        if (main.exists() && main.readText() == text) return
        if (read(main) != null) rotate() // l'ancienne version saine devient la sauvegarde 1
        val staged = File(dir, "favoris.json.part")
        FileOutputStream(staged).use { out ->
            out.write(text.toByteArray(Charsets.UTF_8))
            out.fd.sync() // vraiment écrit sur la mémoire de la télé avant de continuer
        }
        if (!staged.renameTo(main)) {
            main.delete()
            staged.renameTo(main)
        }
    }

    private fun rotate() {
        backup(BACKUPS).delete()
        for (n in BACKUPS - 1 downTo 1) backup(n).takeIf { it.exists() }?.renameTo(backup(n + 1))
        main.copyTo(backup(1), overwrite = true)
    }

    private fun read(file: File): List<Channel>? = try {
        if (!file.exists()) null
        else {
            val array = JSONArray(file.readText())
            (0 until array.length()).map { Channel.fromJson(array.getJSONObject(it)) }
                .filter { it.url.isNotBlank() }
                .takeIf { it.size == array.length() } // une entrée abîmée = fichier abîmé
        }
    } catch (e: Exception) {
        null
    }

    companion object {
        private const val TAG = "GegeTV"
        private const val BACKUPS = 5
    }
}
