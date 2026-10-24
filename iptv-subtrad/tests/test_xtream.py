import json
import os
import stat
import threading
import time

import pytest
import requests

from subtrad.cache import TranslationCache
from subtrad.gui import GuiApp, Settings, make_server
from subtrad.playlist import parse_m3u
from subtrad.store import VideoStore
from subtrad.subtitles import Cue
from subtrad.tele import TvAccess
from subtrad.xtream import (Catalog, XtreamAccount, clean_name, duration_text, episode_title, language_of,
                            next_episode, rating_text, year_of)

SOURCE = "http://portal.example:8080/get.php?username=MONUSER&password=MONMDP&type=m3u_plus"
STREAM = "http://stream.example:80"
PLAYLIST = f"""#EXTM3U
#EXTINF:-1 group-title="|FR| SÉRIES",|FR| Game of Thrones 2011 4K MULTI S01 E01
{STREAM}/series/MONUSER/MONMDP/1001.mkv
#EXTINF:-1 group-title="|FR| SÉRIES",|FR| Game of Thrones 2011 4K MULTI S01 E02
{STREAM}/series/MONUSER/MONMDP/1002.mkv
#EXTINF:-1 group-title="|FR| SÉRIES",|FR| Game of Thrones 2011 4K MULTI S02 E01
{STREAM}/series/MONUSER/MONMDP/1003.mp4
#EXTINF:-1 group-title="|FR| FILMS",|FR| Le Dîner de cons (1998)
{STREAM}/movie/MONUSER/MONMDP/501.mkv
"""

LISTS = {
    "get_series_categories": [{"category_id": "10", "category_name": "|FR| DRAME", "parent_id": 0},
                              {"category_id": "11", "category_name": "|DE| DRAMA", "parent_id": 0}],
    "get_series": [
        {"series_id": 77, "name": "|FR| Game of Thrones 2011 4K MULTI", "category_id": "10",
         "cover": "https://image.tmdb.org/t/p/w600/got.jpg", "releaseDate": "2011-04-17",
         "rating": "8", "genre": "Drame", "plot": "Des familles se disputent un trône."},
        {"series_id": 78, "name": "|DE| Game of Thrones", "category_id": "11",
         "cover": "http://portal.example:8080/images/got.jpg"},
        {"series_id": 79, "name": "|FR| Sense8 2015 FHD MULTI", "category_id": "10",
         "cover": f"{STREAM}/images/MONUSER/s8.jpg"},
    ],
    "get_vod_categories": [{"category_id": "20", "category_name": "FR| COMÉDIE", "parent_id": 0},
                           {"category_id": "21", "category_name": "SD| NOUVEAUTÉS", "parent_id": 0}],
    "get_vod_streams": [
        {"stream_id": 501, "name": "|FR| Le Dîner de cons (1998)", "category_id": "20",
         "stream_icon": "https://image.tmdb.org/t/p/w600/diner.jpg", "rating": 7.4,
         "container_extension": "mkv"},
        {"stream_id": 502, "name": "|FR| Absent de la playlist - 2022", "category_id": "21",
         "stream_icon": "", "container_extension": "mp4"},
    ],
}
SERIES_INFO = {
    "info": {"plot": "Des familles se disputent un trône.", "genre": "Drame", "cast": "Emilia Clarke",
             "backdrop_path": ["https://image.tmdb.org/t/p/w1280/back.jpg"], "releaseDate": "2011-04-17"},
    "seasons": [{"season_number": 1, "name": "Saison 1"}, {"season_number": 2, "name": "Saison 2"}],
    "episodes": {
        "2": [{"id": "1003", "episode_num": 1, "title": "|FR| Game of Thrones 2011 4K MULTI - S02E01",
               "container_extension": "mp4", "info": {"duration": "00:53:00"}}],
        "1": [{"id": "1002", "episode_num": 2, "title": "|FR| Game of Thrones 2011 4K MULTI - S01E02",
               "container_extension": "mkv", "info": {"duration": "00:56:00", "air_date": "2011-04-24"}},
              {"id": "1001", "episode_num": 1, "title": "|FR| Game of Thrones 2011 4K MULTI - S01E01",
               "container_extension": "mkv", "info": {"duration": "01:02:00",
                                                       "movie_image": "https://image.tmdb.org/e1.jpg"}},
              {"id": "9999", "episode_num": 3, "title": "|FR| Game of Thrones 2011 4K MULTI - S01E03",
               "container_extension": "mkv", "info": {}}],
    },
}
VOD_INFO = {"info": {"plot": "Chaque mercredi, un dîner…", "duration": "00:01:20", "duration_secs": 4800, "genre": "Comédie",
                     "releasedate": "1998-04-15", "cover_big": "https://image.tmdb.org/t/p/w600/diner.jpg"}}


