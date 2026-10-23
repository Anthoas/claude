import json
import os
import stat
import threading
import time

import pytest
import requests

from subtrad.cache import TranslationCache
from subtrad.gui import GuiApp, Settings, make_server
from subtrad.hls import HlsClient
from subtrad.store import VideoStore
from subtrad.tele import Guard, TvAccess, is_home_client

from test_gui import PAGES, PLAYLIST, FakeTranslator
from test_hls import BASE, FakeSession


class NoPlayer:
    """La préparation pour la télé ne doit jamais ouvrir de lecteur sur le Mac."""

    def __init__(self, name):
        raise AssertionError(f"lecteur {name} ouvert sur le Mac")


@pytest.fixture
def tele(tmp_path):
    app = GuiApp(
        Settings(tmp_path / "config"), tmp_path / "cache" / "playlist.m3u",
        translator_factory=lambda settings: FakeTranslator(),
        player_factory=NoPlayer,
        cache_factory=lambda: TranslationCache(":memory:"),
        hls=HlsClient(FakeSession(PAGES)),
        whisper_backend=lambda: None,
        store=VideoStore(tmp_path / "videos"),
    )
    app.load_playlist(text=PLAYLIST)
    app.settings.update(tele="on")
    app.tv = TvAccess(app, port=0, host="127.0.0.1")
    app.apply_tv()
    base = f"http://{app.tv_status()['address']}"
    session = requests.Session()
    session.trust_env = False  # pas de proxy pour 127.0.0.1
    session.headers["X-Subtrad-Code"] = app.settings.tv_code()
    yield base, session, app, tmp_path
    app.tv.stop()


def anonymous():
    session = requests.Session()
    session.trust_env = False
    return session


def wait_job(base, session, job_id):
    for _ in range(100):
        job = session.get(base + "/tele/api/job", params={"id": job_id}).json()
        if job["state"] not in ("running", "playing"):
            return job
        time.sleep(0.05)
    raise AssertionError(job)


def test_code_is_six_digits_private_and_kept(tmp_path):
    settings = Settings(tmp_path)
    code = settings.tv_code()
    assert len(code) == 6 and code.isdigit()
    assert Settings(tmp_path).tv_code() == code
    assert stat.S_IMODE(os.stat(tmp_path / "config.json").st_mode) == 0o600
    assert settings.public()["tele_code"] == ""  # accès télé désactivé : code non affiché
    settings.update(tele="on")
    assert settings.public()["tele_code"] == code
    renewed = settings.new_tv_code()
    assert len(renewed) == 6 and Settings(tmp_path).tv_code() == renewed


def test_only_home_addresses_are_accepted():
    for ip in ("192.168.1.25", "10.0.0.7", "172.16.4.2", "127.0.0.1"):
        assert is_home_client(ip)
    for ip in ("8.8.8.8", "81.250.1.1", "pas une adresse"):
        assert not is_home_client(ip)


def test_requests_need_the_code(tele):
    base, session, _, _ = tele
    assert anonymous().get(base + "/tele/api/info").status_code == 401
    wrong = anonymous().get(base + "/tele/api/info", headers={"X-Subtrad-Code": "000000x"})
    assert wrong.status_code == 401 and wrong.json()["error"] == "Code incorrect."
    info = session.get(base + "/tele/api/info").json()
    assert info["count"] == 4 and info["subtitle_label"] == "Indonésien (traduit)"
    assert session.headers["X-Subtrad-Code"] not in json.dumps(info)


def test_too_many_wrong_codes_lock_the_device(tele):
    base, session, app, _ = tele
    for _ in range(10):
        anonymous().get(base + "/tele/api/info", headers={"X-Subtrad-Code": "nope"})
    locked = session.get(base + "/tele/api/info")  # même le bon code est refusé un moment
    assert locked.status_code == 429


def test_guard_unlocks_after_the_delay():
    guard = Guard(max_failures=2, lock_seconds=0.05)
    guard.failure("192.168.1.25")
    assert not guard.locked("192.168.1.25")
    guard.failure("192.168.1.25")
    assert guard.locked("192.168.1.25") and not guard.locked("192.168.1.26")
    time.sleep(0.06)
    assert not guard.locked("192.168.1.25")


