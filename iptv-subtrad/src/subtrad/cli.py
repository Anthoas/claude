"""Interface en ligne de commande : `subtrad <commande> ...`."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from . import extract
from .cache import TranslationCache
from .hls import HlsClient
from .pipeline import fetch_source_subtitles
from .playlist import load_playlist
from .subtitles import load_subtitles, save_subtitles
from .translate import DEFAULT_MODEL, ClaudeTranslator, translate_cues


def _progress(done: int, total: int) -> None:
    print(f"\r  traduction : {done}/{total} répliques", end="", file=sys.stderr, flush=True)
    if done == total:
        print(file=sys.stderr)


def _translator(args) -> ClaudeTranslator:
    return ClaudeTranslator(
        source=args.depuis, target=args.vers, model=args.modele, effort=args.effort
    )


def cmd_chaines(args) -> int:
    for i, ch in enumerate(load_playlist(args.playlist)):
        if args.filtre and args.filtre.lower() not in f"{ch.name} {ch.group}".lower():
            continue
        group = f"[{ch.group}] " if ch.group else ""
        print(f"{i:4d}  {group}{ch.name}\n      {ch.url}")
    return 0


def cmd_pistes(args) -> int:
    tracks = HlsClient().list_subtitle_tracks(args.url)
    for t in tracks:
        flags = " ".join(f for f, on in [("défaut", t.default), ("forcée", t.forced),
                                         ("SME", t.sdh)] if on)
        print(f"HLS      {t.language or '?':5s} {t.name} {flags}\n         {t.uri}")
    try:
        embedded = extract.probe_subtitle_tracks(args.url)
    except Exception as exc:
        embedded = []
        print(f"(ffprobe : {exc})", file=sys.stderr)
    for t in embedded:
        kind = "texte" if t.is_text else "image"
        print(f"intégrée 0:s:{t.index}  {t.language or '?':5s} {t.codec} ({kind}) {t.title}")
    if not tracks and not embedded:
        print("Aucune piste de sous-titres trouvée.")
        return 1
    return 0


def cmd_traduire(args) -> int:
    cues = load_subtitles(args.entree)
    out = Path(args.sortie or Path(args.entree).with_suffix(f".{args.vers}.srt"))
    translated = translate_cues(
        cues, _translator(args), TranslationCache(), args.lot, on_progress=_progress
    )
    save_subtitles(translated, out)
    print(f"{len(translated)} répliques écrites dans {out}")
    return 0


def cmd_regarder(args) -> int:
    from .player import make_player  # import tardif : inutile pour les autres commandes

    print("Recherche des sous-titres…", file=sys.stderr)
    source = fetch_source_subtitles(args.url, args.depuis, prefer_sdh=args.sme)
    print(f"  {len(source.cues)} répliques ({source.origin})", file=sys.stderr)

    translated = translate_cues(
        source.cues, _translator(args), TranslationCache(), args.lot, on_progress=_progress
    )
    sub_path = Path(args.sortie) if args.sortie else (
        Path(tempfile.mkdtemp(prefix="subtrad-")) / f"sous-titres.{args.vers}.srt"
    )
    save_subtitles(translated, sub_path)
    print(f"  sous-titres traduits : {sub_path}", file=sys.stderr)

    player = make_player(args.lecteur, args.lecteur_chemin)
    return player.start(args.url, sub_path).wait()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="subtrad", description="Traduit les sous-titres d'un flux IPTV avec Claude."
    )
    sub = parser.add_subparsers(dest="commande", required=True)

    p = sub.add_parser("chaines", help="lister les chaînes d'une playlist M3U")
    p.add_argument("playlist", help="URL ou fichier .m3u")
    p.add_argument("--filtre", help="ne garder que les chaînes contenant ce texte")
    p.set_defaults(func=cmd_chaines)

    p = sub.add_parser("pistes", help="lister les pistes de sous-titres d'un flux")
    p.add_argument("url")
    p.set_defaults(func=cmd_pistes)

    translation = argparse.ArgumentParser(add_help=False)
    translation.add_argument("--depuis", default="fr", help="langue source (défaut : fr)")
    translation.add_argument("--vers", default="id", help="langue cible (défaut : id)")
    translation.add_argument("--modele", default=DEFAULT_MODEL, help="modèle Claude")
    translation.add_argument("--effort", default="low",
                             choices=["low", "medium", "high", "xhigh", "max"],
                             help="effort de réflexion du modèle (défaut : low, plus rapide)")
    translation.add_argument("--lot", type=int, default=40,
                             help="nombre de répliques par requête (défaut : 40)")
    translation.add_argument("-o", "--sortie", help="fichier de sous-titres à écrire")

    p = sub.add_parser("traduire", parents=[translation],
                       help="traduire un fichier de sous-titres local (.srt, .vtt, .ass)")
    p.add_argument("entree")
    p.set_defaults(func=cmd_traduire)

    p = sub.add_parser("regarder", parents=[translation],
                       help="récupérer, traduire et lire un flux (replay / VOD)")
    p.add_argument("url")
    p.add_argument("--lecteur", default="mpv", choices=["mpv", "vlc"])
    p.add_argument("--lecteur-chemin", help="chemin du binaire du lecteur")
    p.add_argument("--sme", action="store_true",
                   help="préférer les sous-titres pour sourds et malentendants")
    p.set_defaults(func=cmd_regarder)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
