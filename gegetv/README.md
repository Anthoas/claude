# GégéTV — les directs, simplement

Application Android TV pour regarder les **chaînes en direct** d'une playlist IPTV, sans
traduction et sans Mac : elle lit elle-même la playlist M3U.

- **Menu de gauche** (style ZenIPTV) : tête de sanglier, puis Favoris (étoile), Rechercher (loupe),
  Réglages (engrenage) ; petite icône et son nom, page affichée sur fond arrondi, passer sur un
  bouton ouvre sa page. Noms de chaînes affichés sans le préfixe de pays (« |FR| »).
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
- **Réglages**, deux onglets :
  - **Sources** : les comptes Xtream Codes enregistrés (nom, adresse du serveur, identifiant, mot de
    passe), « ● Utilisée » sur celle en service. OK sur une source : « Utiliser cette source » ou
    « Supprimer » (confirmation ; ses favoris et sa liste sont effacés). « + Ajouter une source » :
    le compte est vérifié auprès du serveur avant d'être gardé. Une seule source à la fois, chacune
    garde ses favoris (`files/favoris/<source>/`) et sa liste (`files/chaines-<source>.json`).
  - **Chaînes** : source utilisée, nombre de chaînes, date de la liste, « Recharger maintenant ».
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

Les chaînes sont demandées au serveur Xtream Codes (`player_api.php`, `get_live_categories` et
`get_live_streams` : ~3 s pour 7 000 chaînes, au lieu de ~2 min pour la playlist M3U complète).
Adresse d'une chaîne : `serveur/identifiant/mot de passe/numéro`, lue comme du MPEG-TS (sinon le
lecteur ne voyait que le son). Première ouverture de cette version : l'ancien lien `get.php`
devient la source « Ma source », avec sa liste et ses favoris (rattachés par numéro de chaîne).

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

## Version avec une source déjà prête (télé sans Mac à côté)

Pour installer GégéTV chez quelqu'un sans pouvoir taper la source sur place : créer le fichier privé
`gegetv/source-preinstallee.properties` (ignoré par git, jamais dans le dépôt) :

```
nom=Gérard
serveur=http://serveur:port
identifiant=…
mot_de_passe=…
```

puis compiler : au premier lancement, l'appli ajoute cette source et l'utilise (une seule fois ; si
on la supprime, elle ne revient pas). Retirer le fichier ensuite, sinon toutes les versions compilées
l'emportent. Le fichier de la source « Gérard » est gardé hors du dépôt dans
`~/.config/gegetv/source-gerard.properties`.

