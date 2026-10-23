"""Cache SQLite des traductions : on ne repaie jamais deux fois la même réplique."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path


def default_cache_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "subtrad" / "translations.sqlite"


class TranslationCache:
    def __init__(self, path: str | Path | None = None):
        path = Path(path) if path else default_cache_path()
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path))
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS translations (key TEXT PRIMARY KEY, text TEXT NOT NULL)"
        )

    @staticmethod
    def key(namespace: str, text: str) -> str:
        return hashlib.sha256(f"{namespace}\0{text}".encode()).hexdigest()

    def get_many(self, namespace: str, texts: list[str]) -> dict[str, str]:
        found = {}
        for text in set(texts):
            row = self._db.execute(
                "SELECT text FROM translations WHERE key = ?", (self.key(namespace, text),)
            ).fetchone()
            if row:
                found[text] = row[0]
        return found

    def put_many(self, namespace: str, pairs: dict[str, str]) -> None:
        with self._db:
            self._db.executemany(
                "INSERT OR REPLACE INTO translations (key, text) VALUES (?, ?)",
                [(self.key(namespace, src), dst) for src, dst in pairs.items()],
            )

    def close(self) -> None:
        self._db.close()
