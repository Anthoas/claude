"""Plusieurs sources : lien M3U, fichier, ou serveur (adresse + identifiant + mot de passe)."""

import http.server
import json
import stat
import threading
from urllib.parse import parse_qs, urlparse

import pytest

from subtrad.cache import TranslationCache
from subtrad.gui import GuiApp, Library, Settings, make_server
from subtrad.hls import HlsClient
from subtrad.playlist import parse_m3u
from subtrad.sources import SLOT_SIZE, build_source, host_of, normalize_server, xtream_playlist_url
from subtrad.store import VideoStore

from test_gui import FakePlayer
from test_features import SlowTranslator

PLAYLIST_A = '#EXTM3U\n#EXTINF:-1 group-title="Films",Le Dîner de cons\nhttp://a.example/movie/u/p/1.mkv\n#EXTINF:-1 group-title="Info",Chaîne Info\nhttp://a.example/live/u/p/2.ts\n'
PLAYLIST_B = '#EXTM3U\n#EXTINF:-1 group-title="Films",Les Visiteurs\nhttp://b.example/movie/u/p/9.mkv\n'
SECRET = "MOTDEPASSE-TRES-SECRET"


def test_server_address_is_normalized():
    assert normalize_server("ma.box:8080") == "http://ma.box:8080"
    assert normalize_server(" https://ma.box/get.php?username=a&password=b ") == "https://ma.box"
    assert normalize_server("http://user:pw@ma.box:80/x") == "http://ma.box:80"
    for bad in ("", "   ", "ftp://ma.box", "http://"):
        with pytest.raises(ValueError):
            normalize_server(bad)


def test_xtream_url_encodes_credentials():
    url = xtream_playlist_url("ma.box:8080", "jean dupont", "p&ss=wo/rd+é")
    query = parse_qs(urlparse(url).query)
    assert url.startswith("http://ma.box:8080/get.php?")
    assert query == {"username": ["jean dupont"], "password": ["p&ss=wo/rd+é"],
                     "type": ["m3u_plus"], "output": ["ts"]}


def test_host_never_includes_path_or_credentials():
    assert host_of("http://ma.box:8080/get.php?username=a&password=SECRET") == "ma.box:8080"
    assert host_of("https://user:pw@ma.box/x") == "ma.box"
    source = build_source("xtream", "", 0, server="ma.box:8080", username="u", password=SECRET)
    public = json.dumps(source.public())
    assert SECRET not in public and '"u"' not in public and "get.php" not in public
    assert source.name == "ma.box:8080"  # nom par défaut : l'hôte


def test_build_source_validates_input():
    with pytest.raises(ValueError):
        build_source("m3u", "", 0, url="ftp://x")
    with pytest.raises(ValueError):
        build_source("xtream", "", 0, server="ma.box", username="", password="x")
    with pytest.raises(ValueError):
        build_source("xtream", "", 0, server="ma.box", username="x", password="  ")
    with pytest.raises(ValueError):
        build_source("inconnu", "", 0)


def test_library_ids_stay_stable_when_other_sources_change():
    lib = Library()
    lib.set_source(0, parse_m3u(PLAYLIST_A, "A"))
    lib.set_source(1, parse_m3u(PLAYLIST_B, "B"))
    visiteurs = lib.search("visiteurs")["items"][0]
    assert visiteurs["id"] == 1 * SLOT_SIZE and visiteurs["source"] == "B"
    lib.set_source(0, parse_m3u(PLAYLIST_A + PLAYLIST_B.split("\n", 1)[1], "A"))  # A grossit
    assert lib.get(visiteurs["id"]).name == "Les Visiteurs"  # le numéro de B n'a pas bougé
    lib.remove_source(0)
    assert lib.get(visiteurs["id"]).name == "Les Visiteurs"
    with pytest.raises(KeyError):
        lib.get(0)
    assert lib.search("")["total"] == 1


def test_library_filters_by_source():
    lib = Library()
    lib.set_source(0, parse_m3u(PLAYLIST_A, "A"))
    lib.set_source(1, parse_m3u(PLAYLIST_B, "B"))
    assert lib.search("")["total"] == 3
    assert lib.search("", source="B")["total"] == 1
    assert [i["name"] for i in lib.search("", kind="film", source="A")["items"]] == ["Le Dîner de cons"]
    assert [g["name"] for g in lib.groups(source="B")] == ["Films"]


class FakeXtream(http.server.BaseHTTPRequestHandler):
    """Serveur IPTV de test : n'accepte qu'un identifiant et un mot de passe."""

    hits = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        type(self).hits.append(self.path)
        ok = url.path == "/get.php" and q.get("username") == "jean" and q.get("password") == SECRET
        body = PLAYLIST_A.encode() if ok else b"Forbidden"
        self.send_response(200 if ok else 403)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def xtream_server(monkeypatch):
    handler = type("H", (FakeXtream,), {"hits": []})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    yield f"127.0.0.1:{server.server_address[1]}", handler
    server.shutdown()


