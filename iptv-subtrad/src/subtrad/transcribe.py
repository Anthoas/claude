"""Transcription de la voix avec Whisper, pour les vidéos sans sous-titres en texte.

Tout se passe sur ce Mac (aucun coût) : ffmpeg lit le son, on le découpe en morceaux
d'environ 30 s aux moments de silence, Whisper les transcrit, puis on en fait des
sous-titres lisibles à l'écran. Les répliques sortent au fur et à mesure, pour être
traduites pendant que la transcription continue.

Deux moteurs, choisis automatiquement :
- mlx-whisper sur les Mac à puce Apple (M1, M2...) : rapide, utilise la puce graphique ;
- faster-whisper ailleurs (Mac Intel, Linux, Windows) : sur le processeur, plus lent.
"""

from __future__ import annotations

import importlib.util
import platform
import re
import subprocess
import sys
import threading
import unicodedata
from typing import Callable, Iterator, NamedTuple, Protocol

from .errors import Cancelled
from .extract import _require, kill_when_cancelled
from .subtitles import Cue

SAMPLE_RATE = 16_000
CHUNK_SECONDS = 30.0  # Whisper travaille par fenêtres de 30 s
SEARCH_SECONDS = 8.0  # on cherche un silence dans les 8 dernières secondes du morceau
MAX_CHARS_PER_CUE = 84  # deux lignes de ~42 caractères
MAX_CHARS_PER_LINE = 42

DEFAULT_MODELS = {
    "mlx": "mlx-community/whisper-large-v3-turbo",  # ~1,6 Go, téléchargé au premier usage
    "faster-whisper": "small",
}

# Phrases que Whisper invente sur des silences ou de la musique (en français surtout).
_HALLUCINATIONS = (
    "amara.org", "sous-titrage st", "sous-titres realises", "sous-titrage societe radio-canada",
    "sous-titrage fr", "merci d'avoir regarde", "abonnez-vous", "n'oubliez pas de vous abonner",
    "sous-titres par", "transcription par", "thanks for watching",
)


class WhisperUnavailable(RuntimeError):
    pass


class Segment(NamedTuple):
    start: float  # secondes, relatives au début du morceau
    end: float
    text: str
    no_speech_prob: float = 0.0
    avg_logprob: float = 0.0


class Transcriber(Protocol):
    name: str

    def transcribe(self, audio, language: str) -> list[Segment]:
        """`audio` : tableau numpy float32, mono, 16 kHz."""
        ...


def backend_name() -> str | None:
    """Moteur Whisper installé et utilisable sur cette machine, ou None."""
    apple_silicon = sys.platform == "darwin" and platform.machine() == "arm64"
    if apple_silicon and importlib.util.find_spec("mlx_whisper"):
        return "mlx"
    if importlib.util.find_spec("faster_whisper"):
        return "faster-whisper"
    return None


class MlxTranscriber:
    name = "mlx"

    def __init__(self, model: str | None = None):
        self.model = model or DEFAULT_MODELS["mlx"]

    def transcribe(self, audio, language: str) -> list[Segment]:
        import mlx_whisper

        result = mlx_whisper.transcribe(
            audio, path_or_hf_repo=self.model, language=language,
            condition_on_previous_text=False, verbose=None,
        )
        return [
            Segment(s["start"], s["end"], s["text"], s.get("no_speech_prob", 0.0),
                    s.get("avg_logprob", 0.0))
            for s in result.get("segments", [])
        ]


class FasterWhisperTranscriber:
    name = "faster-whisper"

    def __init__(self, model: str | None = None):
        from faster_whisper import WhisperModel

        self._model = WhisperModel(model or DEFAULT_MODELS["faster-whisper"],
                                   device="auto", compute_type="int8")

    def transcribe(self, audio, language: str) -> list[Segment]:
        segments, _ = self._model.transcribe(
            audio, language=language, vad_filter=True, condition_on_previous_text=False,
        )
        return [Segment(s.start, s.end, s.text, s.no_speech_prob, s.avg_logprob) for s in segments]


def make_transcriber(model: str | None = None) -> Transcriber:
    backend = backend_name()
    if backend == "mlx":
        return MlxTranscriber(model)
    if backend == "faster-whisper":
        return FasterWhisperTranscriber(model)
    raise WhisperUnavailable(
        "Whisper n'est pas installé : voir la notice (pipx install --force \".[whisper]\")."
    )


# --- Découpage du son -------------------------------------------------------------------------


def _cut_point(samples, search: int) -> int:
    """Indice du passage le plus silencieux dans les `search` derniers échantillons."""
    import numpy as np

    frame = SAMPLE_RATE // 20  # 50 ms
    tail = samples[-search:].astype(np.float32)
    n = len(tail) // frame
    if n == 0:
        return len(samples)
    energy = (tail[: n * frame].reshape(n, frame) ** 2).mean(axis=1)
    quietest = int(energy.argmin())
    return len(samples) - search + quietest * frame + frame // 2


