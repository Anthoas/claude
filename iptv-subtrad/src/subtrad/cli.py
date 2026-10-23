"""Interface en ligne de commande : `subtrad <commande> ...`."""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile
from pathlib import Path

from . import extract
from .cache import TranslationCache
from .demo import demo_cues, demo_video_url
from .errors import friendly_error
from .hls import HlsClient
from .pipeline import fetch_source_subtitles
from .playlist import load_playlist
from .subtitles import load_subtitles, save_subtitles
from .translate import DEFAULT_MODEL, ClaudeTranslator, TranslationPipeline


def _progress(done: int, total: int) -> None:
    print(f"\r  traduction : {done}/{total} répliques", end="", file=sys.stderr, flush=True)
    if done == total:
        print(file=sys.stderr)


def _status(message: str, fraction: float | None = None) -> None:
    """Affiche l'étape en cours sur une seule ligne qui se met à jour."""
    print(f"\r\033[K  {message}", end="", file=sys.stderr, flush=True)


def _translate_all(cues, translator, batch_size: int):
    """Traduit toutes les répliques, plusieurs lots en parallèle."""
    if not cues:
        return []
    pipeline = TranslationPipeline(
        translator, TranslationCache(), batch_size, workers=4,
        on_batch=lambda _: _progress(pipeline.translated, len(cues)),
    )
    pipeline.add(cues)
    return pipeline.finish()


def _whisper_factory(args):
    if not getattr(args, "transcrire", False):
        return None
    from .transcribe import make_transcriber

    return make_transcriber


def _translator(args) -> ClaudeTranslator:
    return ClaudeTranslator(
        source=args.depuis, target=args.vers, model=args.modele, effort=args.effort
    )


def _print_usage(translator: ClaudeTranslator) -> None:
    print(f"  {translator.usage_summary()}", file=sys.stderr)


def _fmt_time(ms: int) -> str:
    return f"{ms // 60000:02d}:{ms // 1000 % 60:02d}"


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
    translator = _translator(args)
    translated = _translate_all(cues, translator, args.lot)
    _print_usage(translator)
    save_subtitles(translated, out)
    print(f"{len(translated)} répliques écrites dans {out}")
    return 0


def cmd_demo(args) -> int:
    from .player import MpvPlayer

    cues = demo_cues()
    translator = _translator(args)
    print(f"Traduction de la scène de démonstration ({len(cues)} répliques)…", file=sys.stderr)
    translated = _translate_all(cues, translator, args.lot)
    _print_usage(translator)
    print()
    for src, dst in zip(cues, translated):
        print(f"[{_fmt_time(src.start_ms)}] {src.text.replace(chr(10), ' / ')}")
        print(f"        -> {dst.text.replace(chr(10), ' / ')}")
    if args.sans_lecture:
        return 0

    sub_path = Path(args.sortie) if args.sortie else (
        Path(tempfile.mkdtemp(prefix="subtrad-")) / f"demo.{args.vers}.srt"
    )
    save_subtitles(translated, sub_path)
    print("\nOuverture de mpv (écran uni : seuls les sous-titres comptent)…", file=sys.stderr)
    return MpvPlayer(args.lecteur_chemin).start(demo_video_url(), sub_path).wait()


def cmd_regarder(args) -> int:
    from .player import make_player  # import tardif : inutile pour les autres commandes

    print("Recherche des sous-titres…", file=sys.stderr)
    source = fetch_source_subtitles(args.url, args.depuis, prefer_sdh=args.sme, on_status=_status,
                                    transcriber_factory=_whisper_factory(args))
    print("\r\033[K", end="", file=sys.stderr)
    if source.live_track:
        return _regarder_direct(args, source)
    print(f"  {len(source.cues)} répliques ({source.origin})", file=sys.stderr)

    translator = _translator(args)
    translated = _translate_all(source.cues, translator, args.lot)
    _print_usage(translator)
    sub_path = Path(args.sortie) if args.sortie else (
        Path(tempfile.mkdtemp(prefix="subtrad-")) / f"sous-titres.{args.vers}.srt"
    )
    save_subtitles(translated, sub_path)
    print(f"  sous-titres traduits : {sub_path}", file=sys.stderr)

    player = make_player(args.lecteur, args.lecteur_chemin)
    return player.start(args.url, sub_path).wait()