def make_app(tmp_path):
    return GuiApp(
        Settings(tmp_path / "config"), tmp_path / "cache" / "playlist.m3u",
        translator_factory=lambda s: SlowTranslator(0), player_factory=FakePlayer,
        cache_factory=lambda: TranslationCache(":memory:"), hls=HlsClient(),
        whisper_backend=lambda: None, store=VideoStore(tmp_path / "videos"))


def test_add_xtream_source_with_good_and_bad_password(tmp_path, xtream_server):
    address, handler = xtream_server
    app = make_app(tmp_path)
    with pytest.raises(Exception) as err:
        app.add_source("xtream", server=address, username="jean", password="mauvais")
    assert "403" in str(err.value) or "refusé" in str(err.value)
    assert app.sources == [] and app.library.search("")["total"] == 0  # rien n'est enregistré

    added = app.add_source("xtream", server=address, username="jean", password=SECRET)
    assert added["count"] == 2 and added["kind"] == "xtream" and added["host"] == address
    assert SECRET not in json.dumps(app.public_sources())
    assert "password=" + SECRET in handler.hits[-1]  # le serveur, lui, a bien reçu le mot de passe
    assert [i["source"] for i in app.library.search("")["items"]] == [address, address]


def test_credentials_are_stored_privately_and_survive_a_restart(tmp_path, xtream_server):
    address, _ = xtream_server
    app = make_app(tmp_path)
    app.add_source("xtream", name="Maison", server=address, username="jean", password=SECRET)
    app.add_source("fichier", name="Clé USB", text=PLAYLIST_B)
    config = tmp_path / "config" / "config.json"
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    for f in (tmp_path / "cache" / "playlists").glob("*.m3u"):
        assert stat.S_IMODE(f.stat().st_mode) == 0o600

    again = make_app(tmp_path)  # redémarrage : relit le disque, sans réseau
    assert [s["name"] for s in again.public_sources()] == ["Maison", "Clé USB"]
    assert [s["active"] for s in again.public_sources()] == [True, False]  # une seule source utilisée
    assert again.library.search("")["total"] == 2
    again.activate_source(again.sources[1].id)
    assert again.library.search("")["items"][0]["name"] == "Les Visiteurs"
    assert make_app(tmp_path).public_sources()[1]["active"]  # le choix survit à un redémarrage


def test_names_stay_unique_and_remove_deletes_everything(tmp_path):
    app = make_app(tmp_path)
    app.add_source("fichier", name="Films", text=PLAYLIST_A)
    second = app.add_source("fichier", name="films", text=PLAYLIST_B)
    assert second["name"] == "films (2)"
    removed_id = app.sources[0].id
    app.remove_source(removed_id)
    assert [s["name"] for s in app.public_sources()] == ["films (2)"]
    assert not (tmp_path / "cache" / "playlists" / f"{removed_id}.m3u").exists()
    assert app.library.search("")["total"] == 1
    with pytest.raises(KeyError):
        app.remove_source("inconnue")
    # un numéro de source n'est jamais réutilisé : l'ancienne vidéo ne peut pas "ressusciter"
    new = app.add_source("fichier", name="Neuf", text=PLAYLIST_A)
    assert app.sources[-1].slot > app.sources[0].slot and new["name"] == "Neuf"


def test_refresh_one_source_does_not_break_the_others(tmp_path, xtream_server):
    address, _ = xtream_server
    app = make_app(tmp_path)
    app.add_source("xtream", name="Maison", server=address, username="jean", password=SECRET)
    app.add_source("fichier", name="USB", text=PLAYLIST_B)
    app.sources[0].password = "changé"  # le mot de passe a changé côté serveur
    result = {s["name"]: s for s in app.refresh_sources()}
    assert "403" in result["Maison"]["error"] or "refusé" in result["Maison"]["error"]
    assert SECRET not in result["Maison"]["error"] and "get.php" not in result["Maison"]["error"]
    assert result["USB"]["error"] == ""  # un fichier ne se recharge pas : ignoré sans erreur
    assert app.library.search("")["total"] == 2  # l'ancienne liste de « Maison » reste utilisable
    app.sources[0].password = SECRET
    assert app.refresh_sources(app.sources[0].id)[0]["error"] == ""


