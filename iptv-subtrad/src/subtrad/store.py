"""Mémoire par vidéo : ce qui a déjà été fait n'est jamais refait.

Deux choses sont gardées sur le disque, dans `~/.cache/subtrad/videos/` :
- les **sous-titres d'origine** d'une vidéo (récupérés ou transcrits), pour ne pas relire un
  fichier de plusieurs Go ni refaire une transcription de plusieurs dizaines de minutes ;
- les **sous-titres traduits** (un fichier .srt), pour rouvrir la vidéo immédiatement.

Les noms de fichiers sont des empreintes de l'adresse de la vidéo : l'adresse, qui contient
souvent un identifiant et un mot de passe, n'apparaît jamais sur le disque.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

from .cache import default_cache_path
from .subtitles import Cue, load_subtitles, save_subtitles


def default_store_dir() -> Path:
    return default_cache_path().parent / "videos"


class VideoStore:
    def __init__(self, directory: Path | None = None):
        self.directory = Path(directory) if directory else default_store_dir()

    @staticmethod
    def _key(*parts: str) -> str:
        return hashlib.sha256("\0".join(parts).encode()).hexdigest()[:32]

    # --- sous-titres d'origine ---

    def _source_path(self, url: str, language: str) -> Path:
        return self.directory / "sources" / f"{self._key(url, language)}.json"

    def load_source(self, url: str, language: str) -> tuple[list[Cue], str] | None:
        """(répliques d'origine, description de leur provenance) ou None."""
        try:
            data = json.loads(self._source_path(url, language).read_text(encoding="utf-8"))
            return [Cue(*c) for c in data["cues"]], data.get("origin", "")
        except (OSError, ValueError, TypeError, KeyError):
            return None  # absent ou abîmé : on refait

    def save_source(self, url: str, language: str, cues: list[Cue], origin: str) -> None:
        if not cues:
            return
        payload = {"origin": origin, "saved_at": int(time.time()),
                   "cues": [[c.start_ms, c.end_ms, c.text] for c in cues]}
        self._write(self._source_path(url, language), json.dumps(payload, ensure_ascii=False))

    # --- sous-titres traduits ---

    def translation_path(self, url: str, depuis: str, vers: str, model: str) -> Path:
        return self.directory / "traductions" / f"{self._key(url, depuis, vers, model)}.{vers}.srt"

    def translation_file(self, url: str, depuis: str, vers: str, model: str) -> Path | None:
        """Chemin du .srt traduit s'il existe et est lisible, sinon None."""
        path = self.translation_path(url, depuis, vers, model)
        try:
            return path if path.stat().st_size > 0 and load_subtitles(path) else None
        except Exception:
            return None

    def save_translation(self, url: str, depuis: str, vers: str, model: str,
                         cues: list[Cue]) -> Path:
        path = self.translation_path(url, depuis, vers, model)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=path.parent, prefix=".tmp-") as tmp:
            staged = save_subtitles(cues, Path(tmp) / path.name)
            os.replace(staged, path)  # remplacement d'un seul coup : jamais de fichier à moitié écrit
        return path

    def forget(self, url: str, depuis: str, vers: str, model: str) -> None:
        """Oublie tout pour cette vidéo (sous-titres d'origine et traduction)."""
        for path in (self._source_path(url, depuis),
                     self.translation_path(url, depuis, vers, model)):
            path.unlink(missing_ok=True)

    # --- outils ---

    @staticmethod
    def _write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
