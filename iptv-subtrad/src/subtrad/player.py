"""Lancement des lecteurs externes (mpv recommandé, VLC possible)."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Emplacements habituels quand le binaire n'est pas dans le PATH.
_KNOWN_PATHS = {
    "vlc": [
        "/Applications/VLC.app/Contents/MacOS/VLC",
        r"C:\Program Files\VideoLAN\VLC\vlc.exe",
        r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
    ],
    "mpv": [
        "/Applications/mpv.app/Contents/MacOS/mpv",
        r"C:\Program Files\mpv\mpv.exe",
    ],
}


class PlayerNotFound(RuntimeError):
    pass


def find_player(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    for candidate in _KNOWN_PATHS.get(name, []):
        if Path(candidate).exists():
            return candidate
    raise PlayerNotFound(f"{name} introuvable : installe-le ou passe --lecteur-chemin.")


class MpvPlayer:
    """Pilote mpv via son socket IPC (JSON), pour ajouter/recharger des sous-titres en cours de
    lecture. L'IPC n'est utilisé que sous Linux/macOS ; sous Windows on se contente de --sub-file.
    """

    def __init__(self, binary: str | None = None):
        self.binary = binary or find_player("mpv")
        self.process: subprocess.Popen | None = None
        self.ipc_path: str | None = None

    def start(self, url: str, subtitle: str | Path | None = None, title: str | None = None):
        args = [self.binary, "--force-window=immediate"]
        if sys.platform != "win32":
            self.ipc_path = os.path.join(tempfile.mkdtemp(prefix="subtrad-"), "mpv.sock")
            args.append(f"--input-ipc-server={self.ipc_path}")
        if subtitle:
            args.append(f"--sub-file={subtitle}")
        if title:
            args.append(f"--force-media-title={title}")
        self.process = subprocess.Popen(args + [url])
        return self

    def command(self, *args) -> dict:
        if not self.ipc_path:
            raise RuntimeError("IPC mpv indisponible sur cette plateforme.")
        deadline = time.monotonic() + 10
        while not os.path.exists(self.ipc_path):
            if time.monotonic() > deadline:
                raise TimeoutError("mpv n'a pas ouvert son socket IPC.")
            time.sleep(0.1)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.connect(self.ipc_path)
            sock.sendall(json.dumps({"command": list(args)}).encode() + b"\n")
            for line in sock.makefile():
                reply = json.loads(line)
                if "event" not in reply:  # on ignore les événements asynchrones
                    return reply
        return {}

    def add_subtitle(self, path: str | Path, title: str = "Traduction") -> dict:
        return self.command("sub-add", str(path), "select", title)

    def reload_subtitle(self) -> dict:
        """À appeler quand le fichier de sous-titres a été complété (mode direct)."""
        return self.command("sub-reload")

    def wait(self) -> int:
        return self.process.wait() if self.process else 0


class VlcPlayer:
    """VLC ne sait pas recharger un fichier de sous-titres à chaud : adapté au replay/VOD."""

    def __init__(self, binary: str | None = None):
        self.binary = binary or find_player("vlc")
        self.process: subprocess.Popen | None = None

    def start(self, url: str, subtitle: str | Path | None = None, title: str | None = None):
        args = [self.binary]
        if subtitle:
            args.append(f"--sub-file={subtitle}")
        if title:
            args.append(f"--meta-title={title}")
        self.process = subprocess.Popen(args + [url])
        return self

    def wait(self) -> int:
        return self.process.wait() if self.process else 0


def make_player(name: str, binary: str | None = None):
    if name == "mpv":
        return MpvPlayer(binary)
    if name == "vlc":
        return VlcPlayer(binary)
    raise ValueError(f"Lecteur inconnu : {name}")
