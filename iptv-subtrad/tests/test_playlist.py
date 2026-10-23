from subtrad.playlist import parse_m3u

PLAYLIST = """#EXTM3U
#EXTINF:-1 tvg-id="arte.fr" tvg-logo="http://logo/arte.png" group-title="Généralistes",Arte
http://example.com/arte/index.m3u8

# commentaire
#EXTINF:-1 group-title="Info, actu",France 24
http://example.com/f24.m3u8
http://example.com/sans-nom.m3u8
"""


def test_parse_channels_and_attributes():
    channels = parse_m3u(PLAYLIST)
    assert [c.name for c in channels] == ["Arte", "France 24", "http://example.com/sans-nom.m3u8"]
    arte = channels[0]
    assert arte.url == "http://example.com/arte/index.m3u8"
    assert arte.attrs["tvg-id"] == "arte.fr"
    assert arte.logo == "http://logo/arte.png"
    assert arte.group == "Généralistes"
    # Une virgule dans un attribut entre guillemets ne coupe pas le nom.
    assert channels[1].group == "Info, actu"
    assert channels[2].attrs == {}
