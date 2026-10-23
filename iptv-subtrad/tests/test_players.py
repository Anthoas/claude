"""Lancement de VLC : la piste traduite est sélectionnée, nommée, et seule ajoutée."""

import shutil
import stat
import time
from pathlib import Path

import pytest

from subtrad.player import VlcPlayer


def fake_binary(tmp_path: Path) -> tuple[Path, Path]:
    log = tmp_path / "argv.txt"
    script = tmp_path / "vlc"
    script.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{log}"\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script, log


def launched_args(tmp_path, **kwargs) -> list[str]:
    script, log = fake_binary(tmp_path)
    VlcPlayer(binary=str(script)).start("http://serveur/film.mkv", **kwargs).wait()
    for _ in range(50):
        if log.exists() and log.stat().st_size:
            break
        time.sleep(0.05)
    return log.read_text(encoding="utf-8").splitlines()


def test_vlc_gets_the_translated_track_with_a_real_name(tmp_path):
    args = launched_args(tmp_path, subtitle="/tmp/sous-titres.id.srt", title="Épisode 5",
                         subtitle_label="Indonésien (traduit)")
    assert args == ["--sub-file=/tmp/sous-titres.id.srt", "--no-sub-autodetect-file",
                    "--sub-description=Indonésien (traduit)", "--meta-title=Épisode 5",
                    "http://serveur/film.mkv"]


def test_vlc_without_subtitle_adds_no_subtitle_options(tmp_path):
    assert launched_args(tmp_path) == ["http://serveur/film.mkv"]


def test_player_start_accepts_the_label_for_every_player():
    import inspect

    from subtrad.player import MpvPlayer

    assert "subtitle_label" in inspect.signature(MpvPlayer.start).parameters
    assert "subtitle_label" in inspect.signature(VlcPlayer.start).parameters


@pytest.mark.skipif(not shutil.which("cvlc"), reason="VLC requis")
def test_documented_vlc_options_exist():
    """Les options passées à VLC existent bien dans la version installée."""
    import subprocess

    out = subprocess.run(["vlc", "-H", "--advanced"], capture_output=True, text=True).stdout
    if not out:  # VLC refuse de tourner en administrateur
        pytest.skip("VLC ne s'exécute pas ici (administrateur)")
    for option in ("--sub-file", "--sub-description", "--sub-autodetect-file"):
        assert option in out
