# Notice d'utilisation sur Mac

Ce guide s'adresse à quelqu'un qui n'a jamais utilisé le Terminal. Compte une demi-heure pour
la première installation. Tu ne la fais qu'une fois.

## Ce que fait le programme

Tu lui donnes l'adresse d'une vidéo (replay ou chaîne en direct). Il récupère les sous-titres
français, les traduit en indonésien avec Claude, puis ouvre la vidéo dans le lecteur **mpv**
avec les sous-titres traduits.

## Le Terminal en deux mots

Le Terminal est une fenêtre où l'on tape des commandes. Pour l'ouvrir : touches **⌘ + Espace**,
tape `Terminal`, puis Entrée. Pour exécuter une commande, tape-la (ou colle-la) et appuie sur
**Entrée**. Rien ne se passe tant que tu n'as pas appuyé sur Entrée.

Dans ce guide, les lignes grises sont à copier-coller telles quelles dans le Terminal.

## Étape 1 : récupérer le programme

1. Sur GitHub, ouvre le dépôt `anthoas/claude` et choisis la branche
   `claude/awesome-johnson-5ksrnk` (menu déroulant en haut à gauche).
2. Clique sur le bouton vert **Code**, puis **Download ZIP**.
3. Le fichier arrive dans **Téléchargements**. Double-clique dessus pour le décompresser.
4. Dans le dossier obtenu, repère le sous-dossier **`iptv-subtrad`**.

## Étape 2 : installer Homebrew

Homebrew est un « magasin d'applications » pour le Terminal. Il installe le reste.

Ouvre le Terminal et colle cette ligne :

