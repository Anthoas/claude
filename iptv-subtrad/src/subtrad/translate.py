"""Traduction des sous-titres par lots avec l'API Claude."""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Protocol

import anthropic

from .cache import TranslationCache
from .errors import Cancelled
from .subtitles import Cue

# Haiku suffit pour les sous-titres (jugé suffisant à l'essai) et coûte ~20x moins que Sonnet.
DEFAULT_MODEL = "claude-haiku-5-5"

log = logging.getLogger(__name__)

# Prix en dollars par million de tokens (entrée, sortie), pour estimer le coût affiché.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}

LANGUAGE_NAMES = {
    "fr": "French",
    "en": "English",
    "id": "Indonesian (Bahasa Indonesia)",
}

SYSTEM_PROMPT = """You translate TV and film subtitles from {source} into {target}.

The viewer reads them on screen while watching, so:
- Write natural, everyday spoken {target}, not a literal word-for-word rendering.
- Keep each subtitle short enough to read in the time it is displayed: at most two lines, \
roughly 42 characters per line. Keep the original line breaks when they make sense.
- Translate every cue on its own, using the surrounding cues only to resolve meaning \
(who is speaking, pronouns, running jokes). Never merge or split cues.
- Keep names, places and brands as they are. Adapt idioms and wordplay to an equivalent \
{target} expression when one exists.
- Sound descriptions for deaf and hard-of-hearing viewers, such as [Musique] or (rires), \
are translated too and keep their brackets.

Return one translation for every cue id you are given, and nothing else."""

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "text": {"type": "string"},
                },
                "required": ["id", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["translations"],
    "additionalProperties": False,
}


class TranslationError(RuntimeError):
    pass


class Translator(Protocol):
    """Interface commune : permet de brancher un autre moteur (local, de test...)."""

    namespace: str  # identifie le moteur et les langues dans le cache

    def translate_batch(
        self, texts: list[str], context: list[tuple[str, str | None]]
    ) -> list[str]:
        """Traduit `texts` ; `context` = répliques précédentes (original, traduction ou None
        quand elle n'est pas encore connue, en traduction parallèle)."""
        ...


class ClaudeTranslator:
    def __init__(
        self,
        source: str = "fr",
        target: str = "id",
        model: str = DEFAULT_MODEL,
        effort: str = "low",
        client: anthropic.Anthropic | None = None,
    ):
        self.source, self.target, self.model, self.effort = source, target, model, effort
        self.client = client or anthropic.Anthropic()
        self.namespace = f"claude:{model}:{source}>{target}"
        self.calls = self.input_tokens = self.output_tokens = 0
        self._usage_lock = threading.Lock()
        self.system = SYSTEM_PROMPT.format(
            source=LANGUAGE_NAMES.get(source, source),
            target=LANGUAGE_NAMES.get(target, target),
        )

    def translate_batch(
        self, texts: list[str], context: list[tuple[str, str | None]]
    ) -> list[str]:
        payload = {
            "previous_cues": [
                {"original": o, **({"translation": t} if t is not None else {})}
                for o, t in context
            ],
            "cues": [{"id": i, "text": text} for i, text in enumerate(texts)],
        }
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            # Si un filtre de sécurité refuse la requête, l'API la relance sur un autre
            # modèle quand la catégorie du refus le permet (API Claude uniquement).
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": _RESPONSE_SCHEMA},
            },
            system=self.system,
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        )

        usage = getattr(response, "usage", None)
        if usage:
            with self._usage_lock:  # plusieurs lots peuvent être traduits en même temps
                self.calls += 1
                self.input_tokens += usage.input_tokens or 0
                self.output_tokens += usage.output_tokens or 0

        if response.stop_reason in ("refusal", "max_tokens"):
            if len(texts) == 1:
                if response.stop_reason == "max_tokens":
                    raise TranslationError("Réponse tronquée sur une seule réplique.")
                # Une réplique isolée refusée (dialogue violent, par ex.) : on garde l'original
                # plutôt que d'interrompre tout le film.
                log.warning("Réplique non traduite (refus) : %r", texts[0])
                return list(texts)
            # Lot trop long pour une réponse, ou refusé à cause d'une seule réplique :
            # on le coupe en deux pour isoler le problème.
            half = len(texts) // 2
            first = self.translate_batch(texts[:half], context)
            return first + self.translate_batch(
                texts[half:], context + list(zip(texts[:half], first))
            )

        raw = next(b.text for b in response.content if b.type == "text")
        by_id = {item["id"]: item["text"] for item in json.loads(raw)["translations"]}
        missing = [i for i in range(len(texts)) if i not in by_id]
        if missing:
            if len(texts) == 1:
                # Toujours absente : on garde l'original plutôt que d'interrompre tout le film.
                log.warning("Réplique non traduite (absente de la réponse) : %r", texts[0])
                return list(texts)
            # Réponse incomplète : on redemande seulement les répliques oubliées.
            log.warning("Répliques absentes de la réponse, nouvelle demande : %s", missing)
            retried = self.translate_batch([texts[i] for i in missing], context)
            by_id.update(zip(missing, retried))
        return [by_id[i] for i in range(len(texts))]


    def estimated_cost(self) -> float | None:
        """Coût estimé en dollars, None si le modèle n'est pas dans la grille de prix."""
        if self.model not in PRICES:
            return None
        price_in, price_out = PRICES[self.model]
        return (self.input_tokens * price_in + self.output_tokens * price_out) / 1_000_000

    def usage_summary(self) -> str:
        if not self.calls:
            return "aucune requête envoyée (tout venait du cache)"

        def fmt(n: int) -> str:
            return f"{n:,}".replace(",", "\u202f")

        cost = self.estimated_cost()
        price = f"coût estimé : {cost:.3f} $".replace(".", ",") + ", " if cost is not None else ""
        return (
            f"{price}{self.calls} requêtes, "
            f"{fmt(self.input_tokens)} tokens envoyés et {fmt(self.output_tokens)} reçus"
        )


