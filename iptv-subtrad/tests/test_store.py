"""Mémoire par vidéo : on ne refait jamais ce qui a déjà été fait."""

import time


from subtrad import pipeline as pipeline_module
from subtrad.cache import TranslationCache
from subtrad.gui import GuiApp, Settings, job_public
from subtrad.hls import HlsClient
from subtrad.store import VideoStore
from subtrad.subtitles import Cue

from test_features import BlockingPlayer, FakeMpv, SlowTranslator, wait_state
from test_gui import BASE, PAGES, PLAYLIST, FakePlayer
from test_hls import FakeSession

CUES = [Cue(1000, 2500, "Bonjour à tous."), Cue(4000, 6000, "Deux lignes\nsur l'écran.")]
URL = "http://iptv.example/series/MONUSER/MONMDP/730640.mkv"


def test_source_and_translation_roundtrip(tmp_path):
    store = VideoStore(tmp_path)
    assert store.load_source(URL, "fr") is None
    store.save_source(URL, "fr", CUES, "sous-titres intégrés (subrip)")
    assert store.load_source(URL, "fr") == (CUES, "sous-titres intégrés (subrip)")
    assert store.load_source(URL, "en") is None  # autre langue : autre entrée

    assert store.translation_file(URL, "fr", "id", "claude-haiku-5-5") is None
    translated = [Cue(c.start_ms, c.end_ms, f"ID {c.text}") for c in CUES]
    path = store.save_translation(URL, "fr", "id", "claude-haiku-5-5", translated)
    assert store.translation_file(URL, "fr", "id", "claude-haiku-5-5") == path
    assert "ID Bonjour à tous." in path.read_text(encoding="utf-8")
    assert store.translation_file(URL, "fr", "id", "claude-sonnet-5-5") is None  # autre modèle
    assert store.translation_file(URL, "fr", "en", "claude-haiku-5-5") is None  # autre langue

    store.forget(URL, "fr", "id", "claude-haiku-5-5")
    assert store.load_source(URL, "fr") is None
    assert store.translation_file(URL, "fr", "id", "claude-haiku-5-5") is None


def test_urls_and_credentials_never_reach_the_disk(tmp_path):
    store = VideoStore(tmp_path)
    store.save_source(URL, "fr", CUES, "origine")
    store.save_translation(URL, "fr", "id", "m", CUES)
    for file in tmp_path.rglob("*"):
        assert "MONMDP" not in str(file) and "MONUSER" not in str(file)
        if file.is_file():
            assert "MONMDP" not in file.read_text(encoding="utf-8")


def test_damaged_files_are_ignored_not_fatal(tmp_path):
    store = VideoStore(tmp_path)
    store.save_source(URL, "fr", CUES, "origine")
    store._source_path(URL, "fr").write_text("{pas du json", encoding="utf-8")
    assert store.load_source(URL, "fr") is None
    path = store.translation_path(URL, "fr", "id", "m")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    assert store.translation_file(URL, "fr", "id", "m") is None


def make_app(tmp_path, translator=None, player=FakePlayer, **settings):
    app = GuiApp(
        Settings(tmp_path / "config"), tmp_path / "playlist.m3u",
        translator_factory=lambda s: translator or SlowTranslator(0),
        player_factory=player, cache_factory=lambda: TranslationCache(":memory:"),
        hls=HlsClient(FakeSession(PAGES)), whisper_backend=lambda: None,
        store=VideoStore(tmp_path / "videos"),
    )
    app.settings.update(**settings)
    app.load_playlist(text=PLAYLIST)
    return app


def movie(app):
    return app.library.search("diner")["items"][0]["id"]


def finish(app, job_id, states=("done", "error", "cancelled")):
    return wait_state(app, job_id, set(states))


def test_second_opening_is_instant_and_free(tmp_path, monkeypatch):
    translator = SlowTranslator(0)
    app = make_app(tmp_path, translator)
    index = movie(app)
    assert app.search("diner")["items"][0]["ready"] is False

    first = finish(app, app.watch(index).id)
    assert first.state == "done" and first.saved is True
    assert app.search("diner")["items"][0]["ready"] is True
    calls_after_first = len(translator.contexts)

    # Deuxième ouverture : ni lecture des sous-titres, ni traduction.
    def boom(*a, **k):
        raise AssertionError("les sous-titres ne devraient pas être cherchés une 2e fois")

    monkeypatch.setattr("subtrad.gui.open_cue_source", boom)
    FakePlayer.started.clear()
    second = finish(app, app.watch(index).id)
    assert second.state == "done", second.error
    assert len(translator.contexts) == calls_after_first  # rien envoyé à Claude
    assert "déjà prêts" in second.note and second.player == "VLC"
    url, srt, title = FakePlayer.started[-1]
    assert url == f"{BASE}movie/master.m3u8" and "ID Bonjour." in srt


def test_saved_translation_does_not_need_an_api_key(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    index = movie(app)
    finish(app, app.watch(index).id)

    def no_key(settings):
        raise RuntimeError("Aucune clé Claude")

    app.make_translator = no_key
    job = finish(app, app.watch(index).id)
    assert job.state == "done", job.error


def test_source_is_reused_when_only_the_translation_changes(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    index = movie(app)
    finish(app, app.watch(index).id)
    app.settings.update(model="claude-sonnet-5-5")  # autre modèle : il faut retraduire…
    assert app.search("diner")["items"][0]["ready"] is False
    monkeypatch.setattr("subtrad.gui.open_cue_source", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("la lecture ne doit pas être refaite")))  # …mais pas relire le fichier
    job = finish(app, app.watch(index).id)
    assert job.state == "done", job.error
    assert "déjà récupérés" in job.note and job.translated == 3


def test_forget_starts_over(tmp_path):
    app = make_app(tmp_path)
    index = movie(app)
    finish(app, app.watch(index).id)
    assert app.forget(index) == {"ready": False}
    assert app.search("diner")["items"][0]["ready"] is False


def test_cancelled_or_incomplete_work_is_not_saved(tmp_path):
    app = make_app(tmp_path, SlowTranslator(delay=0.5), player=BlockingPlayer)
    index = movie(app)
    job = app.watch(index)
    time.sleep(0.2)
    app.cancel(job.id)
    job = finish(app, job.id)
    assert job.state == "cancelled" and job.saved is False
    assert app.search("diner")["items"][0]["ready"] is False


def test_failed_batches_are_not_saved_as_translations(tmp_path):
    FakeMpv.instances.clear()
    app = make_app(tmp_path, SlowTranslator(0, fail_on="Bonjour."), player=FakeMpv,
                   lecteur="mpv")
    job = finish(app, app.watch(movie(app)).id)
    assert job.state == "done" and job.saved is False  # un lot est resté en français


def test_mpv_playback_of_saved_translation_uses_the_subtitle_file(tmp_path):
    app = make_app(tmp_path, lecteur="vlc")
    index = movie(app)
    finish(app, app.watch(index).id)
    app.settings.update(lecteur="mpv")
    FakeMpv.instances.clear()
    app.make_player = lambda name: FakePlayer(name)
    FakePlayer.started.clear()
    job = finish(app, app.watch(index).id)
    assert job.state == "done" and job.player == "mpv"
    assert "ID Bonjour." in FakePlayer.started[-1][1]


def test_stream_url_is_never_sent_to_the_page(tmp_path):
    app = make_app(tmp_path)
    job = app.watch(movie(app))
    finish(app, job.id)
    public = job_public(app.jobs[job.id])
    assert "channel_url" not in public and "iptv" not in str(public) and "master.m3u8" not in str(public)
    assert pipeline_module  # le module est bien celui utilisé