def test_tv_flow_search_prepare_and_get_subtitles(tele):
    base, session, app, _ = tele
    found = session.get(base + "/tele/api/search", params={"q": "diner"}).json()
    item = found["items"][0]
    assert item["name"] == "Le Dîner de cons" and item["ready"] is False and "url" not in item
    assert session.get(base + "/tele/api/subtitles", params={"id": item["id"]}).status_code == 404
    assert session.get(base + "/tele/api/ready").json()["total"] == 0

    job = session.post(base + "/tele/api/prepare", json={"id": item["id"]}).json()
    assert job["target"] == "tele" and "channel_url" not in job
    listed = session.get(base + "/tele/api/jobs").json()
    assert [(j["id"], j["channel_id"]) for j in listed] == [(job["id"], item["id"])]
    assert "channel_url" not in listed[0]
    job = wait_job(base, session, job["id"])
    assert job["state"] == "done", job
    assert (job["found"], job["translated"], job["saved"], job["player"]) == (3, 3, True, "")

    srt = session.get(base + "/tele/api/subtitles", params={"id": item["id"]})
    assert srt.headers["Content-Type"].startswith("application/x-subrip")
    assert "ID Bonjour." in srt.content.decode("utf-8")
    video = session.get(base + "/tele/api/video", params={"id": item["id"]}).json()
    assert video["ready"] is True and video["url"] == f"{BASE}movie/master.m3u8"
    ready = session.get(base + "/tele/api/ready").json()
    assert [v["name"] for v in ready["items"]] == ["Le Dîner de cons"]

    # Deuxième demande : déjà prêt, rien n'est refait.
    again = wait_job(base, session, session.post(base + "/tele/api/prepare", json={"id": item["id"]}).json()["id"])
    assert again["state"] == "done" and "aucun coût" in again["note"]


def test_prepare_twice_reuses_the_running_job(tele):
    base, session, app, _ = tele
    release = threading.Event()

    class SlowTranslator(FakeTranslator):
        def translate_batch(self, texts, context):
            release.wait(5)
            return super().translate_batch(texts, context)

    app.make_translator = lambda settings: SlowTranslator()
    movie = session.get(base + "/tele/api/search", params={"q": "diner"}).json()["items"][0]["id"]
    first = session.post(base + "/tele/api/prepare", json={"id": movie}).json()
    second = session.post(base + "/tele/api/prepare", json={"id": movie}).json()
    assert first["id"] == second["id"]
    release.set()
    assert wait_job(base, session, first["id"])["state"] == "done"


def test_tv_errors_are_readable_and_hide_stream_urls(tele):
    base, session, _, _ = tele
    live = session.get(base + "/tele/api/search", params={"q": "matin"}).json()["items"][0]["id"]
    job = wait_job(base, session, session.post(base + "/tele/api/prepare", json={"id": live}).json()["id"])
    assert job["state"] == "error" and "iptv.example" not in job["error"]
    missing = session.get(base + "/tele/api/video", params={"id": 99})
    assert missing.status_code == 404 and "introuvable" in missing.json()["error"]
    # La télé ne voit que ses propres préparations.
    assert session.get(base + "/tele/api/job", params={"id": "inconnu"}).status_code == 404


def test_mac_page_toggles_tv_access_and_shows_the_code(tmp_path):
    app = GuiApp(Settings(tmp_path / "config"), tmp_path / "cache" / "playlist.m3u",
                 whisper_backend=lambda: None, store=VideoStore(tmp_path / "videos"))
    app.tv = TvAccess(app, port=0, host="127.0.0.1")
    srv, token = make_server(app, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    page = f"http://127.0.0.1:{srv.server_address[1]}"
    session = anonymous()
    session.headers["X-Subtrad-Token"] = token
    try:
        assert session.get(page + "/api/state").json()["tele_status"]["active"] is False
        on = session.post(page + "/api/settings", json={"tele": "on"}).json()
        assert on["tele_status"]["active"] is True and len(on["tele_code"]) == 6
        renewed = session.post(page + "/api/settings", json={"nouveau_code_tele": True}).json()
        assert renewed["tele_code"] == app.settings.tv_code()
        off = session.post(page + "/api/settings", json={"tele": "off"}).json()
        assert off["tele_status"]["active"] is False and off["tele_code"] == ""
    finally:
        app.tv.stop()
        srv.shutdown()
        srv.server_close()


def test_tv_can_delete_a_watched_video(tele):
    base, session, app, _ = tele
    movie = session.get(base + "/tele/api/search", params={"q": "diner"}).json()["items"][0]["id"]
    assert wait_job(base, session, session.post(base + "/tele/api/prepare", json={"id": movie}).json()["id"])["state"] == "done"
    assert session.get(base + "/tele/api/ready").json()["total"] == 1

    assert session.post(base + "/tele/api/forget", json={"id": movie}).json() == {"ready": False}
    assert session.get(base + "/tele/api/ready").json()["total"] == 0
    assert session.get(base + "/tele/api/subtitles", params={"id": movie}).status_code == 404
    assert session.get(base + "/tele/api/video", params={"id": movie}).json()["ready"] is False
    # Sans le code, impossible de supprimer.
    assert anonymous().post(base + "/tele/api/forget", json={"id": movie}).status_code == 401
