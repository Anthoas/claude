"""Traduction parallèle, annulation, démarrage rapide (mpv) et transcription Whisper."""

import shutil
import subprocess
import threading
import time

import pytest

from subtrad.cache import TranslationCache
from subtrad.errors import Cancelled
from subtrad.gui import GuiApp, Settings
from subtrad.hls import HlsClient
from subtrad.subtitles import Cue
from subtrad.transcribe import (
    SAMPLE_RATE, Segment, WhisperCppTranscriber, _cut_point, _samples, ensure_model,
    is_hallucination, iter_audio_chunks, segments_to_cues, split_for_screen, wrap_lines,
)
from subtrad.translate import TranslationPipeline

from test_gui import PAGES, PLAYLIST, FakePlayer
from test_hls import FakeSession

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg requis")


# --- Traduction parallèle ---------------------------------------------------------------------


class SlowTranslator:
    namespace = "slow"

    def __init__(self, delay=0.2, fail_on=None):
        self.delay, self.fail_on = delay, fail_on
        self.active = self.max_active = 0
        self.lock = threading.Lock()
        self.contexts = []

    def translate_batch(self, texts, context):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.contexts.append((list(texts), list(context)))
        time.sleep(self.delay)
        with self.lock:
            self.active -= 1
        if self.fail_on and self.fail_on in texts:
            raise RuntimeError("API indisponible")
        return [f"ID {t}" for t in texts]

    def usage_summary(self):
        return "coût estimé : 0 $"


def cues(n, start=0):
    return [Cue(i * 1000, i * 1000 + 900, f"Réplique {i}") for i in range(start, start + n)]


def test_pipeline_translates_batches_in_parallel_and_in_order():
    translator = SlowTranslator(delay=0.2)
    seen = []
    pipeline = TranslationPipeline(translator, batch_size=5, workers=4, first_batch_size=2,
                                   on_batch=seen.append)
    started = time.monotonic()
    pipeline.add(cues(22))
    result = pipeline.finish()
    elapsed = time.monotonic() - started
    assert [c.text for c in result] == [f"ID Réplique {i}" for i in range(22)]
    assert translator.max_active > 1 and elapsed < 0.2 * 6  # 6 lots, pas l'un après l'autre
    assert len(translator.contexts[0][0]) == 2  # premier lot plus petit
    # Le contexte d'un lot : les répliques d'origine qui le précèdent (traduction inconnue).
    batch, context = next(c for c in translator.contexts if c[0][0] == "Réplique 2")
    assert context == [("Réplique 0", None), ("Réplique 1", None)]
    assert pipeline.found == pipeline.translated == 22 and sum(len(b) for b in seen) == 22


def test_pipeline_error_propagates_or_keeps_original():
    pipeline = TranslationPipeline(SlowTranslator(0, fail_on="Réplique 3"), batch_size=2)
    pipeline.add(cues(6))
    with pytest.raises(RuntimeError):
        pipeline.finish()
    tolerant = TranslationPipeline(SlowTranslator(0, fail_on="Réplique 3"), batch_size=2,
                                   keep_original_on_error=True)
    tolerant.add(cues(6))
    texts = [c.text for c in tolerant.finish()]
    assert texts[2:4] == ["Réplique 2", "Réplique 3"] and texts[0] == "ID Réplique 0"


def test_pipeline_cancel_stops_pending_batches():
    cancel = threading.Event()
    translator = SlowTranslator(delay=0.2)
    pipeline = TranslationPipeline(translator, batch_size=1, workers=1, cancel=cancel)
    pipeline.add(cues(10))
    time.sleep(0.1)
    cancel.set()
    with pytest.raises(Cancelled):
        pipeline.finish()
    assert len(translator.contexts) < 10


# --- Interface : annulation, lecteurs ------------------------------------------------------------


class BlockingPlayer(FakePlayer):
    """Lecteur qui « joue » jusqu'à ce qu'on l'arrête."""

    def wait(self):
        self.stopped.wait(10)
        return 0


class FakeMpv(FakePlayer):
    """mpv simulé : la lecture avance de 0,5 s à chaque appel de time_pos."""

    instances = []

    def __init__(self, name="mpv"):
        super().__init__(name)
        self.pos = 0.0
        self.overlays = []
        self.kwargs = {}
        FakeMpv.instances.append(self)

    def start(self, url, subtitle=None, title=None, **kwargs):
        self.kwargs = kwargs
        return self

    def is_running(self):
        return self.pos < 12 and not self.stopped.is_set()

    def time_pos(self):
        self.pos += 0.5
        return self.pos

    def show_overlay(self, text):
        self.overlays.append(text)

    def hide_overlay(self):
        self.overlays.append(None)


