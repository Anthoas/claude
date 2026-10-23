"""Choix de la bonne piste (jamais la « forcée »), et raisons affichées quand c'est lent."""

import http.server
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

from subtrad import extract
from subtrad.extract import EmbeddedTrack, choose_embedded_track
from subtrad.mkv import read_mkv_subtitles
from subtrad.pipeline import check_subtitles, open_cue_source

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg requis")

FULL = "1\n00:00:01,000 --> 00:00:02,000\nBonjour à tous.\n\n2\n00:00:04,000 --> 00:00:05,000\nComment ça va ?\n\n3\n00:00:07,000 --> 00:00:08,000\nTrès bien.\n"
FORCED = "1\n00:00:05,000 --> 00:00:06,000\nValar morghulis.\n"


def make_film(tmp_path: Path, name="film.mkv", forced_first=True, codec="srt", forced_only=False) -> Path:
    (tmp_path / "full.srt").write_text(FULL, encoding="utf-8")
    (tmp_path / "forced.srt").write_text(FORCED, encoding="utf-8")
    inputs = ["-i", str(tmp_path / "forced.srt")]
    if not forced_only:
        inputs += ["-i", str(tmp_path / "full.srt")]
        if not forced_first:
            inputs = ["-i", str(tmp_path / "full.srt"), "-i", str(tmp_path / "forced.srt")]
    n = len(inputs) // 2
    forced_index = (0 if forced_first or forced_only else 1)
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=5:d=10", *inputs,
           "-map", "0:v", *[a for i in range(n) for a in ("-map", f"{i + 1}:s")],
           "-c:v", "libx264", "-c:s", codec]
    for i in range(n):
        cmd += [f"-metadata:s:s:{i}", "language=fre"]
    cmd += [f"-disposition:s:{forced_index}", "forced", f"-metadata:s:s:{forced_index}", "title=Français (forcés)",
            str(tmp_path / name)]
    subprocess.run(cmd, check=True)
    return tmp_path / name


def test_forced_track_is_never_preferred():
    forced = EmbeddedTrack(0, "subrip", "fre", "Français", forced=True)
    titled = EmbeddedTrack(1, "subrip", "fre", "Forcés")  # drapeau absent, mais le titre le dit
    sdh = EmbeddedTrack(2, "subrip", "fre", "Français SDH")
    plain = EmbeddedTrack(3, "subrip", "fre", "Français")
    image = EmbeddedTrack(4, "hdmv_pgs_subtitle", "fre", "")
    english = EmbeddedTrack(5, "subrip", "eng", "English")
    tracks = [forced, titled, sdh, plain, image, english]
    assert choose_embedded_track(tracks, "fr") is plain
    assert choose_embedded_track(tracks, "fr", prefer_sdh=True) is sdh
    assert choose_embedded_track([forced, titled], "fr") is forced  # à défaut, la forcée
    assert choose_embedded_track(tracks, "de") is None


@needs_ffmpeg
@pytest.mark.parametrize("forced_first", [True, False])
def test_full_read_picks_the_full_track_not_the_forced_one(tmp_path, forced_first):
    film = make_film(tmp_path, forced_first=forced_first)
    info = extract.probe(str(film))
    assert sorted(t.looks_forced for t in info.tracks) == [False, True]
    notes = []
    source = open_cue_source(str(film), "fr", on_note=notes.append)
    texts = [c.text for group in source.groups for c in group]
    assert texts == ["Bonjour à tous.", "Comment ça va ?", "Très bien."]
    assert not any("forcés" in n for n in notes)


@needs_ffmpeg
def test_only_forced_tracks_are_reported(tmp_path):
    film = make_film(tmp_path, forced_only=True)
    notes = []
    open_cue_source(str(film), "fr", on_note=notes.append)
    assert any("forcés" in n for n in notes)
    check = check_subtitles(str(film), "fr")
    assert check.ok is False and "forcés" in check.message


@needs_ffmpeg
def test_non_mkv_container_explains_why_it_is_slow(tmp_path):
    film = make_film(tmp_path, name="film.mp4", codec="mov_text")
    notes = []
    source = open_cue_source(str(film), "fr", on_note=notes.append)
    assert source.kind == "ffmpeg" and any("pas un MKV" in n for n in notes)


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Refuse (503) toute requête qui arrive pendant qu'une autre est en cours, comme un serveur
    qui limite les connexions simultanées."""

    busy = 0
    lock = threading.Lock()
    supports_range = True

    def log_message(self, *args):
        pass

    def do_GET(self):
        cls = type(self)
        with cls.lock:
            if cls.busy:
                self.send_response(503)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            cls.busy += 1
        try:
            time.sleep(0.005)
            data = (Path(self.directory) / self.path.lstrip("/")).read_bytes()
            a, _, b = self.headers["Range"][6:].partition("-")
            start, end = int(a), min(int(b), len(data) - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
            body = data[start : end + 1]
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        finally:
            with cls.lock:
                cls.busy -= 1


@needs_ffmpeg
def test_server_refusing_parallel_requests_falls_back_to_one_connection(tmp_path, monkeypatch):
    make_film(tmp_path, forced_first=False)
    handler = type("H", (_Handler,), {"busy": 0, "lock": threading.Lock()})
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), lambda *a, **k: handler(*a, directory=str(tmp_path), **k))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    try:
        cues, _ = read_mkv_subtitles(f"http://127.0.0.1:{server.server_address[1]}/film.mkv", "fr",
                                     workers=4)
    finally:
        server.shutdown()
    assert [c.text for c in cues] == ["Bonjour à tous.", "Comment ça va ?", "Très bien."]