def iter_audio_chunks(
    url: str,
    on_position: Callable[[float], None] | None = None,
    cancel: threading.Event | None = None,
    chunk_seconds: float = CHUNK_SECONDS,
    search_seconds: float = SEARCH_SECONDS,
) -> Iterator[tuple[float, object]]:
    """Donne (début en secondes, son float32) par morceaux d'environ `chunk_seconds`,
    coupés sur un silence. `on_position(secondes)` suit la lecture du son."""
    import numpy as np

    process = subprocess.Popen(
        [_require("ffmpeg"), "-v", "error", "-nostdin", "-i", url,
         "-vn", "-sn", "-dn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    kill_when_cancelled(process, cancel)
    chunk = int(chunk_seconds * SAMPLE_RATE)
    search = int(search_seconds * SAMPLE_RATE)
    buffer = np.zeros(0, dtype=np.int16)
    offset = 0  # en échantillons
    read = 0
    try:
        while True:
            data = process.stdout.read(65536)
            if not data:
                break
            usable = len(data) - len(data) % 2
            buffer = np.concatenate([buffer, np.frombuffer(data[:usable], dtype=np.int16)])
            read += usable // 2
            if on_position:
                on_position(read / SAMPLE_RATE)
            while len(buffer) >= chunk:
                cut = _cut_point(buffer[:chunk], search)
                yield offset / SAMPLE_RATE, buffer[:cut].astype(np.float32) / 32768.0
                offset += cut
                buffer = buffer[cut:]
        process.wait()
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        if process.returncode != 0:
            message = process.stderr.read().decode("utf-8", "replace").strip()[-300:]
            raise RuntimeError(f"ffmpeg n'a pas pu lire le son : {message}")
        if len(buffer) > SAMPLE_RATE // 2:
            yield offset / SAMPLE_RATE, buffer.astype(np.float32) / 32768.0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


# --- Du texte transcrit aux sous-titres -------------------------------------------------------


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def is_hallucination(text: str) -> bool:
    norm = _normalize(text)
    if not re.search(r"\w", norm):  # que de la ponctuation ou des notes de musique
        return True
    return any(phrase in norm for phrase in _HALLUCINATIONS)


def wrap_lines(text: str, width: int = MAX_CHARS_PER_LINE) -> str:
    """Coupe en deux lignes équilibrées si le texte est trop long pour une seule."""
    if len(text) <= width:
        return text
    words = text.split()
    best, best_gap = text, len(text)
    for i in range(1, len(words)):
        first, second = " ".join(words[:i]), " ".join(words[i:])
        gap = abs(len(first) - len(second))
        if gap < best_gap:
            best, best_gap = f"{first}\n{second}", gap
    return best


def split_for_screen(start_ms: int, end_ms: int, text: str) -> list[Cue]:
    """Découpe une longue phrase en plusieurs sous-titres d'au plus deux lignes, le temps
    étant réparti selon la longueur de chaque morceau."""
    words = text.split()
    pieces, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > MAX_CHARS_PER_CUE and current:
            pieces.append(current)
            current = word
        else:
            current = candidate
    if current:
        pieces.append(current)
    total = sum(len(p) for p in pieces) or 1
    cues, t = [], start_ms
    for i, piece in enumerate(pieces):
        end = end_ms if i == len(pieces) - 1 else t + round((end_ms - start_ms) * len(piece) / total)
        cues.append(Cue(t, end, wrap_lines(piece)))
        t = end
    return cues


def segments_to_cues(segments: list[Segment], offset_s: float, chunk_s: float) -> list[Cue]:
    cues = []
    for seg in segments:
        text = " ".join(seg.text.split())
        if not text or is_hallucination(text):
            continue
        if seg.no_speech_prob > 0.6 and seg.avg_logprob < -1.0:  # probablement pas de la parole
            continue
        start = offset_s + max(0.0, seg.start)
        end = offset_s + min(max(seg.end, seg.start + 0.5), chunk_s)
        cues.extend(split_for_screen(round(start * 1000), round(end * 1000), text))
    return cues


def iter_transcribed_cues(
    url: str,
    transcriber: Transcriber,
    language: str = "fr",
    duration: float | None = None,
    on_status: Callable[[str, float | None], None] | None = None,
    cancel: threading.Event | None = None,
) -> Iterator[list[Cue]]:
    """Donne les répliques transcrites, morceau de son par morceau de son."""

    def status(message: str, fraction: float | None = None) -> None:
        if on_status:
            on_status(message, fraction)

    if transcriber.name == "mlx":
        status("Préparation de Whisper (au premier usage : téléchargement du modèle, ~1,6 Go)…")
    for offset, audio in iter_audio_chunks(url, cancel=cancel):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        chunk_s = len(audio) / SAMPLE_RATE
        yield segments_to_cues(transcriber.transcribe(audio, language), offset, chunk_s)
        done = offset + chunk_s
        if duration:
            status(f"Transcription de la voix (Whisper) : {_minutes(done)} sur {_minutes(duration)}",
                   min(1.0, done / duration))
        else:
            status(f"Transcription de la voix (Whisper) : {_minutes(done)}")


def _minutes(seconds: float) -> str:
    return f"{int(seconds // 60)} min {int(seconds % 60):02d} s"