class FakeXtream:
    def __init__(self):
        self.account = XtreamAccount.from_playlist_source(SOURCE)
        self.calls = []

    def call(self, action=None, **params):
        self.calls.append(action)
        if action == "get_series_info":
            return SERIES_INFO
        if action == "get_vod_info":
            return VOD_INFO
        return LISTS[action]


def make_catalog(tmp_path, fake=None, channels=None, clock=lambda: 1000.0):
    fake = fake or FakeXtream()
    entries = list(enumerate(channels if channels is not None else parse_m3u(PLAYLIST)))
    return Catalog(lambda: fake, lambda: entries, tmp_path / "xtream", clock=clock), fake


def test_name_helpers():
    assert language_of("|FR| Game of Thrones") == "FR" and language_of("FR| COMÉDIE") == "FR"
    assert language_of("Sans préfixe") == ""
    assert clean_name("|FR| |IT| Jerry & Marge Go Large - 2022") == "Jerry & Marge Go Large - 2022"
    assert clean_name("|FR DV⁴ᴷ| House of the Dragon (2022)") == "House of the Dragon (2022)"
    assert clean_name("FR| COMÉDIE") == "COMÉDIE" and clean_name("Les 4 | 3 fantastiques") == "Les 4 | 3 fantastiques"
    assert duration_text({"duration": "00:01:20", "duration_secs": 4808}) == "1 h 20"
    assert duration_text({"duration_secs": "3409"}) == "57 min" and duration_text({"duration": "00:56"}) == "00:56"
    assert duration_text({"duration": "00:01:20", "duration_secs": 80}, movie=True) == "1 h 20"
    assert duration_text({"duration_secs": 80}) == "1 min"  # un épisode très court reste tel quel
    assert (rating_text(7.373), rating_text("8"), rating_text("0"), rating_text(None)) == ("7.4", "8", "", "")
    assert year_of("Le Dîner de cons (1998)") == "1998" and year_of("Sans année") == ""


def test_episode_titles_and_next_episode():
    assert episode_title("|FR| Sunny (2024) - S01 E01 - Il fabrique des réfrigérateurs", {}) == \
        "Il fabrique des réfrigérateurs"
    assert episode_title("|FR| Game of Thrones 2011 4K MULTI - S06E05", {}) == ""
    assert episode_title("|FR| X - S01E02", {"name": "La Porte"}) == "La Porte"
    assert episode_title("|FR| X - S01E02", {"name": "X S01E02"}) == ""

    def ep(watched=False, progress=0.0):
        return {"watched": watched, "progress": progress}

    seasons = [{"season": 0, "episodes": [ep()]},  # épisodes spéciaux : ignorés
               {"season": 1, "episodes": [ep(True), ep(True)]},
               {"season": 2, "episodes": [ep(), ep()]}]
    assert next_episode(seasons) == {"season": 2, "episode": 0}  # suite logique : S02E01
    seasons[2]["episodes"][0] = ep(progress=0.4)
    assert next_episode(seasons) == {"season": 2, "episode": 0}  # commencé : on y revient
    assert next_episode([{"season": 1, "episodes": [ep(), ep()]}]) == {"season": 0, "episode": 0}
    assert next_episode([{"season": 1, "episodes": [ep(True)]}]) == {"season": 0, "episode": 0}  # dernier vu


