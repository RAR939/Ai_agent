"""Тесты задачи 4.5: извлечение моделью (вызов Ollama подменён)."""
import json
import types

import pytest

from src.schemas import DeadlineExtract, Message
from src.tracker import extract

GOOD = {"has_deadline": True, "discipline": "elektro", "kind": "lab", "task": "Лаб.2",
        "due_text": "до пятницы", "action": "new", "fuzzy": False, "confidence": 0.95}


def mk(text="Лаб.2 по электротехнике сдаём до пятницы", i=3, reply_to=None):
    return Message(id=f"elektro:{i}", chat="elektro", ts="2026-10-20T14:03:00+03:00",
                   author="STAROSTA", role="starosta", text=text, reply_to=reply_to, src="m#1")


@pytest.fixture
def calls(monkeypatch):
    """Подменяет _chat очередью ответов; возвращает список полученных запросов."""
    class Fake:
        def __init__(self):
            self.answers, self.requests, self.logs = [], [], []

        def __call__(self, messages):
            self.requests.append(messages)
            return self.answers.pop(0)
    fake = Fake()
    monkeypatch.setattr(extract, "_chat", fake)
    monkeypatch.setattr(extract, "_log", lambda name, rec: fake.logs.append((name, rec)))
    return fake


def test_good_json(tdb, calls):
    calls.answers = [json.dumps(GOOD)]
    got = extract.extract_deadline(mk())
    assert isinstance(got, DeadlineExtract) and got.task == "Лаб.2" and got.action == "new"
    assert len(calls.requests) == 1
    assert calls.logs[0][0] == "extract_calls.jsonl" and calls.logs[0][1]["msg_id"] == "elektro:3"


def test_call_is_saved_to_labels(tdb, calls):
    calls.answers = [json.dumps(GOOD)]
    extract.extract_deadline(mk())
    label = tdb.get_label("elektro:3")
    assert label["prompt_version"] == "extract_v1" and label["model_name"] == "qwen3:8b"
    assert json.loads(label["model_json"])["task"] == "Лаб.2"


def test_broken_json_retries_once_with_hint(tdb, calls):
    calls.answers = ["Конечно! Вот ответ:", json.dumps(GOOD)]
    got = extract.extract_deadline(mk())
    assert got is not None and len(calls.requests) == 2
    assert extract.RETRY_HINT in calls.requests[1][-1]["content"]
    assert calls.requests[1][-2] == {"role": "assistant", "content": "Конечно! Вот ответ:"}


def test_two_failures_are_logged_and_skipped(tdb, calls):
    calls.answers = ["не json", '{"has_deadline": "возможно"}']
    assert extract.extract_deadline(mk()) is None
    assert len(calls.requests) == 2
    name, rec = calls.logs[-1]
    assert name == "extract_failures.jsonl" and rec["msg_id"] == "elektro:3" and rec["error"]
    assert tdb.get_label("elektro:3") is None


def test_confidence_out_of_range_is_rejected(tdb, calls):
    calls.answers = [json.dumps(dict(GOOD, confidence=1.7))] * 2
    assert extract.extract_deadline(mk()) is None


def test_markdown_fence_and_extra_text_are_tolerated(tdb, calls):
    calls.answers = ["```json\n" + json.dumps(GOOD) + "\n```"]
    assert extract.extract_deadline(mk()) is not None
    calls.answers = ["Ответ: " + json.dumps(GOOD) + " Готово."]
    assert extract.extract_deadline(mk(i=4)) is not None


def test_not_a_deadline(tdb, calls):
    calls.answers = [json.dumps({"has_deadline": False, "confidence": 0.9})]
    got = extract.extract_deadline(mk("ахах"))
    assert got.has_deadline is False and got.task is None and got.fuzzy is False


def test_model_down_propagates(tdb, monkeypatch):
    def down(messages):
        raise extract.ModelUnavailable("нет связи")
    monkeypatch.setattr(extract, "_chat", down)
    with pytest.raises(extract.ModelUnavailable):
        extract.extract_deadline(mk())