```
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

- Il demande le **mot de passe de ton Mac**. Tu ne verras rien s'écrire quand tu le tapes,
  c'est normal. Valide avec Entrée.
- À la fin, il affiche un encadré « **Next steps** » avec deux commandes à copier-coller
  (elles commencent par `echo` et `eval`). **Exécute-les**, puis passe à l'étape suivante.
  Sur les Mac récents (puce Apple M1, M2, M3...), cette étape est indispensable.
- Vérifie que ça marche : tape `brew --version`. Un numéro de version doit s'afficher.

## Étape 3 : installer les outils

Colle ces deux lignes, une à la fois (elles installent les lecteurs vidéo VLC et mpv, ffmpeg et
un outil pour installer le programme) :

```
brew install mpv ffmpeg pipx
brew install --cask vlc
```

(Si VLC est déjà dans ton dossier Applications, la deuxième ligne le signale simplement.)

Puis celle-ci :

```
pipx ensurepath
```

**Ferme complètement le Terminal** (⌘ + Q) puis rouvre-le.

## Étape 4 : installer le programme

1. Dans le Terminal, tape `cd ` (avec une espace après).
2. **Glisse le dossier `iptv-subtrad` depuis le Finder dans la fenêtre du Terminal** : son
   chemin s'écrit tout seul. Appuie sur Entrée.
3. Colle :

```
pipx install .
```

**Attention au point à la fin** : tape `pipx install`, une espace, puis un point. Sans lui, le
Terminal répond « the following arguments are required: package_spec ». Quand l'installation
est finie, `subtrad --help` doit afficher la liste des commandes.

Si tu modifies ou mets à jour le programme plus tard, relance dans ce dossier :
`pipx install --force .`

## Étape 4 bis : installer Whisper (pour les vidéos sans sous-titres)

Whisper transcrit la voix des vidéos qui n'ont pas de sous-titres en texte. Il tourne **sur ton
Mac**, gratuitement ; seule la traduction reste payante. Une seule commande :

```
brew install whisper-cpp
```

C'est tout : pas de `pipx` à relancer. Au **premier** usage, le programme télécharge le modèle
de Whisper (~550 Mo, une seule fois) ; la progression s'affiche dans la page.

- Sur un Mac à puce Apple (M1, M2, M3, M4 : menu  > « À propos de ce Mac »), Whisper utilise la
  puce graphique et va vite. Sur un Mac Intel il fonctionne aussi, mais plus lentement.
- Pour l'essayer seul, sans rien traduire : `subtrad transcrire "chemin ou adresse de la vidéo"`.
  Il écrit un fichier `transcription.fr.srt`.

## Étape 5 : obtenir la clé d'accès à Claude

Claude est un service payant à l'usage, séparé d'un éventuel abonnement.

1. Crée un compte sur **console.anthropic.com**.
2. Ajoute un peu de crédit (5 dollars suffisent largement pour commencer).
3. Va dans **API Keys**, clique sur **Create Key** et copie la clé (elle commence par `sk-ant-`).
4. Dans le Terminal, colle la ligne suivante **en remplaçant `sk-ant-ta-cle-ici` par ta clé**
   (garde les guillemets) :

```
echo 'export ANTHROPIC_API_KEY="sk-ant-ta-cle-ici"' >> ~/.zshrc
```

5. **Ferme et rouvre le Terminal.**

Cette clé est un mot de passe : ne la partage avec personne.

**Coût :** pour un film, je l'estime à quelques centimes ou dizaines de centimes. Ce n'est pas
mesuré : regarde ta consommation sur console.anthropic.com après les premiers essais. Les
traductions sont mémorisées : revoir le même programme ne coûte rien.

## Étape 5 bis : tester sans aucune source vidéo

```
subtrad demo
```

Le programme traduit une scène de 2 minutes en français parlé (avec des expressions imagées
comme « poser un lapin » ou « c'est la fin des haricots »), affiche dans le Terminal chaque
phrase avec sa traduction, puis ouvre mpv sur un écran uni avec les sous-titres traduits.
C'est le meilleur moyen de juger la qualité de l'indonésien et la synchronisation.

- `subtrad demo --sans-lecture` affiche seulement le tableau original / traduction.
- `subtrad demo --modele claude-sonnet-5-5` essaie un modèle plus puissant, mais environ 20 fois
  plus cher (voir « Coût » plus bas), pour comparer la qualité.

## Étape 6 : l'interface graphique (le plus simple)

```
subtrad gui
```

Chrome s'ouvre sur la page du programme. **Laisse la fenêtre du Terminal ouverte** tant que
tu utilises la page ; pour tout arrêter, reviens dans le Terminal et fais **Ctrl + C**.

1. **La première fois**, colle le lien M3U de ta playlist et clique sur **Charger** (une
   grosse playlist peut prendre une minute). Elle est gardée sur ce Mac : les fois suivantes,
   la liste s'affiche directement. Le bouton **↻ Actualiser** la retélécharge.
2. **Cherche** dans la barre du haut : les accents et majuscules ne comptent pas, et tu peux
   taper plusieurs mots (« diner cons »). Les onglets **Direct / Films / Séries** et la liste des
   catégories affinent la recherche.
3. **Sous-titres ?** vérifie, sans rien dépenser, ce qui est possible pour cette vidéo :
   - **✓ vert** : sous-titres trouvés, récupérés en quelques secondes ;
   - **✓ orange** : sous-titres trouvés, mais il faudra lire tout le fichier vidéo (plusieurs
     minutes pour un film) ;
   - **◐ orange** : pas de sous-titres en texte, la voix sera transcrite par Whisper (plus long) ;
   - **✗ rouge** : impossible ; la raison s'affiche.
4. **▶ Regarder traduit** : une carte en bas à droite montre où en est le programme :
   - la **récupération des sous-titres** (avec un pourcentage et le temps restant quand il faut
     lire le fichier, ou l'avancement de la transcription Whisper) ;
   - la **traduction**, qui avance **en même temps** : plusieurs morceaux sont envoyés à Claude
     en parallèle ;
   - puis la **lecture**, dans le lecteur choisi dans les réglages :
     - **VLC** (par défaut) s'ouvre quand toute la traduction est prête ;
     - **mpv** (« démarrage rapide ») s'ouvre au bout de quelques secondes et reçoit la suite des
       sous-titres pendant la lecture : c'est le plus rapide, surtout avec Whisper.

   Le bouton **Annuler** arrête tout à n'importe quel moment ; pendant la lecture, il devient
   **Arrêter** et ferme la vidéo.
5. **⚙ Réglages** : clé Claude (déjà détectée si tu as fait l'étape 5), modèle (Haiku par
   défaut), langues, **lecteur vidéo** (VLC ou mpv), **Whisper** (transcrire la voix quand il
   n'y a pas de sous-titres) et changement de playlist.

Le lien de la playlist et la clé Claude sont enregistrés uniquement sur ce Mac, dans des
fichiers que toi seul peux lire.

## Étape 6 bis : regarder sur la télé (application en préparation)

Dans **⚙ Réglages**, choisis **Regarder sur la télé : Activé**, puis **Enregistrer**. La fenêtre
affiche alors l'**adresse** du Mac (par exemple `192.168.1.35:8766`) et un **code à 6 chiffres** :
ce sont eux qu'il faudra taper dans l'application de la télé (une seule fois).

- Seuls les appareils de la maison peuvent s'en servir, et seulement avec le code. Ce n'est
  jamais ouvert sur Internet. **Changer le code de la télé** le remplace si tu l'as donné à quelqu'un.
- Le Mac doit rester **allumé** avec `subtrad gui` ouvert : c'est lui qui prépare et traduit.
- Une vidéo préparée depuis la télé apparaît aussi dans les cartes de progression du Mac
  (« pour la télé ») ; aucun lecteur ne s'ouvre sur le Mac.

## Étape 7 : les commandes du Terminal (pour aller plus loin)

**Règle importante :** mets toujours l'adresse entre guillemets `"..."`. Sans eux, le Terminal
coupe l'adresse au premier `&` ou `?` et rien ne fonctionne.

### a) Lister les chaînes de ta playlist

```
subtrad chaines "ton_lien_ou_fichier.m3u" --filtre arte
```

Si tu as un fichier `.m3u` sur ton Mac, tu peux le glisser dans le Terminal à la place du
texte entre guillemets. `--filtre arte` ne garde que les chaînes dont le nom contient « arte ».
Chaque chaîne s'affiche avec son adresse : c'est elle qu'il faut copier pour la suite.

### b) Vérifier qu'une chaîne a des sous-titres utilisables (à faire en premier)

```
subtrad pistes "adresse_de_la_chaine"
```

- Une ligne qui commence par `HLS fr` : **c'est bon**.
- Seulement des pistes marquées « image », ou rien du tout : ce flux n'est pas utilisable pour
  l'instant.

### c) Regarder avec les sous-titres traduits

```
subtrad regarder "adresse_de_la_chaine"
```

- **Replay / film** : le programme traduit tout (quelques minutes), puis ouvre mpv.
- **Direct** : mpv s'ouvre tout de suite et lit la chaîne avec environ 30 secondes de retard.
  C'est voulu : ce délai laisse le temps à la traduction d'arriver.

### d) Traduire un fichier de sous-titres que tu as déjà

```
subtrad traduire "mon_fichier.srt"
```

Le résultat est écrit à côté, dans un fichier `mon_fichier.id.srt`.

## Coût : voir ce que chaque traduction a coûté

À la fin de chaque traduction, le programme affiche une ligne du type :
`coût estimé : 0,031 $, 22 requêtes, 40 000 tokens envoyés et 30 000 reçus`.
C'est une estimation, à comparer avec console.anthropic.com.

Le modèle par défaut est `claude-haiku-5-5` : environ 5 centimes pour un film (estimation).
Si une traduction te semble trop approximative, ajoute `--modele claude-sonnet-5-5` à la
commande : meilleur sur les passages difficiles, mais environ 20 fois plus cher (de l'ordre
d'un dollar par film).

## Mettre à jour le programme

Quand je corrige ou améliore le programme, refais ceci :
1. Retélécharge le ZIP (étape 1) et décompresse-le.
2. Dans le Terminal : `cd ` (avec une espace), glisse le **nouveau** dossier `iptv-subtrad`
   dans la fenêtre, puis Entrée.
3. Tape `pipx install --force .` (n'oublie pas le point) et Entrée.

## Dans mpv

| Touche | Action |
|---|---|
| Espace | pause / reprise |
| F | plein écran |
| ← / → | reculer / avancer de 5 secondes |
| V | afficher / masquer les sous-titres (replay) |
| Q | quitter |

Pour tout arrêter depuis le Terminal : **Ctrl + C**.

## Réglages (à ajouter à la fin de la commande `regarder`)

| Besoin | Option |
|---|---|
| Sous-titres en avance sur la voix (direct) | `--decalage 1` (les retarde d'1 seconde) |
| Sous-titres en retard sur la voix (direct) | `--decalage -1` (les avance d'1 seconde) |
| Sous-titres qui manquent par moments (direct) | `--marge 8` (plus de délai pour traduire) |
| Texte trop petit ou trop grand (direct) | `--taille 55` ou `--taille 36` |
| Sous-titres pour sourds et malentendants | `--sme` |
| Utiliser VLC à la place de mpv (replay seulement) | `--lecteur vlc` |

Exemple : `subtrad regarder "adresse" --decalage -1 --marge 8`

Pour VLC, installe-le d'abord avec `brew install --cask vlc`.

## Plusieurs sources (⚙ Réglages > Sources)

Tu peux garder **plusieurs sources** en même temps : leurs vidéos apparaissent toutes dans la même
liste, avec le nom de la source sous chaque titre. Dans **⚙ Réglages > Sources > + Ajouter une
source**, trois façons :
- **Lien M3U** : colle le lien de la playlist ;
- **Serveur + identifiant** : tape l'adresse du serveur (ex. `http://monserveur.com:8080`), ton
  identifiant et ton mot de passe ; le programme en déduit le lien (au format standard
  `.../get.php?username=…&password=…`). Si ton service utilise un autre format, prends « Lien M3U » ;