def test_account_comes_from_the_playlist_link():
    account = XtreamAccount.from_playlist_source(SOURCE)
    assert (account.base, account.username, account.password) == ("http://portal.example:8080", "MONUSER", "MONMDP")
    assert XtreamAccount.from_playlist_source("http://x.example/liste.m3u") is None
    assert XtreamAccount.from_playlist_source("/Users/moi/liste.m3u") is None


def test_categories_and_series_are_french_by_default_and_searchable(tmp_path):
    catalog, _ = make_catalog(tmp_path)
    assert catalog.categories("series") == [{"id": "10", "name": "DRAME", "count": 2}]
    assert [c["id"] for c in catalog.categories("series", lang="")] == ["10", "11"]
    page = catalog.series()
    assert page["total"] == 2 and [s["name"] for s in page["items"]] == ["Game of Thrones 2011 4K MULTI",
                                                                         "Sense8 2015 FHD MULTI"]
    assert page["items"][0]["year"] == "2011"
    assert catalog.series(query="THRONES")["total"] == 1
    assert catalog.series(query="sense8", category="11")["total"] == 0


def test_series_detail_groups_seasons_and_links_episodes_to_the_playlist(tmp_path):
    catalog, _ = make_catalog(tmp_path)
    ready = {0}  # S01E01 = entrée 0 de la playlist, déjà traduite
    detail = catalog.series_detail(77, status=lambda vid: {"ready": vid in ready, "watched": vid == 0})
    assert detail["plot"].startswith("Des familles") and detail["backdrop"].endswith("back.jpg")
    assert [s["season"] for s in detail["seasons"]] == [1, 2]
    s1 = detail["seasons"][0]["episodes"]
    assert [(e["episode"], e["id"], e["ready"]) for e in s1] == [(1, 0, True), (2, 1, False), (3, -1, False)]
    assert s1[0]["title"] == "" and s1[0]["duration"] == "01:02:00"  # pas de vrai titre fourni
    assert s1[0]["watched"] is True and s1[1]["watched"] is False
    assert detail["next"] == {"season": 0, "episode": 1}  # S01E01 vu : on propose S01E02
    assert detail["seasons"][1]["episodes"][0]["id"] == 2
    with pytest.raises(KeyError):
        catalog.series_detail(12345)


def test_movies_are_linked_to_the_playlist(tmp_path):
    catalog, _ = make_catalog(tmp_path)
    page = catalog.movies(status=lambda vid: {"ready": vid == 3, "progress": 0.25})
    assert [(m["name"], m["id"], m["ready"], m["year"]) for m in page["items"]] == [
        ("Le Dîner de cons (1998)", 3, True, "1998"), ("Absent de la playlist - 2022", -1, False, "2022")]
    assert page["items"][0]["rating"] == "7.4" and page["items"][0]["progress"] == 0.25
    assert page["items"][1]["progress"] == 0.0  # absent de la playlist : aucun état
    detail = catalog.movie_detail(501)
    assert detail["id"] == 3 and detail["duration"] == "1 h 20" and detail["year"] == "1998"


def test_images_never_reveal_the_account_or_the_servers(tmp_path):
    catalog, _ = make_catalog(tmp_path)
    everything = json.dumps([catalog.series(lang=""), catalog.movies(), catalog.series_detail(77),
                             catalog.movie_detail(501), catalog.categories("series", "")])
    for secret in ("MONUSER", "MONMDP", "portal.example", "stream.example"):
        assert secret not in everything
    assert "image.tmdb.org" in everything  # les images publiques passent


def test_catalog_is_kept_on_disk_privately_and_refreshed_daily(tmp_path):
    catalog, fake = make_catalog(tmp_path)
    catalog.series()
    path = tmp_path / "xtream" / "catalog.json"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert fake.calls.count("get_series") == 1

    again, fake2 = make_catalog(tmp_path, clock=lambda: 1000.0 + 3600)
    again.series()
    assert fake2.calls == []  # relu depuis le disque, aucun appel

    later, fake3 = make_catalog(tmp_path, clock=lambda: 1000.0 + 2 * 86400)
    later.series()  # répond tout de suite avec l'ancien catalogue, recharge en arrière-plan
    for thread in threading.enumerate():
        if thread is not threading.current_thread() and thread.daemon:
            thread.join(timeout=2)
    assert "get_series" in fake3.calls


