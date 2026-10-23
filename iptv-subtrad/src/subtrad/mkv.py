"""Lecture rapide des sous-titres d'un fichier MKV : on ne télécharge que les sous-titres.

Un MKV contient en général un index (les « Cues ») qui donne, pour chaque sous-titre, sa
position exacte dans le fichier (mkvmerge et ffmpeg l'écrivent par défaut). Avec des
requêtes HTTP « Range », on va chercher ces quelques kilo-octets au lieu de lire toute la
vidéo : quelques secondes au lieu de plusieurs minutes pour un épisode.

Si quelque chose manque (pas d'index, serveur sans « Range »...), `MkvFastPathUnavailable`
est levée et l'appelant revient à la lecture complète par ffmpeg.
"""

from __future__ import annotations

import re
import threading
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable

import requests

from .errors import Cancelled
from .hls import lang_matches
from .subtitles import Cue

# Identifiants des éléments Matroska utilisés (spécification EBML / Matroska).
EBML_HEADER = 0x1A45DFA3
SEGMENT = 0x18538067
SEEK_HEAD, SEEK, SEEK_ID, SEEK_POSITION = 0x114D9B74, 0x4DBB, 0x53AB, 0x53AC
INFO, TIMESTAMP_SCALE = 0x1549A966, 0x2AD7B1
TRACKS, TRACK_ENTRY, TRACK_NUMBER, TRACK_TYPE, CODEC_ID = 0x1654AE6B, 0xAE, 0xD7, 0x83, 0x86
LANGUAGE, LANGUAGE_BCP47, NAME = 0x22B59C, 0x22B59D, 0x536E
FLAG_DEFAULT, FLAG_FORCED = 0x88, 0x55AA
CONTENT_ENCODINGS, CONTENT_ENCODING, CONTENT_COMPRESSION = 0x6D80, 0x6240, 0x5034
COMPRESSION_ALGO, COMPRESSION_SETTINGS = 0x4254, 0x4255
CUES, CUE_POINT, CUE_TIME, CUE_TRACK_POSITIONS = 0x1C53BB6B, 0xBB, 0xB3, 0xB7
CUE_TRACK, CUE_CLUSTER_POSITION, CUE_RELATIVE_POSITION, CUE_DURATION = 0xF7, 0xF1, 0xF0, 0xB2
CLUSTER, BLOCK_GROUP, BLOCK, BLOCK_DURATION, SIMPLE_BLOCK = 0x1F43B675, 0xA0, 0xA1, 0x9B, 0xA3

SUBTITLE_TRACK = 0x11
TEXT_CODECS = {"S_TEXT/UTF8", "S_TEXT/ASCII", "S_TEXT/ASS", "S_TEXT/SSA", "S_TEXT/WEBVTT"}

HEAD_BYTES = 64 * 1024
MAX_INDEX_BYTES = 32 * 1024 * 1024
BLOCK_READ = 4096


class MkvFastPathUnavailable(Exception):
    """La lecture rapide est impossible pour ce fichier : utiliser la lecture complète."""


# --- Lecture par plages d'octets ---------------------------------------------------------


class RangeReader:
    """Lit des morceaux d'un fichier local ou distant (requêtes HTTP « Range »)."""

    def __init__(self, source: str, timeout: float = 30.0):
        self.source = source
        self.timeout = timeout
        self.is_http = source.startswith(("http://", "https://"))
        self._local = threading.local()

    def _session(self) -> requests.Session:
        if not hasattr(self._local, "session"):  # une session (connexion) par thread
            self._local.session = requests.Session()
        return self._local.session

    def read(self, offset: int, length: int) -> bytes:
        if not self.is_http:
            with open(self.source, "rb") as f:
                f.seek(offset)
                return f.read(length)
        headers = {"Range": f"bytes={offset}-{offset + length - 1}"}
        with self._session().get(self.source, headers=headers, timeout=self.timeout,
                                 stream=True) as resp:
            resp.raise_for_status()
            if resp.status_code != 206:
                # Le serveur ignore « Range » et enverrait tout le fichier : on abandonne.
                raise MkvFastPathUnavailable("le serveur ne permet pas la lecture par morceaux")
            data = bytearray()
            for chunk in resp.iter_content(chunk_size=65536):
                data += chunk
                if len(data) >= length:
                    break
            return bytes(data[:length])


