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
import threading
import time
from pathlib import Path

from .cache import default_cache_path
from .subtitles import Cue, load_subtitles, save_subtitles


def default_store_dir() -> Path:
    return default_cache_path().parent / "videos"


WATCHED_FRACTION = 0.9  # au-delà, la vidéo est « vue »


class VideoStore:
    def __init__(self, directory: Path | None = None):
        self.directory = Path(directory) if directory else default_store_dir()
        self._progress_lock = threading.Lock()
        self._progress: dict | None = None

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

    def translated_names(self) -> set[str]:
        """Noms des fichiers traduits présents : une seule lecture du dossier, même pour une
        playlist de plusieurs centaines de milliers d'entrées."""
        try:
            return {entry.name for entry in os.scandir(self.directory / "traductions")}
        except OSError:
            return set()

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

    # --- avancement de la lecture (ce qui a été regardé) ---

    def _progress_data(self) -> dict:
        if self._progress is None:
            try:
                self._progress = json.loads((self.directory / "progress.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._progress = {}
        return self._progress

    def save_progress(self, url: str, position_ms: int, duration_ms: int, ended: bool = False) -> dict:
        """Retient où la lecture s'est arrêtée. « Vu » reste acquis même si on la revoit."""
        key = self._key(url)
        with self._progress_lock:
            data = self._progress_data()
            old = data.get(key, {})
            position, duration = max(0, int(position_ms)), max(0, int(duration_ms))
            watched = bool(old.get("watched")) or ended or (
                duration > 0 and position >= duration * WATCHED_FRACTION)
            data[key] = {"position": 0 if ended else position, "duration": duration or old.get("duration", 0),
                         "watched": watched, "updated": int(time.time())}
            self._write(self.directory / "progress.json", json.dumps(data))
            return dict(data[key])

    def progress(self, url: str) -> dict:
        """{"position": ms, "duration": ms, "watched": bool, "progress": 0 à 1}."""
        with self._progress_lock:
            entry = dict(self._progress_data().get(self._key(url), {}))
        position, duration = entry.get("position", 0), entry.get("duration", 0)
        return {"position": position, "duration": duration, "watched": bool(entry.get("watched")),
                "progress": round(min(1.0, position / duration), 3) if duration else 0.0}

    # --- outils ---

    @staticmethod
    def _write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
