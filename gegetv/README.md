# GégéTV — les directs, simplement

Application Android TV pour regarder les **chaînes en direct** d'une playlist IPTV, sans
traduction et sans Mac : elle lit elle-même la playlist M3U.

- **★ Favoris** (à l'ouverture) : grille des chaînes favorites, OK pour regarder ; sous chaque
  chaîne, l'émission en cours et une barre qui montre où elle en est (mise à jour chaque minute).
- **Rechercher** : nom d'une chaîne (sans accents ni majuscules), chaînes françaises d'abord ;
  ★ sur celles déjà en favori. Haut/bas sortent du champ de saisie.
- **Réglages** : lien de la playlist (masqué), « Enregistrer et actualiser la liste des chaînes ».
- **Lecture** : plein écran ; un bandeau (logo, nom, émission en cours avec horaires, avancement
  et résumé, émission suivante, « ☆ Ajouter aux favoris » / « ★ Retirer », Retour) s'affiche à
  l'ouverture et à chaque appui sur OK, puis se cache après 6 s.

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