def make_app(tmp_path, translator=None, player=FakePlayer, **settings):
    app = GuiApp(
        Settings(tmp_path / "config"), tmp_path / "playlist.m3u",
        translator_factory=lambda s: translator or SlowTranslator(0),
        player_factory=player,
        cache_factory=lambda: TranslationCache(":memory:"),
        hls=HlsClient(FakeSession(PAGES)),
        whisper_backend=lambda: None,
    )
    if settings:
        app.settings.update(**settings)
    app.load_playlist(text=PLAYLIST)
    return app


def wait_state(app, job_id, states, timeout=10):
    deadline = time.monotonic() + timeout
    while app.jobs[job_id].state not in states and time.monotonic() < deadline:
        time.sleep(0.05)
    return app.jobs[job_id]


def movie_id(app):
    return app.library.search("diner")["items"][0]["id"]


def test_cancel_during_translation(tmp_path):
    translator = SlowTranslator(delay=0.5)
    app = make_app(tmp_path, translator, player=BlockingPlayer)
    job = app.watch(movie_id(app))
    time.sleep(0.2)
    app.cancel(job.id)
    job = wait_state(app, job.id, {"cancelled", "done", "error"})
    assert job.state == "cancelled" and job.step == "Annulé."
    assert job.player == ""  # VLC n'a pas été ouvert


def test_cancel_during_vlc_playback_closes_the_player(tmp_path):
    players = []

    def factory(name):
        players.append(BlockingPlayer(name))
        return players[-1]

    app = make_app(tmp_path, player=factory)
    job = app.watch(movie_id(app))
    job = wait_state(app, job.id, {"playing"})
    assert job.player == "VLC"
    app.cancel(job.id)
    job = wait_state(app, job.id, {"cancelled"})
    assert job.state == "cancelled" and players[0].stopped.is_set()


def test_quick_start_with_mpv_draws_translated_cues(tmp_path):
    FakeMpv.instances.clear()
    app = make_app(tmp_path, player=FakeMpv, lecteur="mpv")
    job = app.watch(movie_id(app))
    job = wait_state(app, job.id, {"done", "error"})
    assert job.state == "done", job.error
    mpv = FakeMpv.instances[-1]
    assert mpv.kwargs.get("hide_original_subs") is True  # pas les sous-titres d'origine en plus
    assert "ID Bonjour." in mpv.overlays and job.player == "mpv"


def test_invalid_player_setting_is_refused(tmp_path):
    settings = Settings(tmp_path)
    with pytest.raises(ValueError):
        settings.update(lecteur="quicktime")


# --- Whisper ----------------------------------------------------------------------------------


def test_cut_point_lands_in_the_silence():
    import math
    from array import array

    sound = array("h", (int(math.sin(i * 0.05) * 20000) for i in range(SAMPLE_RATE * 30)))
    for i in range(SAMPLE_RATE * 25, SAMPLE_RATE * 26):  # une seconde de silence à 25 s
        sound[i] = 0
    cut = _cut_point(_samples(sound.tobytes()), SAMPLE_RATE * 8)
    assert SAMPLE_RATE * 25 <= cut <= SAMPLE_RATE * 26


def test_segments_become_readable_cues():
    segments = [
        Segment(1.0, 3.0, " Bonjour à tous. "),
        Segment(4.0, 5.0, "Sous-titres réalisés par la communauté d'Amara.org"),
        Segment(6.0, 7.0, "♪ ♪"),
        Segment(8.0, 9.0, "euh", no_speech_prob=0.9, avg_logprob=-1.5),
        Segment(10.0, 20.0, "Une très longue phrase qui ne tiendrait jamais sur deux lignes "
                            "de sous-titres à l'écran sans être coupée en morceaux lisibles."),
    ]
    out = segments_to_cues(segments, offset_s=60.0, chunk_s=30.0)
    assert out[0] == Cue(61000, 63000, "Bonjour à tous.")
    assert all("Amara" not in c.text for c in out) and len(out) >= 3
    long_parts = out[1:]
    assert long_parts[0].start_ms == 70000 and long_parts[-1].end_ms == 80000
    assert all(len(c.text.replace("\n", " ")) <= 84 and c.text.count("\n") <= 1 for c in long_parts)


def test_wrap_and_split_helpers():
    assert wrap_lines("Court.") == "Court."
    assert wrap_lines("Une phrase un peu trop longue pour une seule ligne") == \
        "Une phrase un peu trop\nlongue pour une seule ligne"
    assert split_for_screen(0, 1000, "Bonjour") == [Cue(0, 1000, "Bonjour")]
    assert is_hallucination("Merci d'avoir regardé cette vidéo !")
    assert is_hallucination("[BLANK_AUDIO]") and is_hallucination("(musique)")
    assert not is_hallucination("Merci beaucoup.")