class FakeTranslator:
    namespace = "fake"

    def translate_batch(self, texts, context):
        return [f"ID {t}" for t in texts]

    def usage_summary(self):
        return ""


@pytest.fixture
def tele(tmp_path):
    store = VideoStore(tmp_path / "videos")
    app = GuiApp(Settings(tmp_path / "config"), tmp_path / "cache" / "playlist.m3u",
                 translator_factory=lambda s: FakeTranslator(),
                 cache_factory=lambda: TranslationCache(":memory:"),
                 whisper_backend=lambda: None, store=store)
    app.load_playlist(text=PLAYLIST)
    fake = FakeXtream()
    # Comme le vrai programme : le catalogue n'existe que si le lien de la playlist est Xtream.
    app.catalog = Catalog(
        lambda: fake if XtreamAccount.from_playlist_source(app.settings["playlist_source"]) else None,
        lambda: app.library.entries, tmp_path / "xtream")
    app.settings.update(tele="on")
    app.tv = TvAccess(app, port=0, host="127.0.0.1")
    app.apply_tv()
    session = requests.Session()
    session.trust_env = False
    session.headers["X-Subtrad-Code"] = app.settings.tv_code()
    yield f"http://{app.tv_status()['address']}", session, app, store
    app.tv.stop()


def test_tv_catalog_endpoints(tele):
    base, session, app, store = tele
    assert session.get(base + "/tele/api/catalog").json() == {"available": False}  # lien M3U simple
    app.settings.update(playlist_source=SOURCE)
    assert session.get(base + "/tele/api/catalog").json() == {"available": True}
    cats = session.get(base + "/tele/api/catalog/categories", params={"type": "movie"}).json()
    assert cats == [{"id": "20", "name": "COMÉDIE", "count": 1}, {"id": "21", "name": "SD| NOUVEAUTÉS", "count": 1}]
    series = session.get(base + "/tele/api/catalog/series", params={"q": "thrones"}).json()
    assert series["items"][0]["series_id"] == 77

    store.save_translation(app.library.get(0).url, "fr", "id", app.settings["model"], [Cue(0, 1000, "Halo")])
    detail = session.get(base + "/tele/api/catalog/series/info", params={"id": 77}).json()
    first = detail["seasons"][0]["episodes"][0]
    assert first["id"] == 0 and first["ready"] is True and first["watched"] is False
    assert first["title_translated"] == ""  # pas de titre, rien à traduire

    # La télé signale où en est la lecture ; « Vu » au-delà de 90 %.
    saved = session.post(base + "/tele/api/progress", json={"id": 0, "position": 600_000, "duration": 3_600_000}).json()
    assert saved["watched"] is False and saved["position"] == 600_000
    video = session.get(base + "/tele/api/video", params={"id": 0}).json()
    assert video["position"] == 600_000 and video["watched"] is False
    session.post(base + "/tele/api/progress", json={"id": 0, "position": 3_300_000, "duration": 3_600_000})
    detail = session.get(base + "/tele/api/catalog/series/info", params={"id": 77}).json()
    assert detail["seasons"][0]["episodes"][0]["watched"] is True and detail["next"] == {"season": 0, "episode": 1}
    assert session.get(base + "/tele/api/ready").json()["items"][0]["watched"] is True
    # L'épisode se lit ensuite avec les adresses habituelles (numéro de la playlist).
    assert session.get(base + "/tele/api/subtitles", params={"id": first["id"]}).status_code == 200
    movie = session.get(base + "/tele/api/catalog/movie", params={"id": 501}).json()
    assert movie["id"] == 3 and movie["ready"] is False
    assert session.get(base + "/tele/api/catalog/movie", params={"id": 4040}).status_code == 404
    everything = json.dumps([series, detail, movie, cats])
    for secret in ("MONUSER", "MONMDP", "portal.example", "stream.example"):
        assert secret not in everything
    assert requests.Session().get(base + "/tele/api/catalog").status_code in (401, 403)