def test_prompt_contains_context_and_reply(tdb):
    prev = [mk("привет", i=1), mk("как дела", i=2)]
    parent = mk("когда сдавать Лаб.2?", i=0)
    msgs = extract.build_messages(mk("до пятницы", reply_to=parent.id), prev, parent)
    assert msgs[0]["role"] == "system" and msgs[-1]["role"] == "user"
    user = msgs[-1]["content"]
    assert "[id=elektro:3]" in user and "привет" in user and "когда сдавать Лаб.2?" in user
    assert "STAROSTA (starosta)" in user and "2026-10-20 14:03" in user


def test_prompt_has_schema_rules_and_five_examples(tdb):
    prompt = extract.load_prompt()
    assert "elektro: Электротехника" in prompt and "{disciplines}" not in prompt
    assert "ДОСЛОВНО" in prompt and "Ничего не вычисляй" in prompt
    assert prompt.count('"has_deadline"') >= 6                    # поля + 6 примеров
    for action in ("new", "move", "cancel"):
        assert f'"action": "{action}"' in prompt


def test_prompt_example_jsons_are_valid(tdb):
    for line in extract.load_prompt().splitlines():
        if line.startswith('{"has_deadline"'):
            DeadlineExtract.model_validate_json(line)


def test_very_long_text_and_emoji(tdb, calls):
    calls.answers = [json.dumps(GOOD)]
    assert extract.extract_deadline(mk("сдаём 🔥 " * 2000)) is not None


def test_resolve_discipline(tdb):
    ex = DeadlineExtract(has_deadline=True, discipline="models", confidence=0.9)
    assert extract.resolve_discipline(ex, mk()) == "models"
    ex = DeadlineExtract(has_deadline=True, discipline="Электротехника", confidence=0.9)
    assert extract.resolve_discipline(ex, mk("текст")) == "elektro"
    ex = DeadlineExtract(has_deadline=True, discipline=None, confidence=0.9)
    assert extract.resolve_discipline(ex, mk("сдаём бд до пятницы")) == "models"
    assert extract.resolve_discipline(ex, mk("сдаём до пятницы")) == "elektro"       # чат = ключ
    other = mk("сдаём до пятницы").model_copy(update={"chat": "общий"})
    assert extract.resolve_discipline(ex, other) is None


# ---------- extract: вызов Ollama и лог ----------
def test_chat_passes_schema_and_disables_thinking(monkeypatch):
    from src import llm
    seen = {}

    def fake_chat(**kw):
        seen.update(kw)
        return types.SimpleNamespace(message=types.SimpleNamespace(content='{"a": 1}'))
    monkeypatch.setattr(llm, "chat", fake_chat)
    assert extract._chat([{"role": "user", "content": "x"}]) == '{"a": 1}'
    assert seen["model"] == "qwen3:8b" and seen["think"] is False
    assert seen["format"] == DeadlineExtract.model_json_schema()
    assert seen["options"] == {"temperature": 0}


def test_chat_wraps_connection_errors(monkeypatch):
    from src import llm

    def boom(**kw):
        raise ConnectionError("нет связи")
    monkeypatch.setattr(llm, "chat", boom)
    with pytest.raises(extract.ModelUnavailable):
        extract._chat([])


def test_log_appends_jsonl(set_cfg, tmp_path):
    set_cfg({"paths": {"logs": str(tmp_path)}})
    extract._log("t.jsonl", {"a": "б"})
    extract._log("t.jsonl", {"a": 2})
    lines = (tmp_path / "t.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(x) for x in lines] == [{"a": "б"}, {"a": 2}]


def test_log_never_raises(set_cfg, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    set_cfg({"paths": {"logs": str(blocker / "sub")}})        # папку создать нельзя
    extract._log("t.jsonl", {"a": 1})