# --- Décodage EBML ---------------------------------------------------------------------------


def read_vint(buf: bytes, pos: int, keep_marker: bool = False) -> tuple[int | None, int]:
    """Entier de longueur variable EBML. Renvoie (valeur, nombre d'octets) ; valeur None pour
    une taille « inconnue » (tous les bits à 1)."""
    if pos >= len(buf):
        raise MkvFastPathUnavailable("données tronquées")
    first = buf[pos]
    if first == 0:
        raise MkvFastPathUnavailable("entier EBML invalide")
    length = 9 - first.bit_length()
    if pos + length > len(buf):
        raise MkvFastPathUnavailable("données tronquées")
    value = first if keep_marker else first & (0xFF >> length)
    for byte in buf[pos + 1 : pos + length]:
        value = (value << 8) | byte
    if not keep_marker and value == (1 << (7 * length)) - 1:
        return None, length
    return value, length


def element_header(buf: bytes, pos: int) -> tuple[int, int, int | None]:
    """(identifiant, début des données, taille des données ou None)."""
    eid, n_id = read_vint(buf, pos, keep_marker=True)
    size, n_size = read_vint(buf, pos + n_id)
    return eid, pos + n_id + n_size, size


def children(buf: bytes, start: int, end: int):
    """Éléments contenus entre `start` et `end` : (id, début des données, taille, début)."""
    pos = start
    while pos < end:
        eid, data, size = element_header(buf, pos)
        yield eid, data, size, pos
        if size is None:
            return
        pos = data + size


def as_uint(data: bytes) -> int:
    return int.from_bytes(data, "big") if data else 0


def as_text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace").rstrip("\x00")


# --- Structure du fichier --------------------------------------------------------------------


@dataclass
class TextTrack:
    number: int
    codec: str
    language: str
    name: str
    default: bool
    forced: bool
    compression: tuple[int, bytes] | None  # (algorithme, réglages) : 0 = zlib, 3 = en-tête retiré


@dataclass
class IndexEntry:
    time: int  # en unités de TimestampScale
    cluster_position: int  # relative au début des données du Segment
    relative_position: int  # relative au début des données du Cluster
    duration: int | None


def _parse_tracks(data: bytes) -> list[TextTrack]:
    tracks = []
    for eid, start, size, _ in children(data, 0, len(data)):
        if eid != TRACK_ENTRY:
            continue
        fields: dict[int, bytes] = {}
        compression = None
        for cid, cstart, csize, _ in children(data, start, start + size):
            fields[cid] = data[cstart : cstart + csize]
            if cid == CONTENT_ENCODINGS:
                compression = _parse_compression(data, cstart, cstart + csize)
        if as_uint(fields.get(TRACK_TYPE, b"")) != SUBTITLE_TRACK:
            continue
        codec = as_text(fields.get(CODEC_ID, b""))
        if codec not in TEXT_CODECS:
            continue
        language = as_text(fields[LANGUAGE_BCP47]) if LANGUAGE_BCP47 in fields else (
            as_text(fields[LANGUAGE]) if LANGUAGE in fields else "eng"  # valeur par défaut Matroska
        )
        tracks.append(TextTrack(
            number=as_uint(fields.get(TRACK_NUMBER, b"")), codec=codec, language=language,
            name=as_text(fields.get(NAME, b"")),
            default=as_uint(fields.get(FLAG_DEFAULT, b"\x01")) == 1,
            forced=as_uint(fields.get(FLAG_FORCED, b"\x00")) == 1,
            compression=compression,
        ))
    return tracks