- **Fichier** : choisis un fichier `.m3u` enregistré sur le Mac.

Le nom est facultatif (par défaut : l'adresse du serveur). Une source n'est enregistrée que si sa
playlist se charge vraiment ; en cas d'erreur (mauvais mot de passe, serveur éteint…) la raison
s'affiche et rien n'est enregistré. Quand tu as plusieurs sources, un menu **Toutes les sources**
apparaît à côté de la recherche pour n'en regarder qu'une.

- **Actualiser** (en haut, ou source par source dans les réglages) retélécharge les playlists ;
  une source en panne n'empêche pas les autres de se mettre à jour.
- **Supprimer** retire la source ; les vidéos déjà traduites restent gardées.
- Ton ancienne playlist unique est reprise automatiquement sous le nom « Playlist ».
- Les identifiants sont gardés sur ce Mac uniquement, dans un fichier que toi seul peux lire, et
  la page ne les affiche jamais.

## Dans VLC : la bonne piste de sous-titres

À l'ouverture, VLC affiche **directement la piste « Indonésien (traduit) »** : tu n'as rien à
choisir. Les sous-titres d'origine du fichier (français, anglais, « forcés »…) restent dans le menu
**Sous-titres > Piste de sous-titres**, mais VLC n'en affiche **qu'une à la fois**, donc à l'écran il
n'y a que l'indonésien. Cette liste est celle du fichier : VLC ne permet pas de la masquer.

## Rien n'est refait deux fois

Le programme **garde** ce qu'il a fait pour chaque vidéo, dans `~/.cache/subtrad/videos/` :
- dès qu'une traduction est terminée, la vidéo porte le badge **✓ déjà traduit** dans la liste,
  et le bouton devient **▶ Regarder (prêt)** : elle s'ouvre **tout de suite**, sans lire le
  fichier, sans traduire, **sans frais** (et même sans clé Claude) ;
- les **sous-titres d'origine** sont gardés dès qu'ils sont récupérés : si tu changes de modèle ou de
  langue, seule la traduction est refaite, pas la lecture du fichier ;
- **Refaire** (à côté du bouton) oublie tout pour cette vidéo, si tu veux tout recommencer.

Si tu annules ou fermes une vidéo avant la fin de la préparation, rien n'est gardé (on ne garde
jamais un travail incomplet) : la fois suivante, la préparation recommence au début.