def translate_cues(
    cues: list[Cue],
    translator: Translator,
    cache: TranslationCache | None = None,
    batch_size: int = 40,
    context_size: int = 5,
    on_progress: Callable[[int, int], None] | None = None,
    history: list[tuple[str, str | None]] | None = None,
) -> list[Cue]:
    """Traduit toutes les répliques, par lots, en réutilisant le cache.

    `history` : dernières répliques déjà traduites (original, traduction) qui précèdent
    `cues`, utilisées comme contexte (mode direct, où les répliques arrivent par paquets).
    """
    texts = [c.text for c in cues]
    done: dict[str, str] = cache.get_many(translator.namespace, texts) if cache else {}
    # Une seule traduction par texte distinct (« Oui. », « Merci. » reviennent souvent).
    todo, seen = [], set(done)
    for i, text in enumerate(texts):
        if text not in seen:
            seen.add(text)
            todo.append(i)

    for start in range(0, len(todo), batch_size):
        indices = todo[start : start + batch_size]
        # Contexte : les répliques qui précèdent le lot dans le film, déjà traduites.
        first = indices[0]
        context = list(history or []) + [
            (texts[j], done[texts[j]])
            for j in range(max(0, first - context_size), first)
            if texts[j] in done
        ]
        context = context[-context_size:] if context_size else []
        batch = [texts[i] for i in indices]
        result = dict(zip(batch, translator.translate_batch(batch, context)))
        done.update(result)
        if cache:
            # Une réplique rendue telle quelle (refus) n'est pas mise en cache : elle sera
            # retentée la prochaine fois.
            cache.put_many(translator.namespace, {k: v for k, v in result.items() if k != v})
        if on_progress:
            on_progress(min(start + batch_size, len(todo)), len(todo))

    return [cue.with_text(done[cue.text]) for cue in cues]


class TranslationPipeline:
    """Traduit des répliques au fil de leur arrivée, en envoyant plusieurs lots à la fois.

    On lui passe les répliques pendant qu'elles sont extraites du fichier : la traduction
    avance en même temps que la lecture au lieu d'attendre la fin, et plusieurs requêtes
    partent en parallèle. Chaque lot reçoit comme contexte les répliques d'origine qui le
    précèdent (leur traduction n'est pas forcément déjà connue).
    """

    def __init__(
        self,
        translator: Translator,
        cache: TranslationCache | None = None,
        batch_size: int = 40,
        workers: int = 4,
        context_size: int = 5,
        first_batch_size: int | None = None,
        on_batch: Callable[[list[Cue]], None] | None = None,
        cancel: threading.Event | None = None,
        keep_original_on_error: bool = False,
    ):
        self.translator, self.cache = translator, cache
        self.batch_size, self.context_size = batch_size, context_size
        self.on_batch, self.cancel = on_batch, cancel
        self.keep_original_on_error = keep_original_on_error
        # Un premier lot plus petit : les premières répliques sont prêtes plus vite.
        self._next_size = first_batch_size or batch_size
        self._buffer: list[Cue] = []
        self._recent: deque[str] = deque(maxlen=context_size)
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="subtrad-tr")
        self._futures: list[Future] = []
        self._lock = threading.Lock()
        self._results: list[Cue] = []
        self.found = 0
        self.translated = 0
        self.failed = 0  # lots restés dans la langue d'origine (keep_original_on_error)

    def add(self, cues: list[Cue]) -> None:
        for cue in cues:
            self._buffer.append(cue)
            self.found += 1
            if len(self._buffer) >= self._next_size:
                self.flush()

    def flush(self) -> None:
        """Envoie tout de suite les répliques en attente, même si le lot est incomplet."""
        if not self._buffer:
            return
        batch, self._buffer = self._buffer, []
        self._next_size = self.batch_size
        context = [(text, None) for text in self._recent]
        self._recent.extend(cue.text for cue in batch)
        self._futures.append(self._executor.submit(self._translate, batch, context))

    def _translate(self, batch: list[Cue], context: list[tuple[str, None]]) -> None:
        if self.cancel is not None and self.cancel.is_set():
            raise Cancelled()
        try:
            out = translate_cues(batch, self.translator, self.cache, len(batch),
                                 self.context_size, history=context)
        except Exception as exc:
            if not self.keep_original_on_error:
                raise
            log.warning("Traduction impossible (%s) : sous-titres d'origine gardés.", exc)
            out = list(batch)
            self.failed += 1
        with self._lock:
            self._results.extend(out)
            self.translated += len(out)
        if self.on_batch:
            self.on_batch(out)

    def finish(self) -> list[Cue]:
        """Attend la fin de toutes les traductions et les renvoie dans l'ordre du film."""
        self.flush()
        try:
            for future in self._futures:
                future.result()  # relaie la première erreur
        finally:
            self.close()
        with self._lock:
            return sorted(self._results, key=lambda c: (c.start_ms, c.end_ms))

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
