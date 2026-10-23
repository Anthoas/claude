import json
import os
import socket
import sys
import tempfile
import threading

import pytest

from subtrad.hls import HlsClient, PtsUnwrapper, SubtitleTrack, parse_vtt_segment
from subtrad.live import LiveSubtitleFeed, LiveTranslator, Timeline, display_loop
from subtrad.player import MpvIpc, ass_escape
from subtrad.subtitles import Cue

from test_hls import FakeSession

URI = "https://live.example.com/subs/fr.m3u8"
TRACK = SubtitleTrack(uri=URI, language="fr", name="Français", group_id="subs")


def segment(local_start: str, text: str, mpegts: int = 900000) -> str:
    return (
        f"WEBVTT\nX-TIMESTAMP-MAP=MPEGTS:{mpegts},LOCAL:00:00:00.000\n\n"
        f"{local_start} --> 00:00:59.000\n{text}\n"
    )


def playlist(sequence: int, names: list[str]) -> str:
    body = "".join(f"#EXTINF:6.0,\n{n}\n" for n in names)
    return f"#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXT-X-MEDIA-SEQUENCE:{sequence}\n{body}"


def test_vtt_segment_is_placed_on_video_clock():
    cues = parse_vtt_segment(segment("00:00:01.500", "Bonjour", mpegts=900000))
    # MPEGTS 900000 / 90 kHz = 10 s ; LOCAL 0 -> la réplique à 1,5 s est à 11,5 s.
    assert cues == [Cue(11_500, 69_000, "Bonjour")]


def test_pts_unwrap_after_33_bit_rollover():
    unwrap = PtsUnwrapper()
    wrap_ms = (1 << 33) * 1000 // 90_000
    assert unwrap(wrap_ms - 2_000) == wrap_ms - 2_000
    assert unwrap(1_000) == wrap_ms + 1_000  # le compteur est repassé par zéro


def test_feed_returns_only_new_cues_on_sliding_window():
    pages = {
        URI: playlist(0, ["s0.vtt", "s1.vtt"]),
        "https://live.example.com/subs/s0.vtt": segment("00:00:01.000", "Un"),
        "https://live.example.com/subs/s1.vtt": segment("00:00:01.000", "Un")  # chevauchement
        .replace("\n\n", "\n\n00:00:07.000 --> 00:00:08.000\nDeux\n\n", 1),
        "https://live.example.com/subs/s2.vtt": segment("00:00:13.000", "Trois"),
    }
    session = FakeSession(pages)
    feed = LiveSubtitleFeed(TRACK, hls=HlsClient(session))
    assert [c.text for c in feed.poll()] == ["Un", "Deux"]
    pages[URI] = playlist(1, ["s1.vtt", "s2.vtt"])
    assert [c.text for c in feed.poll()] == ["Trois"]
    assert feed.poll() == []


def test_timeline_active_and_pruning():
    timeline = Timeline(keep_ms=10_000)
    timeline.add([Cue(5_000, 7_000, "b"), Cue(1_000, 3_000, "a"), Cue(6_000, 9_000, "c")])
    assert [c.text for c in timeline.active(2_000)] == ["a"]
    assert [c.text for c in timeline.active(6_500)] == ["b", "c"]
    assert timeline.active(4_000) == []
    timeline.active(30_000)
    assert len(timeline) == 0


class StaticFeed:
    target_duration = 6.0

    def __init__(self, batches):
        self.batches = list(batches)

    def poll(self):
        return self.batches.pop(0) if self.batches else []


class UpperTranslator:
    namespace = "upper"

    def __init__(self, fail=False):
        self.fail, self.contexts = fail, []

    def translate_batch(self, texts, context):
        if self.fail:
            raise RuntimeError("API indisponible")
        self.contexts.append(context)
        return [t.upper() for t in texts]


def test_live_translator_keeps_context_between_polls():
    feed = StaticFeed([[Cue(0, 1, "un"), Cue(1, 2, "deux")], [Cue(2, 3, "trois")]])
    translator, timeline = UpperTranslator(), Timeline()
    worker = LiveTranslator(feed, translator, timeline)
    assert worker.step() == 2
    assert worker.step() == 1
    assert translator.contexts[1] == [("un", "UN"), ("deux", "DEUX")]
    assert [c.text for c in timeline.active(2)] == ["TROIS"]


def test_live_translator_falls_back_to_original_on_error():
    timeline = Timeline()
    LiveTranslator(StaticFeed([[Cue(0, 10, "bonjour")]]), UpperTranslator(fail=True), timeline).step()
    assert [c.text for c in timeline.active(5)] == ["bonjour"]


class FakePlayer:
    def __init__(self, positions):
        self.positions = list(positions)
        self.calls = []

    def is_running(self):
        return bool(self.positions)

    def time_pos(self):
        return self.positions.pop(0)

    def show_overlay(self, text):
        self.calls.append(("show", text))

    def hide_overlay(self):
        self.calls.append(("hide",))


def test_display_loop_shows_and_hides_with_offset():
    timeline = Timeline()
    timeline.add([Cue(10_000, 12_000, "Halo")])
    player = FakePlayer([None, 9.0, 10.5, 11.0, 12.5, 13.0])
    display_loop(player, timeline, offset_ms=500, interval=0)
    # Avec 0,5 s de retard, 10,5 s de lecture = 10,0 s de sous-titres.
    assert player.calls == [("show", "Halo"), ("hide",)]


def test_ass_escape():
    assert ass_escape("a{b}\nc") == "a\\{b\\}\\Nc"
    # Un antislash du texte ne doit pas former de commande ASS comme \\N.
    assert ass_escape("C:\\Nope") == "C:\\\u2060Nope"


@pytest.mark.skipif(sys.platform == "win32", reason="socket Unix")
def test_mpv_ipc_skips_events_and_matches_request_id():
    # Pas tmp_path : sur Mac son chemin dépasse la limite de 104 caractères des sockets Unix.
    path = os.path.join(tempfile.mkdtemp(prefix="subtrad-"), "mpv.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(1)
    received = []

    def fake_mpv():
        conn, _ = server.accept()
        with conn, conn.makefile("rb") as reader:
            for line in reader:
                msg = json.loads(line)
                received.append(msg)
                conn.sendall(b'{"event":"playback-restart"}\n')
                reply = {"request_id": msg["request_id"], "error": "success", "data": 42.5}
                conn.sendall(json.dumps(reply).encode() + b"\n")

    threading.Thread(target=fake_mpv, daemon=True).start()
    ipc = MpvIpc(path, timeout=2)
    assert ipc.request(["get_property", "time-pos"])["data"] == 42.5
    assert ipc.request({"name": "osd-overlay", "id": 1})["error"] == "success"
    assert [m["request_id"] for m in received] == [1, 2]
    ipc.close()
    server.close()
    os.unlink(path)
    os.rmdir(os.path.dirname(path))