def _parse_compression(data: bytes, start: int, end: int) -> tuple[int, bytes] | None:
    for eid, s1, z1, _ in children(data, start, end):
        if eid != CONTENT_ENCODING:
            continue
        for cid, s2, z2, _ in children(data, s1, s1 + z1):
            if cid != CONTENT_COMPRESSION:
                continue
            algo, settings = 0, b""
            for kid, s3, z3, _ in children(data, s2, s2 + z2):
                if kid == COMPRESSION_ALGO:
                    algo = as_uint(data[s3 : s3 + z3])
                elif kid == COMPRESSION_SETTINGS:
                    settings = data[s3 : s3 + z3]
            return algo, settings
    return None


def _parse_cues(data: bytes, track_number: int) -> list[IndexEntry]:
    entries = []
    for eid, start, size, _ in children(data, 0, len(data)):
        if eid != CUE_POINT:
            continue
        time = 0
        positions = []
        for cid, cstart, csize, _ in children(data, start, start + size):
            if cid == CUE_TIME:
                time = as_uint(data[cstart : cstart + csize])
            elif cid == CUE_TRACK_POSITIONS:
                fields = {k: as_uint(data[s : s + z]) for k, s, z, _ in
                          children(data, cstart, cstart + csize)}
                positions.append(fields)
        for fields in positions:
            if fields.get(CUE_TRACK) != track_number:
                continue
            if CUE_RELATIVE_POSITION not in fields or CUE_CLUSTER_POSITION not in fields:
                raise MkvFastPathUnavailable("index sans position précise des sous-titres")
            entries.append(IndexEntry(time, fields[CUE_CLUSTER_POSITION],
                                      fields[CUE_RELATIVE_POSITION], fields.get(CUE_DURATION)))
    # Une même réplique peut être référencée plusieurs fois.
    unique = {(e.cluster_position, e.relative_position): e for e in entries}
    return sorted(unique.values(), key=lambda e: e.time)


def choose_text_track(tracks: list[TextTrack], language: str, prefer_sdh: bool = False):
    candidates = [t for t in tracks if lang_matches(t.language, language)]
    if not candidates:
        return None

    def is_sdh(t: TextTrack) -> bool:
        return bool(re.search(r"sdh|sme|malentendant|hearing", t.name, re.I))

    def is_forced(t: TextTrack) -> bool:
        return t.forced or bool(re.search(r"forc", t.name, re.I))

    candidates.sort(key=lambda t: (is_forced(t), is_sdh(t) != prefer_sdh, not t.default))
    return candidates[0]


# --- Texte des sous-titres -------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>|\{[^}]*\}")


def block_text(codec: str, payload: bytes) -> str:
    text = payload.decode("utf-8", errors="replace")
    if codec in ("S_TEXT/ASS", "S_TEXT/SSA"):
        # ReadOrder, Layer, Style, Name, MarginL, MarginR, MarginV, Effect, Text
        text = text.split(",", 8)[-1]
        text = text.replace("\\N", "\n").replace("\\n", "\n").replace("\\h", " ")
    text = _TAG_RE.sub("", text.replace("\r\n", "\n"))
    return "\n".join(line.strip() for line in text.strip().splitlines() if line.strip())


def _decompress(track: TextTrack, payload: bytes) -> bytes:
    if not track.compression:
        return payload
    algo, settings = track.compression
    if algo == 0:
        return zlib.decompress(payload)
    if algo == 3:
        return settings + payload
    raise MkvFastPathUnavailable(f"compression {algo} non gérée")


# --- Lecture rapide --------------------------------------------------------------------------


