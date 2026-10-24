# Consignes pour Claude (projet de l'utilisateur)

## Qui est l'utilisateur
Il n'est **pas développeur** et parle français : explique en français, simplement, étape par
étape, et dis toujours ce que tu vas faire avant de le faire. Sa compagne est indonésienne : le
but du projet est qu'elle puisse regarder en **indonésien** des vidéos françaises.

## Les deux projets de ce dépôt

### `iptv-subtrad/` : le programme principal (Python, fonctionne, testé)
Récupère les sous-titres français d'une vidéo (HLS, MKV avec index, ffmpeg, ou Whisper en dernier
recours), les traduit avec Claude (Haiku par défaut), et ouvre la vidéo dans VLC ou mpv.
- Interface web locale : `subtrad gui` (Chrome, http://127.0.0.1:8765). Voir `iptv-subtrad/README.md`
  et `iptv-subtrad/NOTICE-MAC.md` (installation sur Mac, écrite pour un non-développeur).
- Tests : `cd iptv-subtrad && python3 -m pytest -q` (≈ 90 tests, doivent tous passer).
  Style : `python3 -m pyflakes src tests`.
- Mémoire par vidéo dans `~/.cache/subtrad/videos/` ; réglages dans `~/.config/subtrad/config.json`
  (contient la clé API et le lien de la playlist : **ne jamais les afficher ni les committer**).

### `tv-debloat/` : nettoyage de sa télé (terminé)
Télé **TCL 43V6C (Android TV 12, SDK 31, processeur 32 bits `armeabi-v7a`, écran 4K avec
interface en 1080p)**, adresse `192.168.1.25` sur le Wi-Fi de la maison (c'était `192.168.1.43`
avant octobre 2026 : l'adresse peut changer, la vérifier). Le Mac est en `192.168.1.35`. Les scripts
(`scripts/00-setup.sh` pour connecter adb, etc.) ont déjà servi. Règles à garder : jamais
`pm uninstall`, jamais de root ni de flash ; seulement `pm disable-user --user 0`, par lots de 10,
avec la liste `data/protected.txt` et l'annulation `scripts/undo.sh`.

## Projet en cours : application Android TV pour la TCL 43V6C
Objectif : lire sur la télé, avec les sous-titres indonésiens, les vidéos préparées par `subtrad`.
**Le Mac reste le cerveau** (extraction, Whisper, traduction, mémoire) ; l'application de la télé
est un **lecteur** piloté à la télécommande (Kotlin, Compose for TV, Media3/ExoPlayer).

Étapes prévues, à valider avec l'utilisateur avant chacune :
1. ✅ Fait (`tele.py`, port 8766, voir « Accès depuis la télé » dans `iptv-subtrad/README.md`) :
   accès sur le Wi-Fi de la maison seulement, code à 6 chiffres (en-tête `X-Subtrad-Code`),
   activé dans ⚙ Réglages. Testé depuis le Mac ; la télé « ping » le Mac. L'appel HTTP depuis la
   télé sera testé par l'application. Playlist réelle : ~507 000 entrées (`/tele/api/ready` ≈ 2 s).
2. ✅ Écrite dans `tv-app/` (voir `tv-app/README.md`) : liste, recherche, préparation, lecture
   avec la piste « Indonésien (traduit) » sélectionnée d'office, navigation au clavier directionnel.
3. ✅ Compilée sur le Mac et installée sur la télé (octobre 2026). **Testé sur la vraie télé** :
   connexion au Mac avec le code, liste « prêtes », fiche, lecture d'un épisode 4K avec les
   sous-titres indonésiens affichés d'office au bon moment. **Pas encore testé** : « Préparer »
   depuis la télé (traduction lancée par la télé), recherche saisie au clavier de la télé.

4. ✅ Catalogue Xtream Codes (octobre 2026) : le lien de la playlist est un `get.php?username=…`,
   le même compte ouvre `player_api.php` (`subtrad/xtream.py`). Sur la télé : grilles d'affiches
   par catégorie (Séries, Films), fiche de série avec saisons et épisodes, fiche de film. Testé sur
   la télé. L'abonnement n'autorise **qu'une connexion vidéo à la fois** (`max_connections: 1`).

Piloter la télé par adb (`input keyevent`) : **vérifier d'abord que Subtrad TV est au premier
plan** (`dumpsys activity activities | grep mResumedActivity`). La famille utilise la télé (appli
ZenIPTV) : une touche envoyée à l'aveugle est arrivée une fois dans la vidéo de quelqu'un.

Ce qui est connu :
- Les vidéos protégées par DRM ne sont lisibles ni par VLC, ni par mpv, ni par l'application.
- ExoPlayer lit directement la plupart des formats ; vérifier HEVC/4K sur ce modèle à l'essai.
- Connexion adb : **cette télé n'a pas de menu « Débogage sans fil » ni d'appairage par code**.
  On se connecte avec `adb connect 192.168.1.25:5555` (« Débogage USB » activé dans les options
  pour les développeurs, il marche aussi par le Wi-Fi). Le Mac a été autorisé (« Toujours
  autoriser ») en octobre 2026. La télé doit être allumée ; si adb répond « unauthorized »,
  demander à l'utilisateur de valider le message sur la télé.
- L'application doit être compilée pour `armeabi-v7a` (32 bits) ; la télé n'a ni curl ni wget.
- Puce Realtek RTD6748. Les épisodes « 4K » de la playlist sont en **Dolby Vision profil 8**
  (HEVC 10 bits HDR10, 23,976 i/s). Le décodeur Dolby Vision de la télé ne sait pas le lire
  (images sautées) : l'application cache les décodeurs Dolby Vision et lit la couche HEVC avec
  `OMX.realtek.video.decoder` (0 image sautée), avec retour automatique au Dolby Vision si besoin.
  Journal de lecture : `adb logcat -s SubtradTV` (le tampon du journal est petit : `logcat -G 8M`).
- L'écran n'a que des modes 60 Hz et 30 Hz (pas de 24 Hz) : léger « judder » 3:2 inévitable.

## GégéTV (`gegetv/`) : application des directs pour le père de l'utilisateur
Android TV, autonome (sans Mac) : lit la playlist M3U, garde les directs, onglets ★ Favoris /
Rechercher / Réglages, favoris ajoutés / retirés par **appui long sur OK** dans les listes (question
Oui / Non ; aucun bouton pendant la vidéo, à la demande de l'utilisateur), zapping haut / bas
entre favoris (seulement si la chaîne regardée est un favori), favoris protégés contre les pertes
(`Favorites.kt` : écriture sûre, 5 sauvegardes, réparation par le nom ; XCIPTV, l'appli qu'utilisait
le père, perdait ses favoris), programme (EPG Xtream `get_short_epg`) dans
le bandeau et sous chaque favori. Paquet `fr.gege.tv` (coexiste avec
Subtrad TV). Icône : tête de sanglier (`gegetv/art/`). Testé sur la TCL avec la playlist de
l'utilisateur (octobre 2026) : chargement (~2 min la première fois), recherche, favoris, son et
décodeur vidéo HEVC démarrés, image de TF1 vue sur une capture (la capture la montre parfois
noire : couche vidéo matérielle), programme de TF1 affiché (octobre 2026). Deuxième télé de l'utilisateur pour les essais : **Philips 2021/22 UHD Android TV**
(Android 11, SDK 30, `armeabi-v7a`, puce MediaTek `mt5895`), `192.168.1.29:5555`, autorisée en
octobre 2026. Sur cette Philips, la vidéo en `SurfaceView` (affichée *derrière* l'appli) restait cachée
par le fond de la fenêtre (son sans image). GégéTV utilise une `TextureView` (directs SDR, vérifié
sur les deux télés). **Subtrad TV garde la `SurfaceView`** (une `TextureView` rend le HDR sombre et
terne) avec une fenêtre sans fond et un écran de lecture transparent : image normale et sous-titres
indonésiens confirmés à l'œil sur la Philips (octobre 2026). Les captures d'écran de la Philips
montrent la vidéo HDR en couleurs fausses (vert/blanc) : ne pas s'y fier. Son clavier à l'écran garde les flèches : Retour le ferme. Télé du père : adresse adb et lien
de playlist à demander.

## Règles de travail
- Ne jamais écrire dans le dépôt, un message, une capture ou un journal : clé API, mots de passe,
  adresses de flux IPTV (elles contiennent identifiant et mot de passe).
- Tester avant de dire que ça marche ; dire clairement ce qui n'a pas pu être testé.
- Pas de contournement de DRM ni d'aide à l'accès à des contenus sans droit : le programme est un
  outil générique de sous-titrage, pas un fournisseur de contenu.
- Commits clairs, en anglais ; ne pas créer de pull request sans qu'il le demande.