def _regarder_direct(args, source) -> int:
    from .live import run_live
    from .player import MpvPlayer

    if args.lecteur != "mpv":
        raise SystemExit(
            "Erreur : le direct n'est géré qu'avec mpv (VLC ne permet pas d'afficher les "
            "sous-titres au fil de l'eau). Relance avec --lecteur mpv."
        )
    print(f"  direct : {source.origin}", file=sys.stderr)
    print(f"  lecture {args.marge} segments derrière le direct, le temps de traduire.",
          file=sys.stderr)
    player = MpvPlayer(args.lecteur_chemin, font_size=args.taille)
    translator = _translator(args)
    try:
        return run_live(
            args.url, source.live_track, translator, player, TranslationCache(),
            batch_size=args.lot, segments_behind=args.marge,
            offset_ms=int(args.decalage * 1000),
        )
    finally:
        _print_usage(translator)


def cmd_transcrire(args) -> int:
    from .extract import probe
    from .transcribe import iter_transcribed_cues, make_transcriber

    transcriber = make_transcriber(args.modele_whisper)
    groups = iter_transcribed_cues(args.url, transcriber, args.langue, probe(args.url).duration,
                                   on_status=_status)
    cues = [cue for group in groups for cue in group]
    print("\r\033[K", end="", file=sys.stderr)
    out = Path(args.sortie or f"transcription.{args.langue}.srt")
    save_subtitles(cues, out)
    print(f"{len(cues)} répliques écrites dans {out}")
    return 0


def cmd_gui(args) -> int:
    from .gui import run_gui

    return run_gui(port=args.port, open_browser=not args.sans_navigateur, tv_port=args.port_tele)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="subtrad", description="Traduit les sous-titres d'un flux IPTV avec Claude."
    )
    sub = parser.add_subparsers(dest="commande", required=True)

    p = sub.add_parser("gui", help="ouvrir l'interface graphique dans Chrome")
    p.add_argument("--port", type=int, default=8765, help="port local (défaut : 8765)")
    p.add_argument("--sans-navigateur", action="store_true",
                   help="ne pas ouvrir le navigateur automatiquement")
    p.add_argument("--port-tele", type=int, default=8766,
                   help="port de l'accès télé sur le Wi-Fi de la maison (défaut : 8766)")
    p.set_defaults(func=cmd_gui)

    p = sub.add_parser("transcrire", help="transcrire la voix d'une vidéo avec Whisper (sans traduire)")
    p.add_argument("url", help="URL ou fichier vidéo")
    p.add_argument("--langue", default="fr", help="langue parlée (défaut : fr)")
    p.add_argument("--modele-whisper", help="modèle Whisper (défaut : le meilleur pour ce Mac)")
    p.add_argument("-o", "--sortie", help="fichier .srt à écrire")
    p.set_defaults(func=cmd_transcrire)

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

    p = sub.add_parser("demo", parents=[translation],
                       help="tester sur une scène de 2 minutes en français parlé")
    p.add_argument("--lecteur-chemin", help="chemin du binaire de mpv")
    p.add_argument("--sans-lecture", action="store_true",
                   help="afficher la traduction dans le Terminal sans ouvrir mpv")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("regarder", parents=[translation],
                       help="récupérer, traduire et lire un flux (replay ou direct)")
    p.add_argument("url")
    p.add_argument("--lecteur", default="mpv", choices=["mpv", "vlc"])
    p.add_argument("--lecteur-chemin", help="chemin du binaire du lecteur")
    p.add_argument("--sme", action="store_true",
                   help="préférer les sous-titres pour sourds et malentendants")
    p.add_argument("--transcrire", action="store_true",
                   help="sans sous-titres en texte, transcrire la voix avec Whisper")
    live = p.add_argument_group("direct (mpv uniquement)")
    live.add_argument("--marge", type=int, default=6,
                      help="segments de retard sur le direct, le temps de traduire (défaut : 6)")
    live.add_argument("--decalage", type=float, default=0.0,
                      help="décalage des sous-titres en secondes, > 0 pour les retarder")
    live.add_argument("--taille", type=int, default=44,
                      help="taille du texte, pour une image de 720 px de haut (défaut : 44)")
    p.set_defaults(func=cmd_regarder)

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="  %(message)s")
    logging.getLogger("subtrad").setLevel(logging.INFO)
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"Erreur : {friendly_error(exc)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
