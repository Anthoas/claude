import json
import os
import stat
import threading

import pytest
import requests

from subtrad.cache import TranslationCache
from subtrad.gui import GuiApp, Settings
from subtrad.playlist import parse_m3u
from subtrad.store import VideoStore
from subtrad.subtitles import Cue
from subtrad.tele import TvAccess
from subtrad.xtream import Catalog, XtreamAccount, clean_name, duration_text, language_of, year_of

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
    "get_vod_categories": [{"category_id": "20", "category_name": "FR| COMÉDIE", "parent_id": 0}],
    "get_vod_streams": [
        {"stream_id": 501, "name": "|FR| Le Dîner de cons (1998)", "category_id": "20",
         "stream_icon": "https://image.tmdb.org/t/p/w600/diner.jpg", "rating": 7.4,
         "container_extension": "mkv"},
        {"stream_id": 502, "name": "|FR| Absent de la playlist - 2022", "category_id": "20",
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
    channels = channels if channels is not None else parse_m3u(PLAYLIST)
    return Catalog(lambda: fake, lambda: channels, tmp_path / "xtream", clock=clock), fake


def test_name_helpers():
    assert language_of("|FR| Game of Thrones") == "FR" and language_of("FR| COMÉDIE") == "FR"
    assert language_of("Sans préfixe") == ""
    assert clean_name("|FR| |IT| Jerry & Marge Go Large - 2022") == "Jerry & Marge Go Large - 2022"
    assert clean_name("|FR DV⁴ᴷ| House of the Dragon (2022)") == "House of the Dragon (2022)"
    assert clean_name("FR| COMÉDIE") == "COMÉDIE" and clean_name("Les 4 | 3 fantastiques") == "Les 4 | 3 fantastiques"
    assert duration_text({"duration": "00:01:20", "duration_secs": 4808}) == "1 h 20"
    assert duration_text({"duration_secs": "3409"}) == "57 min" and duration_text({"duration": "00:56"}) == "00:56"
    assert year_of("Le Dîner de cons (1998)") == "1998" and year_of("Sans année") == ""


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
    detail = catalog.series_detail(77, is_ready=lambda vid: vid in ready)
    assert detail["plot"].startswith("Des familles") and detail["backdrop"].endswith("back.jpg")
    assert [s["season"] for s in detail["seasons"]] == [1, 2]
    s1 = detail["seasons"][0]["episodes"]
    assert [(e["episode"], e["id"], e["ready"]) for e in s1] == [(1, 0, True), (2, 1, False), (3, -1, False)]
    assert s1[0]["title"] == "Game of Thrones 2011 4K MULTI - S01E01" and s1[0]["duration"] == "01:02:00"
    assert detail["seasons"][1]["episodes"][0]["id"] == 2
    with pytest.raises(KeyError):
        catalog.series_detail(12345)


def test_movies_are_linked_to_the_playlist(tmp_path):
    catalog, _ = make_catalog(tmp_path)
    page = catalog.movies(is_ready=lambda vid: vid == 3)
    assert [(m["name"], m["id"], m["ready"], m["year"]) for m in page["items"]] == [
        ("Le Dîner de cons (1998)", 3, True, "1998"), ("Absent de la playlist - 2022", -1, False, "2022")]
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
        lambda: app.library.channels, tmp_path / "xtream")
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
    assert cats == [{"id": "20", "name": "COMÉDIE", "count": 2}]
    series = session.get(base + "/tele/api/catalog/series", params={"q": "thrones"}).json()
    assert series["items"][0]["series_id"] == 77

    store.save_translation(app.library.get(0).url, "fr", "id", app.settings["model"], [Cue(0, 1000, "Halo")])
    detail = session.get(base + "/tele/api/catalog/series/info", params={"id": 77}).json()
    first = detail["seasons"][0]["episodes"][0]
    assert first["id"] == 0 and first["ready"] is True
    # L'épisode se lit ensuite avec les adresses habituelles (numéro de la playlist).
    assert session.get(base + "/tele/api/subtitles", params={"id": first["id"]}).status_code == 200
    movie = session.get(base + "/tele/api/catalog/movie", params={"id": 501}).json()
    assert movie["id"] == 3 and movie["ready"] is False
    assert session.get(base + "/tele/api/catalog/movie", params={"id": 4040}).status_code == 404
    everything = json.dumps([series, detail, movie, cats])
    for secret in ("MONUSER", "MONMDP", "portal.example", "stream.example"):
        assert secret not in everything
    assert requests.Session().get(base + "/tele/api/catalog").status_code in (401, 403)
