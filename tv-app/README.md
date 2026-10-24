# Subtrad TV — lecteur Android TV pour subtrad

Application pour la télé TCL 43V6C (Android TV 12). **Le Mac fait tout le travail** (récupération
des sous-titres, Whisper, traduction, mémoire) ; la télé cherche, demande une préparation, puis lit
la vidéo avec la piste « Indonésien (traduit) » choisie d'office.

- Kotlin, Compose for TV (`androidx.tv:tv-material`), Media3/ExoPlayer (HLS compris).
- Textes en indonésien (par défaut) et en français (`values-fr`) selon la langue de la télé.
- Pas de code natif : un seul APK convient au processeur 32 bits de la télé.
- Parle au Mac via l'accès télé de subtrad (`iptv-subtrad/README.md`, « Accès depuis la télé »),
  en HTTP sur le Wi-Fi de la maison, avec l'en-tête `X-Subtrad-Code`.
- Le .srt est téléchargé sur la télé avant la lecture : le flux vidéo est lu directement depuis son
  serveur, qui ne reçoit jamais le code.

## Écrans

| Écran | Rôle |
|---|---|
| Connexion | adresse du Mac (`192.168.1.35:8766`) et code à 6 chiffres |
| Accueil | onglets Siap ditonton / Film / Serial, recherche, « Muat lebih banyak » |
| Fiche | Tonton et Hapus (supprimer, deux appuis) si prêt ; sinon Siapkan (préparation suivie chaque seconde), Cek subtitle |
| Lecture | ExoPlayer plein écran ; Retour pour quitter |

## Compiler (étape 3, sur le Mac)

Déjà installé sur le Mac (octobre 2026) : JDK 17, Gradle, outils Android en ligne de commande,
plateforme 35 et build-tools 35.0.0 (pas d'Android Studio). `local.properties` (ignoré par git)
pointe vers le kit Android.

```
export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
echo "sdk.dir=/opt/homebrew/share/android-commandlinetools" > local.properties   # si absent
./gradlew assembleRelease
adb -s 192.168.1.25:5555 install -r app/build/outputs/apk/release/app-release.apk
```

Sur une machine neuve : `brew install openjdk@17 gradle`,
`brew install --cask android-commandlinetools`, puis
`sdkmanager "platforms;android-35" "build-tools;35.0.0"` (après `sdkmanager --licenses`).

## Régler la télé sans la télécommande

Les deux valeurs doivent être données ensemble (une autre application ne peut pas détourner le code) :

```
adb shell am start -S -n fr.subtrad.tv/.MainActivity --es address 192.168.1.35:8766 --es code CODE
```

## Réglages (onglets)

- **Connexion au Mac** : adresse et code (une fois connecté, le sélecteur arrive sur l'onglet, sans
  ouvrir le clavier).
- **Sources** : les sources du Mac (une seule utilisée à la fois : seules ses vidéos apparaissent).
  OK sur une source : « Utiliser cette source », « Annuler » ou « Supprimer » (confirmation).
  « + Ajouter une source » (Xtream Codes : nom, adresse du serveur, identifiant, mot de passe) : le
  Mac vérifie le compte et télécharge sa liste (≈ 1 min) ; identifiant et mot de passe partent vers
  le Mac par le Wi-Fi de la maison et ne reviennent jamais vers la télé.

Dans les champs de saisie, les quatre flèches font sortir du champ (sinon gauche/droite déplaçaient
le curseur et « Réglages » était inaccessible depuis la recherche).

## Menu de gauche (style ZenIPTV)

Colonne étroite à gauche : le S vert, puis Prêtes à regarder, Films, Séries, Rechercher (la page
s'affiche dès qu'on passe sur le bouton) et Réglages (s'ouvre avec OK). Petites icônes Material
(`res/drawable/ic_*.xml`) avec leur nom. La page Rechercher a ses propres résultats (« Chercher
dans : Films / Séries », recherches récentes), sans toucher aux pages Films et Séries.