def test_episode_titles_are_translated_once(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)  # la clé du Terminal ne compte pas ici
    calls = []

    class CountingTranslator(FakeTranslator):
        def translate_batch(self, texts, context):
            calls.append(list(texts))
            return super().translate_batch(texts, context)

    cache = TranslationCache(tmp_path / "t.sqlite")
    app = GuiApp(Settings(tmp_path / "config"), tmp_path / "cache" / "playlist.m3u",
                 translator_factory=lambda s: CountingTranslator(), cache_factory=lambda: cache,
                 whisper_backend=lambda: None, store=VideoStore(tmp_path / "videos"),
                 catalog=make_catalog(tmp_path)[0])
    app.catalog.title_translator = app.translate_titles
    assert app.translate_titles(["L'hiver vient"]) == {}  # pas de clé Claude : rien
    app.settings.update(api_key="sk-ant-test")
    app.catalog._info[77] = (1000.0, {**SERIES_INFO, "episodes": {"1": [
        {"id": "1001", "episode_num": 1, "title": "|FR| GoT - S01 E01 - L'hiver vient", "info": {}},
        {"id": "1002", "episode_num": 2, "title": "|FR| GoT - S01 E02 - La route royale", "info": {}}]}})
    eps = app.catalog.series_detail(77)["seasons"][0]["episodes"]
    assert [e["title_translated"] for e in eps] == ["ID L'hiver vient", "ID La route royale"]
    app.catalog.series_detail(77)
    assert calls == [["L'hiver vient", "La route royale"]]  # la 2e ouverture ne coûte rien


