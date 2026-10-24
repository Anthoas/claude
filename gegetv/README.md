# GégéTV — les directs, simplement

Application Android TV pour regarder les **chaînes en direct** d'une playlist IPTV, sans
traduction et sans Mac : elle lit elle-même la playlist M3U.

- **Écran d'accueil** au démarrage (tête de sanglier, « GégéTV ») : la liste des chaînes y est
  rechargée si elle a plus d'une semaine (environ 2 min sur la Philips, barre d'attente), puis le
  programme des favoris est mis à jour (quelques secondes) ; sans réseau, l'ancienne liste sert.
  Ensuite les favoris s'ouvrent, sélecteur sur la première chaîne. Fond vert sombre dès
  l'ouverture (`Theme.GegeTV`), pour éviter un écran gris.
- **Sélecteur : un liseré rouge** (`SELECT_RED`) autour de l'élément choisi, qui garde ses couleurs (ni fond rouge ni fond clair). À l'ouverture,
  il est sur la première chaîne des favoris ; en quittant une chaîne, il revient sur celle-ci ; en
  montant vers les onglets, il arrive sur l'onglet affiché (pas sur celui du dessus).
- **★ Favoris** (à l'ouverture) : grille des chaînes favorites, OK pour regarder, **OK appuyé
  longtemps** pour la retirer (question Oui / Non, « Non » sélectionné d'office) ; sous chaque
  chaîne, l'émission en cours et une barre qui montre où elle en est (mise à jour chaque minute).
- **Rechercher** : nom d'une chaîne (sans accents ni majuscules), chaînes françaises d'abord ;
  ★ sur celles déjà en favori ; **OK appuyé longtemps** sur une chaîne : « Voulez-vous ajouter
  « … » à la liste des favoris ? » Oui / Non. Haut/bas sortent du champ de saisie (sur la Philips,
  le clavier à l'écran se ferme d'abord avec Retour).
- **Réglages** : lien de la playlist (masqué), « Enregistrer et actualiser la liste des chaînes ».
- **Lecture** : plein écran ; un bandeau d'information **sans bouton** (logo, nom, émission en
  cours avec horaires, avancement et résumé, émission suivante) s'affiche à l'ouverture et à chaque
  appui sur OK, puis se cache après 6 s. Retour revient à la liste. **Chaîne favorite : haut /
  bas** passent à la chaîne précédente / suivante des favoris (en boucle) ; hors favoris, haut / bas
  affichent seulement le bandeau. L'ancienne chaîne est arrêtée avant d'ouvrir la nouvelle (abonnement
  à une seule connexion). Pas de bouton favori pendant la
  vidéo : le père avait peur de retirer un favori par erreur. Vidéo en `SurfaceView` (HDR
  compris) avec une fenêtre sans fond et un fond transparent pendant la lecture : sur la Philips
  (MediaTek), le fond de la fenêtre cachait la vidéo (son sans image). Une `TextureView` réglait ce
  problème mais rendait le HDR sombre et terne.

Favoris protégés contre les pertes (`Favorites.kt`, dossier `files/favoris/` de l'appli) :
enregistrés tout de suite (fichier écrit à côté, `fsync`, puis mis à la place de l'ancien) ; les 5
versions précédentes sont gardées (`favoris-1.json` … `favoris-5.json`) et la plus récente version
saine est reprise si le fichier est illisible ; une liste vide ne remplace jamais une liste pleine
(sauf retrait du dernier favori). Après chargement de la playlist, un favori dont l'adresse a changé
est retrouvé par son nom et mis à jour ; introuvable, il reste affiché « Indisponible », jamais
effacé. Les favoris des premières versions (préférences) sont repris une fois. Testé sur la Philips
(fichier abîmé, adresse changée, chaîne disparue).

Logos (`Logos.kt`) : ceux de la playlist sont petits (220 à 256 pixels, JPEG flou). GégéTV prend,
quand elle existe, l'image de 512 pixels détourée de la collection publique tv-logos
(github.com/tv-logo/tv-logos), retrouvée par le nom de la chaîne (« |FR| LIGUE 1+ 1 FHD » →
`ligue-1plus-1-fr`, sinon `ligue-1plus-fr`) ; la liste des logos de chaque pays est gardée sur la
télé et relue tous les 30 jours. Sans correspondance ou si l'image ne se charge pas : logo de la
playlist. Sur la playlist de test, 356 des 1 598 chaînes |FR| ont un logo net.

Programme (`Epg.kt`) : demandé au serveur Xtream Codes de la playlist (`player_api.php`,
`get_short_epg`, avec le compte et le numéro tirés de l'adresse de la chaîne), une chaîne à la fois,
seulement pour la chaîne ouverte et les favoris (le guide complet `xmltv.php` pèse ~40 Mo). Heures
en temps universel ; gardé 30 min. Sans réponse du serveur, l'appli marche comme avant.

La playlist est lue ligne par ligne (elle peut peser des centaines de Mo) ; seuls les directs
(adresses hors `/movie/` et `/series/`) sont gardés, dans `files/chaines.json` sur la télé. Les
adresses sans extension sont lues comme du MPEG-TS (sinon le lecteur ne voyait que le son).

Icône et bannière : `art/sanglier.svg` et `art/banniere.html`, rendus en PNG avec Chrome sans
écran (`--headless --screenshot`).

## Compiler et installer

```
export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
./gradlew assembleRelease
adb -s ADRESSE:5555 install -r app/build/outputs/apk/release/app-release.apk
# lien de la playlist sans le taper à la télécommande :
adb -s ADRESSE:5555 shell am start -S -n fr.gege.tv/.MainActivity --es playlist "'LIEN'"
```