@needs_ffmpeg
def test_audio_is_read_in_chunks_cut_on_silence(tmp_path):
    wav = tmp_path / "voix.wav"
    # 70 s : bip continu, sauf une seconde de silence toutes les 10 s.
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=70,volume='if(lt(mod(t,10),9),1,0)':eval=frame",
                    "-ar", "16000", str(wav)], check=True)
    chunks = list(iter_audio_chunks(str(wav)))
    offsets = [round(o, 1) for o, _ in chunks]
    assert len(chunks) == 3 and offsets[0] == 0
    total = sum(len(a) for _, a in chunks) / 2 / SAMPLE_RATE
    assert abs(total - 70) < 0.1
    for offset in offsets[1:]:  # coupé pendant un silence (entre 9 et 10 s modulo 10)
        assert 9 <= offset % 10 <= 10


@needs_ffmpeg
def test_whisper_fallback_when_there_are_no_subtitles(tmp_path):
    film = tmp_path / "sans-sous-titres.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=5:d=40",
                    "-f", "lavfi", "-i", "sine=frequency=300:duration=40", "-c:v", "libx264",
                    "-c:a", "aac", "-shortest", str(film)], check=True)

    class FakeWhisper:
        name = "fake"

        def transcribe(self, audio, language):
            return [Segment(1.0, 2.5, f"Il dit quelque chose ({language}).")]

    app = make_app(tmp_path)
    app.whisper_backend = lambda: "fake"
    app._transcriber_factory = FakeWhisper
    app.load_playlist(text=f"#EXTM3U\n#EXTINF:-1 group-title=\"Films\",Film muet\n{film}\n")
    assert app.check(0)["mode"] == "whisper"
    FakePlayer.started.clear()
    job = app.watch(0)
    job = wait_state(app, job.id, {"done", "error"})
    assert job.state == "done", job.error
    srt = FakePlayer.started[-1][1]
    assert srt.count("ID Il dit quelque chose (fr).") == 2  # un par morceau de ~30 s


FAKE_WHISPER_CLI = """#!/usr/bin/env python3
import json, sys, wave
args = sys.argv[1:]
opt = lambda name: args[args.index(name) + 1]
with wave.open(opt("-f")) as w:
    assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 16000)
    seconds = w.getnframes() / 16000
assert "-oj" in args and open(opt("-m")).read() == "modèle"
result = {"transcription": [
    {"offsets": {"from": 500, "to": 2000}, "text": " Bonjour (" + opt("-l") + ")"},
    {"offsets": {"from": 2000, "to": 3000}, "text": " [BLANK_AUDIO]"},
    {"offsets": {"from": 3000, "to": int(seconds * 1000)}, "text": " Fin du morceau."},
]}
open(opt("-of") + ".json", "w").write(json.dumps(result))
"""


def test_whisper_cpp_is_called_and_its_json_read(tmp_path, monkeypatch):
    binary = tmp_path / "whisper-cli"
    binary.write_text(FAKE_WHISPER_CLI)
    binary.chmod(0o755)
    model = tmp_path / "modele.bin"
    model.write_text("modèle")
    transcriber = WhisperCppTranscriber(binary=str(binary))
    transcriber.model_path = model
    audio = b"\x00\x00" * SAMPLE_RATE * 4  # 4 s de silence
    segments = transcriber.transcribe(audio, "fr")
    assert segments[0] == Segment(0.5, 2.0, " Bonjour (fr)") and segments[2].end == 4.0
    cues = segments_to_cues(segments, offset_s=30.0, chunk_s=4.0)
    assert [c.text for c in cues] == ["Bonjour (fr)", "Fin du morceau."]  # [BLANK_AUDIO] retiré
    assert cues[0].start_ms == 30500


def test_model_is_downloaded_once_with_progress(tmp_path, monkeypatch):
    import http.server

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    payload = b"x" * 3_000_000
    hits = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/modele.bin"
    statuses = []
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")  # pas de proxy pour le serveur local
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    path = ensure_model("modele.bin", lambda m, f: statuses.append((m, f)), url=url)
    again = ensure_model("modele.bin", url=url)
    server.shutdown()
    assert path == again and path.read_bytes() == payload and len(hits) == 1
    assert statuses[-1][1] == 1.0 and "3 Mo" in statuses[-1][0]
    assert not path.with_name("modele.bin.part").exists()
