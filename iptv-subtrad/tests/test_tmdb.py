import json
import os
import stat
import threading

import requests

from subtrad.gui import GuiApp, Settings, make_server
from subtrad.store import VideoStore
from subtrad.tmdb import EpisodeGuide, TmdbClient, search_name, tmdb_size
from subtrad.xtream import Catalog

from test_xtream import FakeXtream, make_catalog

KEY = "0123456789abcdef0123456789abcdef"


class FakeResponse:
    def __init__(self, status, data):
        self.status_code, self._data = status, data

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)


class FakeTmdb:
    """Faux TMDB : Game of Thrones = 1399, recherche par nom, clé valide = KEY."""

    def __init__(self):
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        params = params or {}
        self.calls.append((url.split("/3", 1)[1], dict(params)))
        if params.get("api_key") != KEY:
            return FakeResponse(401, {"status_message": "Invalid API key"})
        path = url.split("/3", 1)[1]
        if path == "/configuration":
            return FakeResponse(200, {})
        if path == "/search/tv":
            ok = params.get("query") == "Game of Thrones"
            return FakeResponse(200, {"results": [{"id": 1399}] if ok else []})
        if path == "/tv/1399/season/1":
            return FakeResponse(200, {"episodes": [
                {"episode_number": 1, "name": "L'hiver vient", "overview": "Ned Stark…", "still_path": "/e1.jpg",
                 "air_date": "2011-04-17"},
                {"episode_number": 2, "name": "Épisode 2", "overview": "", "still_path": None},
            ]})
        return FakeResponse(404, {})


def make_guide(tmp_path, key=KEY, fake=None, clock=lambda: 1000.0):
    fake = fake or FakeTmdb()
    session = requests.Session()
    session.get = fake.get
    return EpisodeGuide(lambda: TmdbClient(key, session) if key else None, tmp_path / "tmdb", clock=clock), fake


def test_tmdb_image_sizes():
    assert tmdb_size("https://image.tmdb.org/t/p/w185/abc.jpg", "w780") == "https://image.tmdb.org/t/p/w780/abc.jpg"
    assert tmdb_size("https://image.tmdb.org/t/p/original/abc.jpg", "w300") == "https://image.tmdb.org/t/p/w300/abc.jpg"
    assert tmdb_size("https://autre.example/w185/abc.jpg", "w780") == "https://autre.example/w185/abc.jpg"
    assert tmdb_size("", "w780") == ""


def test_search_names_drop_quality_and_version_marks():
    assert search_name("Sense8 2015 FHD MULTI (H.265)") == ("Sense8", "2015")
    assert search_name("Game of Thrones 2011 4K MULTI") == ("Game of Thrones", "2011")
    assert search_name("La Cite invisible (Cidade Invisivel) 2021 FHD MULTI") == ("La Cite invisible", "2021")
    assert search_name("Game of Thrones (2011)") == ("Game of Thrones", "2011")


def test_guide_finds_series_reads_seasons_and_keeps_them_30_days(tmp_path):
    guide, fake = make_guide(tmp_path)
    assert guide.find_series("Game of Thrones 2011 4K MULTI") == 1399
    season = guide.season(1399, 1)
    assert season[1]["title"] == "L'hiver vient" and season[1]["image"].endswith("/w780/e1.jpg")
    assert season[2]["title"] == ""  # « Épisode 2 » ne dit rien
    assert fake.calls[-1][1]["language"] == "fr-FR"
    assert stat.S_IMODE(os.stat(tmp_path / "tmdb" / "tv-1399-s1.json").st_mode) == 0o600
    assert KEY not in "".join(p.read_text() for p in (tmp_path / "tmdb").iterdir())

    again, fake2 = make_guide(tmp_path, clock=lambda: 1000.0 + 86400)
    assert again.season(1399, 1)[1]["title"] == "L'hiver vient" and fake2.calls == []  # gardé
    later, fake3 = make_guide(tmp_path, clock=lambda: 1000.0 + 31 * 86400)
    later.season(1399, 1)
    assert fake3.calls  # plus de 30 jours : redemandé
    assert make_guide(tmp_path, key="")[0].season(1399, 1) == {}  # sans clé : rien


def test_catalog_completes_episodes_with_tmdb_but_keeps_provider_titles(tmp_path):
    guide, fake = make_guide(tmp_path)
    catalog, _ = make_catalog(tmp_path)
    catalog.guide = guide
    detail = catalog.series_detail(77)
    s1 = detail["seasons"][0]["episodes"]
    # Le fournisseur ne donne pas info.id ici : la série est retrouvée par son nom.
    assert any(path == "/search/tv" for path, _ in fake.calls)
    assert (s1[0]["title"], s1[0]["plot"]) == ("L'hiver vient", "Ned Stark…")
    assert s1[0]["image"] == "https://image.tmdb.org/e1.jpg"  # l'image du fournisseur reste prioritaire
    assert s1[0]["image_large"] == "https://image.tmdb.org/e1.jpg"  # pas une adresse /t/p/ : inchangée
    assert s1[1]["title"] == "" and s1[1]["air_date"] == "2011-04-24"


def test_catalog_still_works_when_tmdb_refuses_the_key(tmp_path):
    guide, _ = make_guide(tmp_path, key="mauvaise-cle")
    catalog, _ = make_catalog(tmp_path)
    catalog.guide = guide
    detail = catalog.series_detail(77)
    assert detail["seasons"][0]["episodes"][0]["title"] == ""


def test_settings_check_the_key_and_never_return_it(tmp_path, monkeypatch):
    monkeypatch.setattr(TmdbClient, "check", lambda self: self.key == KEY)
    app = GuiApp(Settings(tmp_path / "config"), tmp_path / "cache" / "playlist.m3u",
                 whisper_backend=lambda: None, store=VideoStore(tmp_path / "videos"),
                 catalog=Catalog(lambda: FakeXtream(), lambda: [], tmp_path / "xtream"))
    srv, token = make_server(app, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    page = f"http://127.0.0.1:{srv.server_address[1]}"
    session = requests.Session()
    session.trust_env = False
    session.headers["X-Subtrad-Token"] = token
    try:
        bad = session.post(page + "/api/settings", json={"tmdb_key": "mauvaise"}).json()
        assert bad["tmdb_ok"] is False and bad["has_tmdb_key"] is False
        good = session.post(page + "/api/settings", json={"tmdb_key": KEY}).json()
        assert good["tmdb_ok"] is True and good["has_tmdb_key"] is True
        kept = session.post(page + "/api/settings", json={"tmdb_key": "", "vers": "id"}).json()
        assert kept["has_tmdb_key"] is True and app.settings["tmdb_key"] == KEY
        everything = json.dumps([bad, good, kept, session.get(page + "/api/state").json()])
        assert KEY not in everything
    finally:
        srv.shutdown()
        srv.server_close()
