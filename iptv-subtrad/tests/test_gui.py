import json
import os
import stat
import threading
import time

import pytest
import requests

from subtrad.cache import TranslationCache
from subtrad.gui import GuiApp, Library, Settings, make_server, normalize
from subtrad.hls import HlsClient
from subtrad.pipeline import check_subtitles

from test_hls import BASE, MASTER, SEG0, SEG1, SUB_PLAYLIST, FakeSession

PLAYLIST = f"""#EXTM3U
#EXTINF:-1 tvg-logo="http://logo/tf.png" group-title="Généralistes",Télé Matin
http://iptv.example/live/u/p/101.ts
#EXTINF:-1 group-title="Films FR",Le Dîner de cons
{BASE}master.m3u8
#EXTINF:-1 group-title="Films FR",Les Visiteurs
http://iptv.example/movie/u/p/202.mkv
#EXTINF:-1 group-title="Séries",Kaamelott S01E01
http://iptv.example/series/u/p/303.mkv
"""
# L'entrée « Le Dîner de cons » pointe vers le faux flux HLS (sous-titres fr) de test_hls.
PLAYLIST = PLAYLIST.replace(f"{BASE}master.m3u8", f"{BASE}movie/master.m3u8")
PAGES = {
    f"{BASE}movie/master.m3u8": MASTER,
    f"{BASE}movie/subs/fr.m3u8": SUB_PLAYLIST,
    f"{BASE}movie/subs/seg0.vtt": SEG0,
    f"{BASE}movie/subs/seg1.vtt": SEG1,
}


def test_normalize_ignores_accents_and_case():
    assert normalize("Télé MATIN") == normalize("tele matin") == "tele matin"


def test_library_search_kinds_and_groups():
    lib = Library()
    assert lib.load_text(PLAYLIST) == 4
    assert lib.kinds() == {"direct": 1, "film": 2, "serie": 1}
    assert [i["name"] for i in lib.search("tele")["items"]] == ["Télé Matin"]
    assert [i["name"] for i in lib.search("diner cons")["items"]] == ["Le Dîner de cons"]
    assert lib.search("", kind="film")["total"] == 2
    assert lib.search("", group="Séries")["items"][0]["kind_label"] == "Série"
    assert [g["name"] for g in lib.groups("film")] == ["Films FR"]
    page = lib.search("", offset=1, limit=2)
    assert page["total"] == 4 and len(page["items"]) == 2
    # Le lien du flux (qui contient souvent identifiant et mot de passe) n'est pas exposé.
    assert "url" not in page["items"][0]


def test_settings_file_is_private(tmp_path):
    settings = Settings(tmp_path)
    settings.update(api_key="sk-ant-secret", model="claude-sonnet-5-5", ignored="x")
    mode = stat.S_IMODE(os.stat(tmp_path / "config.json").st_mode)
    assert mode == 0o600
    reloaded = Settings(tmp_path)
    assert reloaded["model"] == "claude-sonnet-5-5" and "ignored" not in reloaded.data
    assert "sk-ant" not in json.dumps(reloaded.public())
    assert reloaded.public()["has_api_key"] is True


class FakeTranslator:
    namespace = "fake"

    def translate_batch(self, texts, context):
        return [f"ID {t}" for t in texts]

    def usage_summary(self):
        return "coût estimé : 0,001 $"


class FakePlayer:
    started = []

    def start(self, url, subtitle=None, title=None, **kwargs):
        FakePlayer.started.append((url, subtitle and open(subtitle, encoding="utf-8").read(), title))
        return self

    def wait(self):
        return 0


@pytest.fixture
def server(tmp_path):
    app = GuiApp(
        Settings(tmp_path / "config"), tmp_path / "cache" / "playlist.m3u",
        translator_factory=lambda settings: FakeTranslator(),
        player_factory=FakePlayer,
        cache_factory=lambda: TranslationCache(":memory:"),
        hls=HlsClient(FakeSession(PAGES)),
    )
    srv, token = make_server(app, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    session = requests.Session()
    session.trust_env = False  # pas de proxy pour 127.0.0.1
    session.headers["X-Subtrad-Token"] = token
    yield base, session, app, tmp_path
    srv.shutdown()
    srv.server_close()


def test_page_is_served_with_token_and_api_requires_it(server):
    base, session, _, _ = server
    page = session.get(base + "/").text
    assert session.headers["X-Subtrad-Token"] in page and "__TOKEN__" not in page
    anonymous = requests.Session()
    anonymous.trust_env = False
    assert anonymous.get(base + "/api/state").status_code == 403
    # Un autre nom d'hôte (attaque par « DNS rebinding ») est refusé, même avec le jeton.
    forged = session.get(base + "/api/state", headers={"Host": "evil.example"})
    assert forged.status_code == 403


def test_full_flow_load_search_check_watch(server):
    base, session, app, tmp_path = server
    assert session.get(base + "/api/state").json()["count"] == 0
    bad = session.post(base + "/api/playlist", json={"text": "pas une playlist"})
    assert bad.status_code == 400 and "M3U" in bad.json()["error"]

    assert session.post(base + "/api/playlist", json={"text": PLAYLIST}).json() == {"count": 4}
    cached = tmp_path / "cache" / "playlist.m3u"
    assert cached.exists() and stat.S_IMODE(cached.stat().st_mode) == 0o600

    found = session.get(base + "/api/search", params={"q": "dîner"}).json()
    assert found["total"] == 1
    movie_id = found["items"][0]["id"]

    check = session.post(base + "/api/check", json={"id": movie_id}).json()
    assert check["ok"] is True and "fr" in check["message"]

    job = session.post(base + "/api/watch", json={"id": movie_id}).json()
    for _ in range(50):
        jobs = session.get(base + "/api/jobs").json()
        if jobs[0]["state"] in ("done", "error"):
            break
        time.sleep(0.05)
    assert jobs[0]["id"] == job["id"]
    assert jobs[0]["state"] == "done", jobs[0]
    assert (jobs[0]["done"], jobs[0]["total"]) == (3, 3)
    url, srt, title = FakePlayer.started[-1]
    assert url == f"{BASE}movie/master.m3u8" and title == "Le Dîner de cons"
    assert "ID Bonjour." in srt


def test_watch_error_is_reported(server):
    base, session, _, _ = server
    session.post(base + "/api/playlist", json={"text": PLAYLIST})
    # « Télé Matin » est un .ts inconnu du faux réseau : l'erreur doit remonter dans la page.
    tele = session.get(base + "/api/search", params={"q": "matin"}).json()["items"][0]["id"]
    session.post(base + "/api/watch", json={"id": tele})
    for _ in range(50):
        job = session.get(base + "/api/jobs").json()[0]
        if job["state"] == "error":
            break
        time.sleep(0.05)
    assert job["state"] == "error" and job["error"]


def test_settings_endpoint_keeps_key_when_left_empty(server):
    base, session, app, _ = server
    session.post(base + "/api/settings", json={"api_key": "sk-ant-1", "model": "claude-haiku-5-5"})
    public = session.post(base + "/api/settings", json={"api_key": "", "vers": "en"}).json()
    assert app.settings["api_key"] == "sk-ant-1" and public["vers"] == "en"
    assert "sk-ant-1" not in json.dumps(public)


def test_check_reports_missing_language(monkeypatch):
    hls = HlsClient(FakeSession(PAGES))
    result = check_subtitles(f"{BASE}movie/master.m3u8", "de", hls)
    assert result.ok is False and "fr" in result.message and "en" in result.message
