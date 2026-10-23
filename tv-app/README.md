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
| Fiche | Tonton (prêt) ; sinon Siapkan (préparation suivie chaque seconde), Cek subtitle |
| Lecture | ExoPlayer plein écran ; Retour pour quitter |

## Compiler (étape 3, sur le Mac)

Il faut un JDK 17 et les outils Android en ligne de commande (pas d'Android Studio) :

```
brew install openjdk@17 gradle
brew install --cask android-commandlinetools
sdkmanager "platform-tools" "platforms;android-35" "build-tools;35.0.0"
gradle wrapper --gradle-version 8.11.1   # une seule fois, dans tv-app/
./gradlew assembleRelease
adb install -r app/build/outputs/apk/release/app-release.apk
```

## Régler la télé sans la télécommande

Les deux valeurs doivent être données ensemble (une autre application ne peut pas détourner le code) :

```
adb shell am start -S -n fr.subtrad.tv/.MainActivity --es address 192.168.1.35:8766 --es code CODE
```
