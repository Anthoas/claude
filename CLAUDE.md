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
2. Écrire l'application (liste, recherche, lecture avec la piste « Indonésien (traduit) »
   sélectionnée d'office, navigation au clavier directionnel).
3. Compiler sur le Mac (JDK 17 + outils en ligne de commande Android, pas besoin d'Android Studio),
   installer par `adb install`, tester sur la vraie télé, corriger.

Ce qui est connu :
- Les vidéos protégées par DRM ne sont lisibles ni par VLC, ni par mpv, ni par l'application.
- ExoPlayer lit directement la plupart des formats ; vérifier HEVC/4K sur ce modèle à l'essai.
- Connexion adb : **cette télé n'a pas de menu « Débogage sans fil » ni d'appairage par code**.
  On se connecte avec `adb connect 192.168.1.25:5555` (« Débogage USB » activé dans les options
  pour les développeurs, il marche aussi par le Wi-Fi). Le Mac a été autorisé (« Toujours
  autoriser ») en octobre 2026. La télé doit être allumée ; si adb répond « unauthorized »,
  demander à l'utilisateur de valider le message sur la télé.
- L'application doit être compilée pour `armeabi-v7a` (32 bits) ; la télé n'a ni curl ni wget.

## Règles de travail
- Ne jamais écrire dans le dépôt, un message, une capture ou un journal : clé API, mots de passe,
  adresses de flux IPTV (elles contiennent identifiant et mot de passe).
- Tester avant de dire que ça marche ; dire clairement ce qui n'a pas pu être testé.
- Pas de contournement de DRM ni d'aide à l'accès à des contenus sans droit : le programme est un
  outil générique de sous-titrage, pas un fournisseur de contenu.
- Commits clairs, en anglais ; ne pas créer de pull request sans qu'il le demande.
