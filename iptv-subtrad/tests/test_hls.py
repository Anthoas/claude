import pytest

from subtrad.hls import (
    HlsClient,
    LiveStreamNotSupported,
    choose_track,
    parse_attributes,
    parse_subtitle_tracks,
)
from subtrad.pipeline import fetch_source_subtitles
from subtrad.subtitles import Cue

BASE = "https://cdn.example.com/film/"

MASTER = """#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",LANGUAGE="fr",NAME="Français",URI="audio/fr.m3u8"
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",LANGUAGE="fr",NAME="Français (forcés)",FORCED=YES,URI="subs/fr-forced.m3u8"
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",LANGUAGE="fra",NAME="Français SME",CHARACTERISTICS="public.accessibility.transcribes-spoken-dialog,public.accessibility.describes-music-and-sound",URI="subs/fr-sme.m3u8"
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",LANGUAGE="fr",NAME="Français",DEFAULT=YES,URI="subs/fr.m3u8"
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",LANGUAGE="en",NAME="English",URI="subs/en.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=2000000,AUDIO="aud",SUBTITLES="subs"
video/720p.m3u8
"""

SUB_PLAYLIST = """#EXTM3U
#EXT-X-TARGETDURATION:6
#EXT-X-MEDIA-SEQUENCE:0
#EXTINF:6.0,
seg0.vtt
#EXTINF:6.0,
seg1.vtt
#EXT-X-ENDLIST
"""

SEG0 = """WEBVTT
X-TIMESTAMP-MAP=MPEGTS:900000,LOCAL:00:00:00.000

00:00:01.000 --> 00:00:03.000
Bonjour.

00:00:05.000 --> 00:00:07.000
Ça chevauche
deux segments.
"""

SEG1 = """WEBVTT
X-TIMESTAMP-MAP=MPEGTS:900000,LOCAL:00:00:00.000

00:00:05.000 --> 00:00:07.000
Ça chevauche
deux segments.

00:00:08.000 --> 00:00:09.500
<i>Au revoir.</i>
"""


class FakeResponse:
    def __init__(self, text):
        self.text, self.encoding = text, None

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self, pages):
        self.pages = pages

    def get(self, url, timeout=None):
        return FakeResponse(self.pages[url])


def test_parse_attributes_with_quoted_commas():
    attrs = parse_attributes('TYPE=SUBTITLES,NAME="a, b",CHARACTERISTICS="x,y",DEFAULT=YES')
    assert attrs == {"TYPE": "SUBTITLES", "NAME": "a, b", "CHARACTERISTICS": "x,y", "DEFAULT": "YES"}


def test_subtitle_tracks_and_choice():
    tracks = parse_subtitle_tracks(MASTER, BASE + "master.m3u8")
    assert len(tracks) == 4  # la piste audio est ignorée
    assert tracks[0].uri == BASE + "subs/fr-forced.m3u8"
    assert choose_track(tracks, "fr").name == "Français"
    assert choose_track(tracks, "fr", prefer_sdh=True).name == "Français SME"
    assert choose_track(tracks, "en").name == "English"
    assert choose_track(tracks, "de") is None


def test_download_track_merges_segments():
    client = HlsClient(FakeSession({
        BASE + "master.m3u8": MASTER,
        BASE + "subs/fr.m3u8": SUB_PLAYLIST,
        BASE + "subs/seg0.vtt": SEG0,
        BASE + "subs/seg1.vtt": SEG1,
    }))
    source = fetch_source_subtitles(BASE + "master.m3u8", "fr", hls=client)
    assert source.cues == [
        Cue(1000, 3000, "Bonjour."),
        Cue(5000, 7000, "Ça chevauche\ndeux segments."),
        Cue(8000, 9500, "Au revoir."),
    ]


def test_live_playlist_is_rejected_for_now():
    live = SUB_PLAYLIST.replace("#EXT-X-ENDLIST\n", "")
    client = HlsClient(FakeSession({BASE + "subs/fr.m3u8": live}))
    track = parse_subtitle_tracks(MASTER, BASE + "master.m3u8")[2]
    with pytest.raises(LiveStreamNotSupported):
        client.download_track(track)