## Si c'est long : lire la ligne orange

Quand un fichier ne peut pas être lu rapidement, la carte de progression affiche en **orange** la
raison (par exemple « Lecture rapide impossible (le serveur ne permet pas la lecture par
morceaux) » ou « ce fichier n'est pas un MKV »). Dans ce cas, il faut lire tout le fichier :
compte plusieurs minutes. Astuce : choisis **mpv** dans les réglages, la vidéo démarre alors au
bout de quelques secondes pendant que la suite se prépare.

Le programme évite aussi tout seul les sous-titres « **forcés** » (quelques répliques seulement) ;
s'il n'y en a pas d'autres, il le dit.

## En cas de problème

| Ce que tu vois | Cause probable | Solution |
|---|---|---|
| `command not found: brew` | Étape 2 incomplète | Refaire les deux commandes de l'encadré « Next steps », puis rouvrir le Terminal |
| `command not found: subtrad` | `pipx ensurepath` oublié ou Terminal non rouvert | Refaire l'étape 3 et rouvrir le Terminal |
| Erreur « authentication » / « API key » | Clé mal copiée ou Terminal non rouvert | Refaire l'étape 5 |
| « mpv introuvable » | Installation incomplète | `brew install mpv`, puis rouvrir le Terminal |
| « vlc introuvable » | VLC n'est pas installé | `brew install --cask vlc` (ou choisir mpv dans les réglages) |
| « Whisper n'est pas installé » | Étape 4 bis non faite | `brew install whisper-cpp`, ou désactiver Whisper dans les réglages |
| « Aucun sous-titre exploitable trouvé » | La chaîne n'expose pas de sous-titres texte | Voir « Limites » |
| Une erreur longue en rouge | Variable | Copie le message complet et envoie-le moi |

## Limites

- **Je n'ai pas pu tester avec un vrai flux ni sur un Mac.** Il y aura peut-être des
  ajustements à faire. Si quelque chose bloque, envoie-moi le message d'erreur exact.
- Sans Whisper, le programme ne marche que si la vidéo fournit des **sous-titres en texte**.
  Le bouton **Sous-titres ?** le dit avant de lancer quoi que ce soit.
- Whisper n'est pas encore utilisé pour les **directs** (seulement les films et séries).
- Les flux protégés par DRM (chiffrés) ne peuvent être lus ni par VLC ni par mpv.
- Un direct n'est géré que s'il est au format HLS (adresse en `.m3u8`) avec des sous-titres en
  pistes séparées. Une adresse qui finit en `.ts` ne convient pas pour le direct.
