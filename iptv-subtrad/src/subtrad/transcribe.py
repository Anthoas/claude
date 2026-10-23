"""Transcription de la voix avec Whisper, pour les vidéos sans sous-titres en texte.

Tout se passe sur cette machine (aucun coût) : ffmpeg lit le son, on le découpe en morceaux
d'environ 30 s aux moments de silence, Whisper les transcrit, puis on en fait des
sous-titres lisibles à l'écran. Les répliques sortent au fur et à mesure, pour être
traduites pendant que la transcription continue.

Deux moteurs, choisis automatiquement :
- whisper.cpp (`brew install whisper-cpp` sur Mac) : programme déjà compilé, rapide, qui
  utilise la puce graphique des Mac Apple ; aucune dépendance Python. Le modèle (~570 Mo)
  est téléchargé au premier usage ;
- faster-whisper (extra `.[whisper]`), pour les autres systèmes.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unicodedata
import wave
from array import array
from pathlib import Path
from typing import Callable, Iterator, NamedTuple, Protocol

import requests

from .errors import Cancelled
from .extract import _require, kill_when_cancelled
from .subtitles import Cue

SAMPLE_RATE = 16_000
CHUNK_SECONDS = 30.0  # Whisper travaille par fenêtres de 30 s
SEARCH_SECONDS = 8.0  # on cherche un silence dans les 8 dernières secondes du morceau
MAX_CHARS_PER_CUE = 84  # deux lignes de ~42 caractères
MAX_CHARS_PER_LINE = 42

WHISPER_CPP_BINARIES = ("whisper-cli", "whisper-cpp")  # nom selon la version de whisper.cpp
WHISPER_CPP_MODEL = "ggml-large-v3-turbo-q5_0.bin"  # ~570 Mo, bon compromis qualité / vitesse
WHISPER_CPP_MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{name}"
FASTER_WHISPER_MODEL = "small"

# Phrases que Whisper invente sur des silences ou de la musique (en français surtout).
_HALLUCINATIONS = (
    "amara.org", "sous-titrage st", "sous-titres realises", "sous-titrage societe radio-canada",
    "sous-titrage fr", "merci d'avoir regarde", "abonnez-vous", "n'oubliez pas de vous abonner",
    "sous-titres par", "transcription par", "thanks for watching",
)

StatusCallback = Callable[[str, "float | None"], None]


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

    def transcribe(self, audio: bytes, language: str) -> list[Segment]:
        """`audio` : son mono 16 kHz, entiers 16 bits petit-boutistes (PCM s16le)."""
        ...


# --- whisper.cpp ---------------------------------------------------------------------------


def find_whisper_cpp() -> str | None:
    for name in WHISPER_CPP_BINARIES:
        found = shutil.which(name)
        if found:
            return found
    for directory in ("/opt/homebrew/bin", "/usr/local/bin"):  # Homebrew hors du PATH
        for name in WHISPER_CPP_BINARIES:
            candidate = Path(directory) / name
            if candidate.exists():
                return str(candidate)
    return None


def models_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "subtrad" / "whisper"


def ensure_model(name: str = WHISPER_CPP_MODEL, on_status: StatusCallback | None = None,
                 url: str | None = None) -> Path:
    """Chemin du modèle whisper.cpp, téléchargé une seule fois s'il manque."""
    path = models_dir() / name
    if path.exists() and path.stat().st_size > 0:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    with requests.get(url or WHISPER_CPP_MODEL_URL.format(name=name), stream=True,
                      timeout=(15, 120)) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(partial, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                f.write(chunk)
                done += len(chunk)
                if on_status and total:
                    on_status(f"Téléchargement du modèle Whisper (une seule fois) : "
                              f"{done / total:.0%} de {total / 1e6:.0f} Mo", done / total)
                elif on_status:
                    on_status(f"Téléchargement du modèle Whisper (une seule fois) : "
                              f"{done / 1e6:.0f} Mo", None)
    partial.replace(path)
    return path


class WhisperCppTranscriber:
    name = "whisper.cpp"

    def __init__(self, model: str | None = None, binary: str | None = None,
                 model_url: str | None = None):
        self.binary = binary or find_whisper_cpp()
        if not self.binary:
            raise WhisperUnavailable("whisper.cpp introuvable : brew install whisper-cpp")
        self.model_name = model or WHISPER_CPP_MODEL
        self.model_url = model_url
        self.model_path: Path | None = None
        self.threads = max(1, min(8, os.cpu_count() or 4))

    def prepare(self, on_status: StatusCallback | None = None) -> None:
        if self.model_path is None:
            self.model_path = ensure_model(self.model_name, on_status, self.model_url)

    def transcribe(self, audio: bytes, language: str) -> list[Segment]:
        self.prepare()
        with tempfile.TemporaryDirectory(prefix="subtrad-whisper-") as tmp:
            wav_path, out_base = Path(tmp) / "morceau.wav", Path(tmp) / "resultat"
            with wave.open(str(wav_path), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(SAMPLE_RATE)
                wav.writeframes(audio)
            result = subprocess.run(
                [self.binary, "-m", str(self.model_path), "-f", str(wav_path), "-l", language,
                 "-t", str(self.threads), "-oj", "-of", str(out_base), "-np"],
                capture_output=True, text=True, errors="replace",
            )
            if result.returncode != 0:
                raise RuntimeError(f"whisper.cpp a échoué : {result.stderr.strip()[-300:]}")
            data = json.loads(out_base.with_suffix(".json").read_text(encoding="utf-8",
                                                                      errors="replace"))
        return [
            Segment(item["offsets"]["from"] / 1000, item["offsets"]["to"] / 1000, item.get("text", ""))
            for item in data.get("transcription", [])
        ]


# --- faster-whisper (hors Mac) -----------------------------------------------------------


class FasterWhisperTranscriber:
    name = "faster-whisper"

    def __init__(self, model: str | None = None):
        from faster_whisper import WhisperModel

        self._model = WhisperModel(model or FASTER_WHISPER_MODEL, device="auto",
                                   compute_type="int8")

    def transcribe(self, audio: bytes, language: str) -> list[Segment]:
        import numpy as np

        samples = np.frombuffer(audio, dtype="<i2").astype(np.float32) / 32768.0
        segments, _ = self._model.transcribe(
            samples, language=language, vad_filter=True, condition_on_previous_text=False,
        )
        return [Segment(s.start, s.end, s.text, s.no_speech_prob, s.avg_logprob) for s in segments]


def backend_name() -> str | None:
    """Moteur Whisper installé et utilisable sur cette machine, ou None."""
    if find_whisper_cpp():
        return "whisper.cpp"
    if importlib.util.find_spec("faster_whisper"):
        return "faster-whisper"
    return None


def make_transcriber(model: str | None = None) -> Transcriber:
    backend = backend_name()
    if backend == "whisper.cpp":
        return WhisperCppTranscriber(model)
    if backend == "faster-whisper":
        return FasterWhisperTranscriber(model)
    raise WhisperUnavailable(
        "Whisper n'est pas installé : sur Mac, tape « brew install whisper-cpp » (voir la notice)."
    )


# --- Découpage du son -------------------------------------------------------------------------


def _samples(data: bytes) -> array:
    samples = array("h")
    samples.frombytes(data)
    if sys.byteorder == "big":
        samples.byteswap()
    return samples


def _cut_point(samples: array, search: int) -> int:
    """Indice du passage le plus silencieux dans les `search` derniers échantillons."""
    frame = SAMPLE_RATE // 20  # 50 ms
    start = len(samples) - search
    best, best_energy = len(samples), None
    for i in range(search // frame):
        a = start + i * frame
        energy = sum(x * x for x in samples[a : a + frame : 4])  # 1 sur 4 suffit
        if best_energy is None or energy < best_energy:
            best, best_energy = a + frame // 2, energy
    return best


def iter_audio_chunks(
    url: str,
    on_position: Callable[[float], None] | None = None,
    cancel: threading.Event | None = None,
    chunk_seconds: float = CHUNK_SECONDS,
    search_seconds: float = SEARCH_SECONDS,
) -> Iterator[tuple[float, bytes]]:
    """Donne (début en secondes, son PCM s16le) par morceaux d'environ `chunk_seconds`,
    coupés sur un silence. `on_position(secondes)` suit la lecture du son."""
    process = subprocess.Popen(
        [_require("ffmpeg"), "-v", "error", "-nostdin", "-i", url,
         "-vn", "-sn", "-dn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    kill_when_cancelled(process, cancel)
    chunk_bytes = int(chunk_seconds * SAMPLE_RATE) * 2
    search = int(search_seconds * SAMPLE_RATE)
    buffer = bytearray()
    offset = 0  # en échantillons
    read = 0
    try:
        while True:
            data = process.stdout.read(65536)
            if not data:
                break
            buffer += data
            read += len(data)
            if on_position:
                on_position(read / 2 / SAMPLE_RATE)
            while len(buffer) >= chunk_bytes:
                cut = _cut_point(_samples(bytes(buffer[:chunk_bytes])), search)
                yield offset / SAMPLE_RATE, bytes(buffer[: cut * 2])
                offset += cut
                del buffer[: cut * 2]
        process.wait()
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        if process.returncode != 0:
            message = process.stderr.read().decode("utf-8", "replace").strip()[-300:]
            raise RuntimeError(f"ffmpeg n'a pas pu lire le son : {message}")
        usable = len(buffer) - len(buffer) % 2
        if usable > SAMPLE_RATE:  # plus d'une demi-seconde
            yield offset / SAMPLE_RATE, bytes(buffer[:usable])
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
    if re.fullmatch(r"[\[(*].*[\])*]", norm.strip()):  # [BLANK_AUDIO], (musique), *rires*
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

    status("Préparation de Whisper…")
    if hasattr(transcriber, "prepare"):
        transcriber.prepare(on_status)  # télécharge le modèle au premier usage
    status("Transcription de la voix (Whisper) : premier morceau…")
    for offset, audio in iter_audio_chunks(url, cancel=cancel):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        chunk_s = len(audio) / 2 / SAMPLE_RATE
        yield segments_to_cues(transcriber.transcribe(audio, language), offset, chunk_s)
        done = offset + chunk_s
        if duration:
            status(f"Transcription de la voix (Whisper) : {_minutes(done)} sur {_minutes(duration)}",
                   min(1.0, done / duration))
        else:
            status(f"Transcription de la voix (Whisper) : {_minutes(done)}")


def _minutes(seconds: float) -> str:
    return f"{int(seconds // 60)} min {int(seconds % 60):02d} s"
