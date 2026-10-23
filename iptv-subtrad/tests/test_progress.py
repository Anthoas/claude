import shutil
import subprocess

import pytest

from subtrad.extract import EmbeddedTrack, extract_text_track, parse_progress_line
from subtrad.pipeline import format_duration


def test_parse_progress_line():
    assert parse_progress_line("out_time_us=1500000\n") == 1.5
    assert parse_progress_line("out_time_ms=2500000") == 2.5  # ffmpeg : en réalité des microsecondes
    assert parse_progress_line("out_time_us=N/A") is None
    assert parse_progress_line("progress=continue") is None
    assert parse_progress_line("bitrate=  12.3kbits/s") is None


def test_format_duration():
    assert format_duration(7) == "7 s"
    assert format_duration(75) == "1 min 15 s"
    assert format_duration(600) == "10 min 00 s"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg requis")
def test_extraction_reports_progress_and_returns_cues(tmp_path):
    srt = tmp_path / "in.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nBonjour\n\n2\n00:00:08,000 --> 00:00:09,000\nMerci\n")
    video = tmp_path / "film.mkv"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=5:d=10",
         "-i", str(srt), "-map", "0:v", "-map", "1:s", "-c:v", "libx264", "-c:s", "srt", str(video)],
        check=True,
    )
    seen = []
    cues = extract_text_track(str(video), EmbeddedTrack(0, "subrip", "fre", ""), duration=10,
                              on_progress=seen.append)
    assert [c.text for c in cues] == ["Bonjour", "Merci"]
    assert seen and seen[-1] == 1.0 and all(0 <= f <= 1 for f in seen)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg requis")
def test_extraction_error_is_explained_without_the_url(tmp_path):
    with pytest.raises(RuntimeError) as err:
        extract_text_track(str(tmp_path / "absent.mkv"), EmbeddedTrack(0, "subrip", "fre", ""))
    assert "ffmpeg n'a pas pu lire" in str(err.value)