class MkvSubtitleReader:
    def __init__(self, source: str, reader: RangeReader | None = None):
        self.reader = reader or RangeReader(source)
        self.segment_start = 0
        self.timestamp_scale = 1_000_000  # ns par unité (valeur par défaut Matroska)
        self._cluster_header_len: int | None = None

    def _element_at(self, offset: int, max_size: int) -> bytes:
        head = self.reader.read(offset, 16)
        _, data_start, size = element_header(head, 0)
        if size is None or size > max_size:
            raise MkvFastPathUnavailable("élément trop grand ou de taille inconnue")
        return self.reader.read(offset + data_start, size)

    def load_index(self, language: str, prefer_sdh: bool = False):
        head = self.reader.read(0, HEAD_BYTES)
        eid, data, size = element_header(head, 0)
        if eid != EBML_HEADER or size is None:
            raise MkvFastPathUnavailable("ce n'est pas un fichier MKV")
        eid, self.segment_start, _ = element_header(head, data + size)
        if eid != SEGMENT:
            raise MkvFastPathUnavailable("segment MKV introuvable")

        found: dict[int, bytes] = {}
        positions: dict[int, int] = {}
        for eid, start, size, _ in children(head, self.segment_start, len(head)):
            if size is None or eid == CLUSTER or start + size > len(head):
                break
            if eid in (INFO, TRACKS, CUES):
                found[eid] = head[start : start + size]
            elif eid == SEEK_HEAD:
                for sid, s1, z1, _ in children(head, start, start + size):
                    if sid != SEEK:
                        continue
                    fields = {k: head[s : s + z] for k, s, z, _ in children(head, s1, s1 + z1)}
                    if SEEK_ID in fields and SEEK_POSITION in fields:
                        positions[as_uint(fields[SEEK_ID])] = as_uint(fields[SEEK_POSITION])

        for eid in (INFO, TRACKS, CUES):
            if eid not in found and eid in positions:
                found[eid] = self._element_at(self.segment_start + positions[eid], MAX_INDEX_BYTES)
        if TRACKS not in found:
            raise MkvFastPathUnavailable("liste des pistes introuvable")
        if CUES not in found:
            raise MkvFastPathUnavailable("pas d'index dans ce fichier")
        if INFO in found:
            for eid, start, size, _ in children(found[INFO], 0, len(found[INFO])):
                if eid == TIMESTAMP_SCALE:
                    self.timestamp_scale = as_uint(found[INFO][start : start + size])

        track = choose_text_track(_parse_tracks(found[TRACKS]), language, prefer_sdh)
        if track is None:
            raise MkvFastPathUnavailable(f"pas de piste texte « {language} »")
        entries = _parse_cues(found[CUES], track.number)
        if not entries:
            raise MkvFastPathUnavailable("l'index ne référence pas les sous-titres")
        return track, entries

    def _ms(self, units: int) -> int:
        return round(units * self.timestamp_scale / 1_000_000)

    def _cluster_header(self, cluster_offset: int) -> int:
        _, data_start, _ = element_header(self.reader.read(cluster_offset, 12), 0)
        return data_start

    def _parse_block(self, buf: bytes, track: TextTrack) -> tuple[bytes, int | None] | None:
        """(contenu, durée) si `buf` commence par un bloc de cette piste, sinon None."""
        try:
            eid, start, size = element_header(buf, 0)
        except MkvFastPathUnavailable:
            return None
        if eid not in (SIMPLE_BLOCK, BLOCK_GROUP) or size is None:
            return None
        if start + size > len(buf):
            return b"", -1  # bloc plus long que ce qu'on a lu : à relire en entier
        block, duration = None, None
        if eid == SIMPLE_BLOCK:
            block = buf[start : start + size]
        else:
            for cid, cstart, csize, _ in children(buf, start, start + size):
                if cid == BLOCK:
                    block = buf[cstart : cstart + csize]
                elif cid == BLOCK_DURATION:
                    duration = as_uint(buf[cstart : cstart + csize])
        if block is None:
            return None
        number, n = read_vint(block, 0)
        if number != track.number or len(block) < n + 3:
            return None
        flags = block[n + 2]
        if flags & 0x06:  # « lacing » : jamais utilisé pour des sous-titres
            raise MkvFastPathUnavailable("bloc de sous-titres groupé non géré")
        return block[n + 3 :], duration

    def read_entry(self, track: TextTrack, entry: IndexEntry) -> tuple[Cue, bool] | None:
        """(réplique, durée connue ?) ou None pour un bloc vide."""
        cluster = self.segment_start + entry.cluster_position
        header_len = self._cluster_header_len or self._cluster_header(cluster)
        for attempt in range(2):
            offset = cluster + header_len + entry.relative_position
            buf = self.reader.read(offset, BLOCK_READ)
            parsed = self._parse_block(buf, track)
            if parsed and parsed[1] == -1:  # bloc long : on relit exactement sa taille
                _, start, size = element_header(buf, 0)
                parsed = self._parse_block(self.reader.read(offset, start + size), track)
            if parsed:
                self._cluster_header_len = header_len
                payload, duration = parsed
                break
            # En-tête de cluster d'une autre longueur que prévu : on le lit vraiment.
            header_len = self._cluster_header(cluster)
        else:
            raise MkvFastPathUnavailable("position d'un sous-titre incohérente")
        text = block_text(track.codec, _decompress(track, payload))
        if not text:
            return None
        units = duration if duration else entry.duration
        start_ms = self._ms(entry.time)
        return Cue(start_ms, start_ms + (self._ms(units) if units else 3000), text), bool(units)


