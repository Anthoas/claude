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
- Tests : `cd iptv-subtrad && python3 -m pytest -q` (≈ 80 tests, doivent tous passer).
  Style : `python3 -m pyflakes src tests`.
- Mémoire par vidéo dans `~/.cache/subtrad/videos/` ; réglages dans `~/.config/subtrad/config.json`
  (contient la clé API et le lien de la playlist : **ne jamais les afficher ni les committer**).

### `tv-debloat/` : nettoyage de sa télé (terminé)
Télé **TCL 43V6C (Android TV)**, adresse `192.168.1.43` sur le Wi-Fi de la maison. Les scripts
(`scripts/00-setup.sh` pour connecter adb, etc.) ont déjà servi. Règles à garder : jamais
`pm uninstall`, jamais de root ni de flash ; seulement `pm disable-user --user 0`, par lots de 10,
avec la liste `data/protected.txt` et l'annulation `scripts/undo.sh`.

## Projet en cours : application Android TV pour la TCL 43V6C
Objectif : lire sur la télé, avec les sous-titres indonésiens, les vidéos préparées par `subtrad`.
**Le Mac reste le cerveau** (extraction, Whisper, traduction, mémoire) ; l'application de la télé
est un **lecteur** piloté à la télécommande (Kotlin, Compose for TV, Media3/ExoPlayer).

Étapes prévues, à valider avec l'utilisateur avant chacune :
1. Rendre `subtrad` accessible sur le Wi-Fi de la maison (écoute sur le réseau local), **protégé
   par un code** ; ne jamais exposer à Internet. Ajouter un point d'accès qui donne la liste des
   vidéos, l'état d'avancement et le fichier `.srt` traduit.
2. Écrire l'application (liste, recherche, lecture avec la piste « Indonésien (traduit) »
   sélectionnée d'office, navigation au clavier directionnel).
3. Compiler sur le Mac (JDK 17 + outils en ligne de commande Android, pas besoin d'Android Studio),
   installer par `adb install`, tester sur la vraie télé, corriger.

Ce qui est connu :
- Les vidéos protégées par DRM ne sont lisibles ni par VLC, ni par mpv, ni par l'application.
- ExoPlayer lit directement la plupart des formats ; vérifier HEVC/4K sur ce modèle à l'essai.
- La connexion adb sans fil d'Android 11+ demande un **appairage interactif** : le code à 6 chiffres
  et le port d'appairage s'affichent sur la télé (le port de connexion est un autre port, pas
  toujours 5555). Les demander à l'utilisateur, ne pas les deviner. La télé doit être allumée ;
  le débogage sans fil peut se désactiver après un redémarrage.

## Règles de travail
- Ne jamais écrire dans le dépôt, un message, une capture ou un journal : clé API, mots de passe,
  adresses de flux IPTV (elles contiennent identifiant et mot de passe).
- Tester avant de dire que ça marche ; dire clairement ce qui n'a pas pu être testé.
- Pas de contournement de DRM ni d'aide à l'accès à des contenus sans droit : le programme est un
  outil générique de sous-titrage, pas un fournisseur de contenu.
- Commits clairs, en anglais ; ne pas créer de pull request sans qu'il le demande.
