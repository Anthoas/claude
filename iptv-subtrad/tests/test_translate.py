import pytest
import json
from types import SimpleNamespace

from subtrad.cache import TranslationCache
from subtrad.subtitles import Cue, parse_subtitles, save_subtitles
from subtrad.translate import ClaudeTranslator, translate_cues


class FakeTranslator:
    namespace = "fake:fr>id"

    def __init__(self):
        self.calls = []

    def translate_batch(self, texts, context):
        self.calls.append((list(texts), list(context)))
        return [f"ID[{t}]" for t in texts]


CUES = [
    Cue(0, 1000, "Oui."),
    Cue(1000, 2000, "Bonjour."),
    Cue(2000, 3000, "Oui."),
    Cue(3000, 4000, "Merci."),
]


def test_translate_cues_dedupes_batches_and_passes_context():
    translator = FakeTranslator()
    result = translate_cues(CUES, translator, batch_size=2, context_size=5)
    assert [c.text for c in result] == ["ID[Oui.]", "ID[Bonjour.]", "ID[Oui.]", "ID[Merci.]"]
    assert [c.start_ms for c in result] == [0, 1000, 2000, 3000]
    # « Oui. » n'est traduit qu'une fois ; le 2e lot reçoit les répliques précédentes.
    assert translator.calls[0] == (["Oui.", "Bonjour."], [])
    assert translator.calls[1] == (
        ["Merci."],
        [("Oui.", "ID[Oui.]"), ("Bonjour.", "ID[Bonjour.]"), ("Oui.", "ID[Oui.]")],
    )


def test_cache_avoids_second_call():
    cache = TranslationCache(":memory:")
    translate_cues(CUES, FakeTranslator(), cache)
    again = FakeTranslator()
    result = translate_cues(CUES, again, cache)
    assert again.calls == []
    assert result[3].text == "ID[Merci.]"


def _fake_client(reply: dict, stop_reason="end_turn"):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            stop_reason=stop_reason,
            stop_details=None,
            content=[SimpleNamespace(type="text", text=json.dumps(reply))],
        )

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    return client, calls


def test_claude_translator_request_and_parsing():
    reply = {"translations": [{"id": 1, "text": "Terima kasih."}, {"id": 0, "text": "Halo."}]}
    client, calls = _fake_client(reply)
    translator = ClaudeTranslator(client=client)
    assert translator.translate_batch(["Bonjour.", "Merci."], [("Oui.", "Ya.")]) == [
        "Halo.",
        "Terima kasih.",
    ]
    request = calls[0]
    assert request["model"] == "claude-sonnet-5-5"
    assert request["output_config"]["format"]["type"] == "json_schema"
    assert "Indonesian" in request["system"]
    payload = json.loads(request["messages"][0]["content"])
    assert payload["cues"] == [{"id": 0, "text": "Bonjour."}, {"id": 1, "text": "Merci."}]
    assert payload["previous_cues"] == [{"original": "Oui.", "translation": "Ya."}]


def test_srt_roundtrip(tmp_path):
    path = save_subtitles([Cue(1500, 3000, "Halo,\napa kabar?")], tmp_path / "out.srt")
    content = path.read_text(encoding="utf-8")
    assert "00:00:01,500 --> 00:00:03,000" in content
    assert parse_subtitles(content) == [Cue(1500, 3000, "Halo,\napa kabar?")]


def test_refused_single_cue_is_kept_and_not_cached():
    calls = []

    def create(**kwargs):
        texts = [c["text"] for c in json.loads(kwargs["messages"][0]["content"])["cues"]]
        calls.append(texts)
        if "Je vais te tuer !" in texts:
            return SimpleNamespace(stop_reason="refusal", stop_details=None, content=[])
        reply = {"translations": [{"id": i, "text": t.upper()} for i, t in enumerate(texts)]}
        return SimpleNamespace(
            stop_reason="end_turn", stop_details=None,
            content=[SimpleNamespace(type="text", text=json.dumps(reply))],
        )

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    cache = TranslationCache(":memory:")
    cues = [Cue(0, 1, "Bonjour."), Cue(1, 2, "Je vais te tuer !"), Cue(2, 3, "Merci.")]
    result = translate_cues(cues, ClaudeTranslator(client=client), cache)
    # Le lot refusé est coupé en deux jusqu'à isoler la réplique, gardée en français.
    assert [c.text for c in result] == ["BONJOUR.", "Je vais te tuer !", "MERCI."]
    namespace = ClaudeTranslator(client=client).namespace
    assert set(cache.get_many(namespace, [c.text for c in cues])) == {"Bonjour.", "Merci."}


def _usage_client(input_tokens, output_tokens):
    reply = {"translations": [{"id": 0, "text": "Halo."}]}

    def create(**kwargs):
        return SimpleNamespace(
            stop_reason="end_turn", stop_details=None,
            usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
            content=[SimpleNamespace(type="text", text=json.dumps(reply))],
        )

    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))


def test_usage_and_cost_are_tracked():
    translator = ClaudeTranslator(model="claude-sonnet-5-5", client=_usage_client(1500, 2500))
    assert translator.usage_summary().startswith("aucune requête")
    translator.translate_batch(["Bonjour."], [])
    translator.translate_batch(["Bonjour."], [])
    assert (translator.calls, translator.input_tokens, translator.output_tokens) == (2, 3000, 5000)
    # 3000 x 2 $/M + 5000 x 10 $/M = 0,056 $
    assert translator.estimated_cost() == pytest.approx(0.056)
    assert translator.usage_summary() == (
        "coût estimé : 0,056 $, 2 requêtes, 3 000 tokens envoyés et 5 000 reçus"
    )


def test_cost_unknown_for_unlisted_model():
    translator = ClaudeTranslator(model="un-autre-modele", client=_usage_client(10, 10))
    translator.translate_batch(["Bonjour."], [])
    assert translator.estimated_cost() is None
    assert "coût" not in translator.usage_summary()
