"""Scène de démonstration : deux minutes de français parlé, pleines d'expressions imagées.

Sert à juger la qualité d'une traduction et la lecture dans mpv sans dépendre d'un flux
externe : la vidéo est un fond uni généré par ffmpeg, c'est le texte qui compte.
"""

from __future__ import annotations

from .subtitles import Cue

# (début en secondes, fin en secondes, texte)
_SCRIPT = [
    (2.0, 4.0, "[Sonnerie d'un téléphone]"),
    (4.5, 6.5, "Allô ? Théo, c'est toi ?"),
    (7.0, 9.5, "Oui, c'est moi. Tu dors encore ou quoi ?"),
    (10.0, 13.0, "Non non, je suis debout depuis une heure.\nEnfin... depuis cinq minutes."),
    (13.5, 16.0, "Ça ne se voit pas. Tu as vu l'heure ?"),
    (16.5, 19.0, "Il est neuf heures ?! Mince alors,\nj'ai complètement zappé !"),
    (19.5, 22.5, "On devait voir Léa à dix heures,\ntu te souviens ?"),
    (23.0, 25.5, "Bien sûr que je m'en souviens.\nJe ne vais pas lui poser un lapin."),
    (26.0, 28.5, "La dernière fois, elle a attendu\nune heure sous la pluie."),
    (29.0, 31.5, "Il pleuvait des cordes, en plus.\nLa pauvre."),
    (32.0, 34.5, "[Bruit de casseroles]"),
    (35.0, 37.0, "Qu'est-ce que tu fabriques ?"),
    (37.5, 40.5, "Je prépare un petit-déjeuner.\nJ'ai un petit creux."),
    (41.0, 43.5, "Tu n'as pas le temps !\nOn va être en retard."),
    (44.0, 46.5, "Relax. C'est pas la mer à boire,\non y sera dans vingt minutes."),
    (47.0, 50.0, "Tu dis toujours ça, et on arrive\ntoujours à la bourre."),
    (50.5, 53.0, "Bon, d'accord. Je mets les bouchées doubles."),
    (53.5, 56.0, "Tu peux me filer un coup de main ?\nMes clés ont disparu."),
    (56.5, 59.5, "Elles sont dans ta poche.\nComme d'habitude."),
    (60.0, 62.0, "Ah ! Ben voilà."),
    (62.5, 65.0, "Tu as pris ton parapluie ?"),
    (65.5, 68.0, "Non. Il fait grand soleil, regarde."),
    (68.5, 71.0, "Fais-moi confiance :\nça va tourner d'une minute à l'autre."),
    (71.5, 74.0, "Tu as raison, je le prends.\nOn n'est jamais trop prudent."),
    (74.5, 77.0, "[Porte qui claque]"),
    (77.5, 80.0, "Dis, tu sais ce que ça coûte,\nun taxi à cette heure-ci ?"),
    (80.5, 83.5, "Ça coûte les yeux de la tête.\nOn prend le bus."),
    (84.0, 86.5, "Le bus ? Mais il ne passe\nque tous les quarts d'heure !"),
    (87.0, 90.0, "Alors on court. Allez, courage !"),
    (90.5, 93.0, "[Souffle court] Je n'en peux plus..."),
    (93.5, 96.5, "Tu as le cafard, ce matin ?\nTu n'es pas dans ton assiette."),
    (97.0, 100.0, "Non, c'est juste que j'ai\nun chat dans la gorge."),
    (100.5, 103.0, "Léa ! Salut ! Désolés pour le retard !"),
    (103.5, 106.5, "Pas de souci. Je viens d'arriver,\nmoi aussi."),
    (107.0, 110.0, "Ouf ! On a eu chaud."),
    (110.5, 113.5, "Alors, on se prend un petit café\navant d'aller au marché ?"),
    (114.0, 117.0, "Avec plaisir. C'est moi qui offre."),
    (117.5, 120.5, "Ah non, c'est la fin des haricots :\nj'ai oublié mon portefeuille."),
    (121.0, 124.0, "Quel étourdi ! Tu es vraiment\nla tête en l'air."),
    (124.5, 127.0, "[Rires]"),
    (127.5, 130.5, "Allez, ce sera pour moi.\nMais tu me revaudras ça."),
]


def demo_cues() -> list[Cue]:
    return [Cue(round(s * 1000), round(e * 1000), text) for s, e, text in _SCRIPT]


def demo_duration_s() -> int:
    return int(_SCRIPT[-1][1]) + 3


def demo_video_url() -> str:
    """Source vidéo générée à la volée par ffmpeg (fond uni, sans fichier à télécharger)."""
    return f"av://lavfi:color=c=0x1b2a41:s=1280x720:r=25:d={demo_duration_s()}"
