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
    assert request["model"] == "claude-opus-5-5"
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