def test_old_single_playlist_is_migrated(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "playlist.m3u").write_text(PLAYLIST_A, encoding="utf-8")
    settings = Settings(tmp_path / "config")
    settings.update(playlist_source="http://ancien.example/get.php?username=u&password=p")
    app = make_app(tmp_path)
    assert [(s["name"], s["kind"], s["count"]) for s in app.public_sources()] == [("Playlist", "m3u", 2)]
    assert app.library.search("")["total"] == 2
    assert not (cache / "playlist.m3u").exists()
    assert make_app(tmp_path).library.search("")["total"] == 2  # et c'est durable
    assert Settings(tmp_path / "config")["playlist_source"] == ""


def test_api_endpoints(tmp_path, xtream_server):
    import requests

    address, _ = xtream_server
    app = make_app(tmp_path)
    srv, token = make_server(app, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    s = requests.Session()
    s.trust_env = False
    s.headers["X-Subtrad-Token"] = token
    try:
        bad = s.post(base + "/api/sources", json={"kind": "xtream", "server": address,
                                                   "username": "jean", "password": "faux"})
        assert bad.status_code == 400 and "faux" not in bad.text and address not in bad.json()["error"]
        ok = s.post(base + "/api/sources", json={"kind": "xtream", "server": address,
                                                  "username": "jean", "password": SECRET}).json()
        assert ok["count"] == 2
        state = s.get(base + "/api/state").json()
        assert state["count"] == 2 and [x["id"] for x in state["sources"]] == [ok["id"]]
        assert SECRET not in json.dumps(state) and "jean" not in json.dumps(state)
        assert s.get(base + "/api/search", params={"source": address}).json()["total"] == 2
        assert s.get(base + "/api/search", params={"source": "autre"}).json()["total"] == 0
        assert s.post(base + "/api/sources/refresh", json={}).json()[0]["error"] == ""
        assert s.post(base + "/api/sources/delete", json={"id": ok["id"]}).json() == {"removed": ok["id"]}
        assert s.get(base + "/api/state").json()["count"] == 0
    finally:
        srv.shutdown()


def test_page_scopes_its_tab_selectors():
    """Les onglets Direct/Films/Séries et ceux du type de source partagent un style : le code
    de la page ne doit jamais les confondre (un sélecteur trop large a déjà cassé la liste)."""
    from importlib import resources

    html = resources.files("subtrad").joinpath("gui.html").read_text(encoding="utf-8")
    assert 'querySelectorAll(".tabs button")' not in html
    assert 'id="kind-tabs"' in html and 'id="source-kind"' in html


def test_one_source_at_a_time(tmp_path):
    app = make_app(tmp_path)
    first = app.add_source("fichier", name="Films", text=PLAYLIST_A)
    second = app.add_source("fichier", name="USB", text=PLAYLIST_B)
    assert first["active"] and not second["active"]  # une source ajoutée n'est pas utilisée d'office
    names = lambda: [i["name"] for i in app.library.search("")["items"]]
    before = names()
    assert "Les Visiteurs" not in before
    assert [s["active"] for s in app.activate_source(second["id"])] == [False, True]
    assert names() == ["Les Visiteurs"]
    app.remove_source(second["id"])  # la source utilisée est supprimée : la suivante la remplace
    assert app.public_sources()[0]["active"] and names() == before


def test_tv_manages_sources_without_ever_seeing_the_password(tmp_path, xtream_server):
    import requests

    from subtrad.tele import TvAccess

    address, _ = xtream_server
    app = make_app(tmp_path)
    app.add_source("fichier", name="USB", text=PLAYLIST_B)
    app.settings.update(tele="on")
    app.tv = TvAccess(app, port=0, host="127.0.0.1")
    app.apply_tv()
    base = f"http://{app.tv_status()['address']}/tele/api"
    session = requests.Session()
    session.trust_env = False
    session.headers["X-Subtrad-Code"] = app.settings.tv_code()
    try:
        refused = session.post(base + "/sources/add", json={"name": "Maison", "server": address,
                                                            "username": "jean", "password": "mauvais"})
        assert refused.status_code == 400 and len(app.sources) == 1
        added = session.post(base + "/sources/add", json={"name": "Maison", "server": address,
                                                          "username": "jean", "password": SECRET}).json()
        assert added["name"] == "Maison" and not added["active"]
        listed = session.get(base + "/sources").json()
        assert [s["name"] for s in listed] == ["USB", "Maison"]
        used = session.post(base + "/sources/activate", json={"id": added["id"]}).json()
        assert [s["active"] for s in used] == [False, True]
        assert [i["name"] for i in session.get(base + "/search", params={"q": ""}).json()["items"]] != ["Les Visiteurs"]
        left = session.post(base + "/sources/delete", json={"id": added["id"]}).json()
        assert [(s["name"], s["active"]) for s in left] == [("USB", True)]
        everything = json.dumps([refused.json(), added, listed, used, left])
        assert SECRET not in everything and "jean" not in everything
    finally:
        app.tv.stop()
