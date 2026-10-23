"""Mode direct : suit la playlist de sous-titres d'un flux HLS en continu, traduit les
nouvelles répliques au fil de l'eau et les affiche dans mpv au bon moment.

Deux boucles tournent en parallèle :
- un thread « flux » interroge la playlist de sous-titres, télécharge les nouveaux segments
  WebVTT et les fait traduire ;
- la boucle d'affichage lit la position de lecture de mpv et montre la réplique en cours.

La lecture démarre plusieurs segments derrière le direct (`--marge`) : c'est le temps
dont dispose la traduction pour arriver avant l'image.
"""

from __future__ import annotations

import bisect
import logging
import threading
import time
from collections import deque
from typing import Callable, Protocol

from .cache import TranslationCache
from .hls import HlsClient, PtsUnwrapper, SubtitleTrack, parse_media_playlist, parse_vtt_segment
from .subtitles import Cue
from .translate import Translator, translate_cues

log = logging.getLogger(__name__)


class Timeline:
    """Répliques traduites, triées par début, partagées entre les deux boucles."""

    def __init__(self, keep_ms: int = 120_000):
        self._lock = threading.Lock()
        self._cues: list[Cue] = []
        self._starts: list[int] = []
        self.keep_ms = keep_ms

    def add(self, cues: list[Cue]) -> None:
        with self._lock:
            for cue in cues:
                i = bisect.bisect(self._starts, cue.start_ms)
                self._starts.insert(i, cue.start_ms)
                self._cues.insert(i, cue)

    def active(self, now_ms: int) -> list[Cue]:
        with self._lock:
            # On oublie les répliques terminées depuis longtemps (la mémoire reste bornée).
            while self._cues and self._cues[0].end_ms < now_ms - self.keep_ms:
                self._cues.pop(0)
                self._starts.pop(0)
            end = bisect.bisect_right(self._starts, now_ms)
            return [c for c in self._cues[:end] if c.end_ms > now_ms]

    def __len__(self) -> int:
        with self._lock:
            return len(self._cues)


class LiveSubtitleFeed:
    """Interroge la playlist de sous-titres et renvoie les répliques jamais vues."""

    def __init__(self, track: SubtitleTrack, hls: HlsClient | None = None):
        self.track = track
        self.hls = hls or HlsClient()
        self.target_duration = 6.0
        self._seen_segments: deque[str] = deque(maxlen=500)
        self._seen_cues: deque[Cue] = deque(maxlen=2000)
        self._unwrap = PtsUnwrapper()

    def poll(self) -> list[Cue]:
        playlist = parse_media_playlist(self.hls.get_text(self.track.uri), self.track.uri)
        self.target_duration = playlist.target_duration or self.target_duration
        new: list[Cue] = []
        for segment in playlist.segments:
            if segment in self._seen_segments:
                continue
            self._seen_segments.append(segment)
            for cue in parse_vtt_segment(self.hls.get_text(segment)):
                cue = Cue(self._unwrap(cue.start_ms), self._unwrap(cue.end_ms), cue.text)
                # Une réplique à cheval sur deux segments apparaît dans les deux.
                if cue not in self._seen_cues:
                    self._seen_cues.append(cue)
                    new.append(cue)
        new.sort(key=lambda c: c.start_ms)
        return new


class LivePlayer(Protocol):
    def is_running(self) -> bool: ...
    def time_pos(self) -> float | None: ...
    def show_overlay(self, text: str) -> None: ...
    def hide_overlay(self) -> None: ...


class LiveTranslator:
    """Thread « flux » : récupère les nouvelles répliques et les traduit dans la timeline."""

    def __init__(
        self,
        feed: LiveSubtitleFeed,
        translator: Translator,
        timeline: Timeline,
        cache: TranslationCache | None = None,
        batch_size: int = 40,
        context_size: int = 5,
    ):
        self.feed, self.translator, self.timeline = feed, translator, timeline
        self.cache, self.batch_size, self.context_size = cache, batch_size, context_size
        self.history: deque[tuple[str, str]] = deque(maxlen=context_size)
        self.stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def step(self) -> int:
        """Un tour : interroge le flux, traduit ce qui est nouveau. Renvoie le nombre ajouté."""
        cues = self.feed.poll()
        if not cues:
            return 0
        try:
            translated = translate_cues(
                cues, self.translator, self.cache, self.batch_size, self.context_size,
                history=list(self.history),
            )
        except Exception as exc:
            # Le direct ne doit pas s'arrêter pour une requête ratée : on affiche l'original.
            log.warning("Traduction impossible (%s) : sous-titres d'origine affichés.", exc)
            translated = cues
        self.history.extend((c.text, t.text) for c, t in zip(cues, translated))
        self.timeline.add(translated)
        return len(translated)

    def run(self) -> None:
        while not self.stop_event.is_set():
            started = time.monotonic()
            try:
                self.step()
            except Exception as exc:  # réseau coupé, playlist momentanément absente...
                log.warning("Lecture de la playlist de sous-titres : %s", exc)
            # Interroger deux fois par durée de segment, comme le recommande la spec HLS.
            delay = max(1.0, self.feed.target_duration / 2) - (time.monotonic() - started)
            self.stop_event.wait(max(0.0, delay))

    def start(self) -> "LiveTranslator":
        self._thread = threading.Thread(target=self.run, name="subtrad-live", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self.stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)


def display_loop(
    player: LivePlayer,
    timeline: Timeline,
    offset_ms: int = 0,
    interval: float = 0.1,
    should_stop: Callable[[], bool] = lambda: False,
) -> None:
    """Affiche la réplique en cours jusqu'à la fermeture de mpv.

    `offset_ms` > 0 retarde les sous-titres, < 0 les avance (réglage fin de la synchro).
    """
    shown = ""
    while player.is_running() and not should_stop():
        try:
            pos = player.time_pos()
        except (ConnectionError, OSError):
            break  # mpv vient d'être fermé
        if pos is not None:
            now_ms = int(pos * 1000) - offset_ms
            text = "\n".join(c.text for c in timeline.active(now_ms))
            if text != shown:
                if text:
                    player.show_overlay(text)
                else:
                    player.hide_overlay()
                shown = text
        time.sleep(interval)


def run_live(
    url: str,
    track: SubtitleTrack,
    translator: Translator,
    player,
    cache: TranslationCache | None = None,
    batch_size: int = 40,
    segments_behind: int = 6,
    offset_ms: int = 0,
    hls: HlsClient | None = None,
    should_stop: Callable[[], bool] = lambda: False,
) -> int:
    timeline = Timeline()
    worker = LiveTranslator(LiveSubtitleFeed(track, hls), translator, timeline, cache, batch_size)
    # Première traduction avant de lancer la vidéo : les premières répliques sont prêtes.
    worker.step()
    log.info("%d répliques déjà traduites, lancement de mpv.", len(timeline))
    worker.start()
    try:
        player.start(url, live_segments_behind=segments_behind)
        display_loop(player, timeline, offset_ms, should_stop=should_stop)
        if should_stop() and hasattr(player, "stop"):
            player.stop()
        return player.wait()
    finally:
        worker.stop()