def test_episode_titles_are_translated_in_the_background(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    release = threading.Event()

    class SlowTranslator(FakeTranslator):
        def translate_batch(self, texts, context):
            release.wait(5)
            return super().translate_batch(texts, context)

    cache = TranslationCache(tmp_path / "t.sqlite")
    app = GuiApp(Settings(tmp_path / "config"), tmp_path / "cache" / "playlist.m3u",
                 translator_factory=lambda s: SlowTranslator(), cache_factory=lambda: cache,
                 whisper_backend=lambda: None, store=VideoStore(tmp_path / "videos"),
                 catalog=make_catalog(tmp_path)[0])
    app.catalog.title_translator = app.translate_titles_soon
    app.settings.update(api_key="sk-ant-test")
    app.catalog._info[77] = (1000.0, {**SERIES_INFO, "episodes": {"1": [
        {"id": "1001", "episode_num": 1, "title": "|FR| GoT - S01 E01 - L'hiver vient", "info": {}}]}})
    first = app.catalog.series_detail(77)  # répond tout de suite, sans attendre Claude
    assert first["titles_pending"] is True and first["seasons"][0]["episodes"][0]["title_translated"] == ""
    release.set()
    for _ in range(100):
        later = app.catalog.series_detail(77)
        if not later["titles_pending"]:
            break
        time.sleep(0.05)
    assert later["seasons"][0]["episodes"][0]["title_translated"] == "ID L'hiver vient"


def test_xtream_account_comes_from_the_sources(tmp_path):
    from subtrad.sources import build_source

    app = GuiApp(Settings(tmp_path / "config"), tmp_path / "cache" / "playlist.m3u",
                 whisper_backend=lambda: None, store=VideoStore(tmp_path / "videos"))
    assert app._xtream_client() is None
    app.sources = [build_source("fichier", "Fichier", slot=0)]
    assert app._xtream_client() is None  # un fichier n'a pas de compte
    app.sources.append(build_source("m3u", "Lien", slot=1, url=SOURCE))
    assert app._xtream_client() is None  # la source utilisée (la première) n'a pas de compte
    app.settings.update(active_source=app.sources[1].id)
    account = app._xtream_client().account
    assert (account.base, account.username, account.password) == ("http://portal.example:8080", "MONUSER", "MONMDP")
    app.sources = [build_source("xtream", "Serveur", slot=2, server="portal.example:8080",
                                username="MONUSER", password="MONMDP")]
    assert app._xtream_client().account.base == "http://portal.example:8080"


def test_catalog_uses_stable_video_numbers_of_any_source(tmp_path):
    from subtrad.gui import Library
    from subtrad.sources import SLOT_SIZE

    library = Library()
    library.set_source(0, parse_m3u("#EXTM3U\n#EXTINF:-1,Autre\nhttp://autre.example/a.ts\n"))
    library.set_source(5, parse_m3u(PLAYLIST))
    fake = FakeXtream()
    catalog = Catalog(lambda: fake, lambda: library.entries, tmp_path / "xtream")
    first = catalog.series_detail(77)["seasons"][0]["episodes"][0]
    assert first["id"] == 5 * SLOT_SIZE  # S01E01 = 1re vidéo de la source n° 5
    assert library.get(first["id"]).url.endswith("/1001.mkv")
    assert catalog.movies()["items"][0]["id"] == 5 * SLOT_SIZE + 3


def test_mac_page_has_the_catalog_prepare_and_french_playback(tmp_path):
    from test_gui import FakePlayer

    app = GuiApp(Settings(tmp_path / "config"), tmp_path / "cache" / "playlist.m3u",
                 translator_factory=lambda s: FakeTranslator(), player_factory=FakePlayer,
                 cache_factory=lambda: TranslationCache(":memory:"),
                 whisper_backend=lambda: None, store=VideoStore(tmp_path / "videos"))
    app.load_playlist(text=PLAYLIST)
    fake = FakeXtream()
    app.catalog = Catalog(lambda: fake, lambda: app.library.entries, tmp_path / "xtream")
    srv, token = make_server(app, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    page = f"http://127.0.0.1:{srv.server_address[1]}"
    session = requests.Session()
    session.trust_env = False
    session.headers["X-Subtrad-Token"] = token
    try:
        assert session.get(page + "/api/catalog").json() == {"available": True}
        detail = session.get(page + "/api/catalog/series/info", params={"id": 77}).json()
        assert detail["seasons"][0]["episodes"][0]["id"] == 0
        assert session.get(page + "/api/catalog/nimporte").status_code == 404
        assert session.get(page + "/api/ready").json()["total"] == 0
        assert session.get(page + "/api/video", params={"id": 0}).json()["ready"] is False
        # Regarder en français : la vidéo s'ouvre sans sous-titres.
        FakePlayer.started.clear()
        job = session.post(page + "/api/play_original", json={"id": 3}).json()
        for _ in range(50):
            if FakePlayer.started:
                break
            time.sleep(0.02)
        assert FakePlayer.started[-1][1] is None  # aucun fichier de sous-titres
        assert job["state"] in ("playing", "done")  # (le faux lecteur se ferme tout de suite)
        # Sans le jeton de la page : refusé.
        assert requests.Session().get(page + "/api/catalog").status_code == 403
    finally:
        srv.shutdown()
        srv.server_close()


def test_ready_episode_finds_its_series_sheet(tmp_path):
    catalog, _ = make_catalog(tmp_path)
    found = catalog.episode_of(1, "|FR| Game of Thrones 2011 4K MULTI S01 E02")
    assert (found["series_id"], found["series_name"], found["season"]) == (77, "Game of Thrones 2011 4K MULTI", 1)
    assert found["episode"]["id"] == 1 and found["episode"]["episode"] == 2
    assert found["episode"]["air_date"] == "2011-04-24" and found["season_name"] == "Saison 1"
    assert catalog.episode_of(2, "|FR| Game of Thrones 2011 4K MULTI S02 E01")["season"] == 2
    assert catalog.episode_of(3, "|FR| Le Dîner de cons (1998)") is None  # pas un épisode
    assert catalog.episode_of(1, "|FR| Série inconnue S01 E02") is None
    secrets = json.dumps(found)
    assert "MONMDP" not in secrets and "stream.example" not in secrets