def read_mkv_subtitles(
    source: str,
    language: str = "fr",
    prefer_sdh: bool = False,
    on_progress: Callable[[float], None] | None = None,
    cancel: threading.Event | None = None,
    workers: int = 4,
    reader: RangeReader | None = None,
) -> tuple[list[Cue], TextTrack]:
    """Toutes les répliques de la piste texte `language`, sans lire la vidéo.

    Les morceaux sont lus par `workers` connexions à la fois ; si le serveur refuse ce
    parallélisme (erreurs 429 / 503, connexions coupées), on recommence avec une seule
    connexion, plus lente mais acceptée partout.
    """
    try:
        return _read_all(source, language, prefer_sdh, on_progress, cancel, workers, reader)
    except (requests.HTTPError, requests.ConnectionError, requests.Timeout):
        if workers <= 1 or (cancel is not None and cancel.is_set()):
            raise
        return _read_all(source, language, prefer_sdh, on_progress, cancel, 1, reader)


def _read_all(source, language, prefer_sdh, on_progress, cancel, workers, reader):
    mkv = MkvSubtitleReader(source, reader)
    track, entries = mkv.load_index(language, prefer_sdh)
    # Le premier bloc, lu seul, fixe la longueur des en-têtes de cluster pour les suivants.
    first = mkv.read_entry(track, entries[0])
    done = [1]
    lock = threading.Lock()

    def fetch(entry: IndexEntry) -> tuple[Cue, bool] | None:
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        cue = mkv.read_entry(track, entry)
        with lock:
            done[0] += 1
            if on_progress:
                on_progress(done[0] / len(entries))
        return cue

    if workers <= 1:
        rest = [fetch(entry) for entry in entries[1:]]
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="subtrad-mkv") as pool:
            rest = list(pool.map(fetch, entries[1:]))
    found = [r for r in [first, *rest] if r is not None]
    cues = [cue for cue, _ in found]
    # Durée inconnue (3 s par défaut) : la réplique s'arrête au plus tard à la suivante.
    for i, (cue, known) in enumerate(found[:-1]):
        nxt = cues[i + 1]
        if not known and cue.start_ms < nxt.start_ms < cue.end_ms:
            cues[i] = Cue(cue.start_ms, nxt.start_ms, cue.text)
    return cues, track
