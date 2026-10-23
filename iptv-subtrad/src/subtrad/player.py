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


class MpvIpc:
    """Connexion JSON persistante au serveur IPC de mpv (socket Unix, ou tube nommé Windows)."""

    def __init__(self, path: str, timeout: float = 10.0):
        deadline = time.monotonic() + timeout
        while True:
            try:
                self._open(path)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise TimeoutError("mpv n'a pas ouvert son serveur IPC.") from None
                time.sleep(0.1)
        self._next_id = 0

    def _open(self, path: str) -> None:
        if sys.platform == "win32":
            pipe = open(path, "r+b", buffering=0)
            self._reader, self._write, self._close = pipe, pipe.write, pipe.close
        else:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(path)
            self._reader, self._write, self._close = sock.makefile("rb"), sock.sendall, sock.close

    def request(self, command) -> dict:
        """Envoie une commande (liste d'arguments ou dict nommé) et attend sa réponse."""
        self._next_id += 1
        message = {"command": command, "request_id": self._next_id}
        self._write(json.dumps(message).encode() + b"\n")
        while True:
            line = self._reader.readline()
            if not line:
                raise ConnectionError("mpv a fermé la connexion IPC.")
            reply = json.loads(line)
            # Les événements asynchrones (pause, fin de fichier...) n'ont pas de request_id.
            if reply.get("request_id") == self._next_id:
                return reply

    def close(self) -> None:
        self._close()


def ass_escape(text: str) -> str:
    """Rend un texte sûr pour l'OSD de mpv (format ASS : accolades et antislash spéciaux)."""
    text = text.replace("\\", "\\\u2060").replace("{", "\\{").replace("}", "\\}")
    return text.replace("\n", "\\N")


class MpvPlayer:
    """Pilote mpv. En replay, les sous-titres traduits sont passés en fichier (--sub-file) ;
    en direct, on les dessine en surimpression via l'IPC, calés sur l'horloge du flux.
    """

    OVERLAY_ID = 1

    def __init__(self, binary: str | None = None, font_size: int = 44):
        self.binary = binary or find_player("mpv")
        self.font_size = font_size  # sur une hauteur de référence de 720 px
        self.process: subprocess.Popen | None = None
        self.ipc_path: str | None = None
        self._ipc: MpvIpc | None = None

    def start(
        self,
        url: str,
        subtitle: str | Path | None = None,
        title: str | None = None,
        live_segments_behind: int | None = None,
        hide_original_subs: bool = False,
        subtitle_label: str | None = None,  # ignoré : mpv affiche le nom du fichier
    ):
        """Lance mpv. `live_segments_behind` active le mode direct : la lecture démarre
        ce nombre de segments derrière le direct, pour laisser à la traduction le temps
        d'arriver avant l'image.
        """
        if sys.platform == "win32":
            self.ipc_path = rf"\\.\pipe\subtrad-{os.getpid()}"
        else:
            self.ipc_path = os.path.join(tempfile.mkdtemp(prefix="subtrad-"), "mpv.sock")
        args = [self.binary, "--force-window=immediate", f"--input-ipc-server={self.ipc_path}"]
        if subtitle:
            args.append(f"--sub-file={subtitle}")
        if live_segments_behind is not None:
            args += [
                # time-pos = horodatage réel du flux, la référence des sous-titres HLS.
                "--rebase-start-time=no",
                f"--demuxer-lavf-o-append=live_start_index=-{live_segments_behind}",
                # Pas de sous-titres d'origine par-dessus la traduction.
                "--sid=no",
            ]
        elif hide_original_subs:
            args.append("--sid=no")  # nos sous-titres sont dessinés par-dessus (display_loop)
        if title:
            args.append(f"--force-media-title={title}")
        self.process = subprocess.Popen(args + [url])
        return self

    def stop(self) -> None:
        if self.is_running():
            self.process.terminate()

    @property
    def ipc(self) -> MpvIpc:
        if self._ipc is None:
            self._ipc = MpvIpc(self.ipc_path)
        return self._ipc

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def time_pos(self) -> float | None:
        """Position de lecture en secondes, ou None tant que la vidéo n'a pas démarré."""
        reply = self.ipc.request(["get_property", "time-pos"])
        return reply.get("data") if reply.get("error") == "success" else None

    def show_overlay(self, text: str) -> None:
        style = f"{{\\an2\\fs{self.font_size}\\bord2.5\\shad1}}"
        self.ipc.request({
            "name": "osd-overlay", "id": self.OVERLAY_ID, "format": "ass-events",
            "data": style + ass_escape(text), "res_y": 720,
        })

    def hide_overlay(self) -> None:
        self.ipc.request({
            "name": "osd-overlay", "id": self.OVERLAY_ID, "format": "none", "data": "",
        })

    def wait(self) -> int:
        code = self.process.wait() if self.process else 0
        if self._ipc:
            self._ipc.close()
        return code


class VlcPlayer:
    """VLC ne sait pas recharger un fichier de sous-titres à chaud : il reçoit les sous-titres
    traduits au lancement, une fois la traduction terminée (replay / VOD)."""

    def __init__(self, binary: str | None = None):
        self.binary = binary or find_player("vlc")
        self.process: subprocess.Popen | None = None

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()

    def start(self, url: str, subtitle: str | Path | None = None, title: str | None = None,
              subtitle_label: str | None = None, **_ignored):
        args = [self.binary]
        if subtitle:
            # VLC sélectionne tout seul une piste ajoutée avec --sub-file (vérifié : elle passe
            # devant la piste intégrée « par défaut »). On lui donne un vrai nom dans le menu au
            # lieu de « Track 4 », et on l'empêche d'aller chercher d'autres fichiers .srt.
            args += [f"--sub-file={subtitle}", "--no-sub-autodetect-file"]
            if subtitle_label:
                args.append(f"--sub-description={subtitle_label}")
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
