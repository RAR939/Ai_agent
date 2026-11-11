import json
import pytest

from src.index import chunking, subject_classifier
from src.schemas import Message


def _message(n, text, reply_to=None):
    return Message(id=f"group:{n}", chat="group", ts=f"2026-09-07T10:{n:02d}:00+03:00",
                   author="Аня", role="student", text=text, reply_to=reply_to,
                   src=f"messages.html#message{n}")


CONFIG = {"retrieval": {"chunk_strategy": "window", "window_size": 10,
                        "window_step": 5, "max_chunk_chars": 1800,
                        "subject_model_enabled": True,
                        "subject_model_batch_size": 20,
                        "subject_model_min_confidence": 0.75},
          "models": {"llm": "test-model"},
          "disciplines": {"elektro": {"name": "Электротехника"},
                          "algo": {"name": "Алгоритмы"},
                          "models": {"name": "Модели данных"}}}


def test_model_labels_implicit_subject_but_rejects_uncertain_and_social(monkeypatch):
    messages = [_message(1, "По алгоритмам ДЗ1: AVL-дерево"),
                _message(2, "А повороты обязательно показывать?"),
                _message(3, "Можно", "group:1"),
                _message(4, "Кто идёт за кофе?"),
                _message(5, "Схему таблиц можно приложить отдельно?")]
    calls = []

    def fake_chat(**kwargs):
        payload = json.loads(kwargs["messages"][1]["content"])
        calls.append(payload)
        labels = []
        for row in payload:
            key, score = {"group:2": ("algo", 0.92), "group:4": (None, 0.99),
                          "group:5": ("models", 0.55)}[row["id"]]
            labels.append({"id": row["id"], "discipline": key, "confidence": score})
        return {"message": {"content": json.dumps({"labels": labels})}}

    monkeypatch.setattr(subject_classifier, "_chat", fake_chat)
    monkeypatch.setattr(chunking, "cfg", lambda: CONFIG)
    chunks = chunking.chunk_messages(messages)
    assert len(calls) == 1
    assert {row["id"] for row in calls[0]} == {"group:2", "group:4", "group:5"}
    assert next(c for c in chunks if "group:2" in c.msg_ids).discipline == "algo"
    assert next(c for c in chunks if "group:3" in c.msg_ids).discipline == "algo"
    assert next(c for c in chunks if "group:4" in c.msg_ids).discipline is None
    assert next(c for c in chunks if "group:5" in c.msg_ids).discipline is None


def test_model_failure_preserves_rule_based_labels(monkeypatch):
    messages = [_message(1, "По алгоритмам ДЗ1"), _message(2, "Что там с деревом?")]
    monkeypatch.setattr(chunking, "cfg", lambda: CONFIG)
    monkeypatch.setattr(subject_classifier, "_chat", lambda **kw: (_ for _ in ()).throw(OSError("offline")))
    with pytest.warns(RuntimeWarning, match="Subject classification unavailable"):
        chunks = chunking.chunk_messages(messages)
    assert next(c for c in chunks if "group:1" in c.msg_ids).discipline == "algo"
    assert next(c for c in chunks if "group:2" in c.msg_ids).discipline is None
