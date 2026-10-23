import http.server
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from subtrad.mkv import MkvFastPathUnavailable, RangeReader, block_text, read_mkv_subtitles

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg requis")

SRT = """1
00:00:01,000 --> 00:00:02,500
Bonjour à tous.

2
00:00:04,000 --> 00:00:06,000
<i>Deux lignes</i>
sur l'écran.

3
00:00:08,000 --> 00:00:09,000
Au revoir.
"""


def make_mkv(tmp_path: Path, codec="srt", language="fre", to_pipe=False, name="film.mkv",
             big=False) -> Path:
    srt = tmp_path / "in.srt"
    srt.write_text(SRT, encoding="utf-8")
    out = tmp_path / name
    video = "testsrc2=s=320x240:r=25:d=10" if big else "color=c=black:s=64x64:r=5:d=10"
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", video,
           "-i", str(srt), "-map", "0:v", "-map", "1:s", "-c:v", "libx264", "-crf", "10", "-c:s", codec,
           "-metadata:s:s:0", f"language={language}"]
    if to_pipe:  # écrit en flux continu : pas d'index (Cues) dans le fichier
        with open(out, "wb") as f:
            subprocess.run(cmd + ["-f", "matroska", "-"], stdout=f, check=True)
    else:
        subprocess.run(cmd + [str(out)], check=True)
    return out


def test_reads_srt_subtitles_from_the_index(tmp_path):
    progress = []
    cues, track = read_mkv_subtitles(str(make_mkv(tmp_path)), "fr", on_progress=progress.append)
    assert [(c.start_ms, c.end_ms, c.text) for c in cues] == [
        (1000, 2500, "Bonjour à tous."),
        (4000, 6000, "Deux lignes\nsur l'écran."),
        (8000, 9000, "Au revoir."),
    ]
    assert track.codec == "S_TEXT/UTF8" and track.language == "fre"
    assert progress[-1] == 1.0


def test_reads_ass_subtitles(tmp_path):
    cues, track = read_mkv_subtitles(str(make_mkv(tmp_path, codec="ass")), "fr")
    assert track.codec == "S_TEXT/ASS"
    assert [c.text for c in cues] == ["Bonjour à tous.", "Deux lignes\nsur l'écran.", "Au revoir."]


def test_missing_index_or_language_means_fallback(tmp_path):
    with pytest.raises(MkvFastPathUnavailable):
        read_mkv_subtitles(str(make_mkv(tmp_path, to_pipe=True, name="sans-index.mkv")), "fr")
    with pytest.raises(MkvFastPathUnavailable):
        read_mkv_subtitles(str(make_mkv(tmp_path, language="eng")), "fr")
    not_mkv = tmp_path / "x.mkv"
    not_mkv.write_bytes(b"\x00" * 100)
    with pytest.raises(MkvFastPathUnavailable):
        read_mkv_subtitles(str(not_mkv), "fr")


def test_block_text_cleans_ass_and_html():
    ass = "12,0,Default,,0,0,0,,{\\i1}Salut{\\i0}\\Nça va ?".encode()
    assert block_text("S_TEXT/ASS", ass) == "Salut\nça va ?"
    assert block_text("S_TEXT/UTF8", "<b>Gras</b> et <font color=red>rouge</font>".encode()) == "Gras et rouge"


class _RangeHandler(http.server.SimpleHTTPRequestHandler):
    supports_range = True
    requested = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        path = Path(self.directory) / self.path.lstrip("/")
        data = path.read_bytes()
        rng = self.headers.get("Range")
        if rng and self.supports_range:
            a, _, b = rng[6:].partition("-")
            start, end = int(a), min(int(b), len(data) - 1)
            type(self).requested.append(end - start + 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
            body = data[start : end + 1]
        else:
            self.send_response(200)
            body = data
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def http_dir(tmp_path):
    handler = type("H", (_RangeHandler,), {"requested": []})
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), lambda *a, **k: handler(*a, directory=str(tmp_path), **k))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", handler
    server.shutdown()


def test_over_http_only_small_ranges_are_downloaded(tmp_path, http_dir):
    base, handler = http_dir
    size = make_mkv(tmp_path, big=True).stat().st_size
    assert size > 500_000
    reader = RangeReader(f"{base}/film.mkv")
    reader._session().trust_env = False  # pas de proxy pour 127.0.0.1
    cues, _ = read_mkv_subtitles(f"{base}/film.mkv", "fr", reader=reader, workers=1)
    assert len(cues) == 3
    assert sum(handler.requested) < size / 10  # une petite partie du fichier seulement


def test_server_without_range_support_means_fallback(tmp_path, http_dir):
    base, handler = http_dir
    handler.supports_range = False
    make_mkv(tmp_path)
    reader = RangeReader(f"{base}/film.mkv")
    reader._session().trust_env = False
    with pytest.raises(MkvFastPathUnavailable):
        read_mkv_subtitles(f"{base}/film.mkv", "fr", reader=reader)
