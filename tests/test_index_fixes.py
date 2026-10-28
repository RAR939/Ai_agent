"""Тесты правок роли 3: окно чанка через полночь и порог min_score без реранкера."""
import copy

import pytest

from src.index import answer as answer_mod
from src.index import chunking, common, discussion
from src.schemas import Deadline, Message, SearchHit

CFG = {
    "retrieval": {"chunk_strategy": "window", "window_size": 10, "window_step": 5,
                  "max_chunk_chars": 1800, "min_score": 0.3, "use_reranker": True},
    "models": {"llm": "test-llm", "temperature": 0.1},
}


def _cfg(use_reranker: bool) -> dict:
    c = copy.deepcopy(CFG)
    c["retrieval"]["use_reranker"] = use_reranker
    return c


def _msg(i, ts, text, role="student"):
    return Message(id=f"elektro:{i}", chat="elektro", ts=ts, author="A", role=role,
                   text=text, src=f"messages.html#message{i}")


def _hit(score):
    return SearchHit(chunk_id="elektro:1-2", chat="elektro", text="Лаб.2 до пятницы",
                     ts_from="2026-10-21T23:50:00+03:00", ts_to="2026-10-22T00:10:00+03:00",
                     roles=["starosta"], msg_ids=["elektro:1", "elektro:2"], score=score)


# ---------- чанкинг через полночь ----------
MIDNIGHT = [
    _msg(1, "2026-10-21T23:50:00+03:00", "Лаб.2 сдаём", "starosta"),
    _msg(2, "2026-10-22T00:10:00+03:00", "до пятницы?"),
    _msg(3, "2026-10-22T09:00:00+03:00", "Да, до пятницы 24.10", "starosta"),
]


def test_window_crosses_midnight(monkeypatch):
    monkeypatch.setattr(chunking, "cfg", lambda: _cfg(True))
    chunks = chunking.chunk_messages(MIDNIGHT)
    assert any({"elektro:1", "elektro:2"} <= set(c.msg_ids) for c in chunks)


def test_day_strategy_still_splits_by_day(monkeypatch):
    monkeypatch.setattr(chunking, "cfg", lambda: _cfg(True))
    chunks = chunking.chunk_messages(MIDNIGHT, strategy="day")
    assert [c.msg_ids for c in chunks] == [["elektro:1"], ["elektro:2", "elektro:3"]]


def test_window_empty_input(monkeypatch):
    monkeypatch.setattr(chunking, "cfg", lambda: _cfg(True))
    assert chunking.chunk_messages([]) == []


def test_window_other_chats_not_mixed(monkeypatch):
    monkeypatch.setattr(chunking, "cfg", lambda: _cfg(True))
    other = Message(id="models:1", chat="models", ts="2026-10-21T23:55:00+03:00", author="B",
                    role="student", text="привет", src="m.html#message1")
    chunks = chunking.chunk_messages(MIDNIGHT + [other])
    assert all(len({i.split(":")[0] for i in c.msg_ids}) == 1 for c in chunks)


# ---------- порог min_score ----------
@pytest.mark.parametrize("rerank,expected", [(True, 0.3), (False, 0.0)])
def test_min_score_depends_on_reranker(monkeypatch, rerank, expected):
    monkeypatch.setattr(common, "cfg", lambda: _cfg(rerank))
    assert common.min_score() == expected


def _patch_answer(monkeypatch, rerank, hits):
    import ollama
    monkeypatch.setattr(common, "cfg", lambda: _cfg(rerank))
    monkeypatch.setattr(answer_mod, "cfg", lambda: _cfg(rerank))
    monkeypatch.setattr(answer_mod, "search", lambda q, **f: hits)
    monkeypatch.setattr(ollama, "chat",
                        lambda **kw: {"message": {"content": "До пятницы [21.10, староста]"}})


def test_answer_without_reranker_not_refused_on_rrf_score(monkeypatch):
    _patch_answer(monkeypatch, False, [_hit(0.016)])
    res = answer_mod.answer("когда сдавать лабу 2?")
    assert not res.refused and res.sources


def test_answer_with_reranker_refuses_low_score(monkeypatch):
    _patch_answer(monkeypatch, True, [_hit(0.1)])
    assert answer_mod.answer("когда сдавать лабу 2?").refused


def test_answer_with_reranker_accepts_high_score(monkeypatch):
    _patch_answer(monkeypatch, True, [_hit(0.8)])
    assert not answer_mod.answer("когда сдавать лабу 2?").refused


def test_answer_no_hits_refused(monkeypatch):
    _patch_answer(monkeypatch, False, [])
    res = answer_mod.answer("что-то несуществующее")
    assert res.refused and res.sources == []


def test_discussion_without_reranker_keeps_rrf_hits(monkeypatch):
    monkeypatch.setattr(common, "cfg", lambda: _cfg(False))
    monkeypatch.setattr(discussion, "cfg", lambda: _cfg(False))
    monkeypatch.setattr(discussion, "messages", lambda chat: MIDNIGHT)
    hit = _hit(0.016).model_copy(update={"msg_ids": ["elektro:1", "elektro:2"]})
    monkeypatch.setattr(discussion, "search", lambda *a, **k: [hit])
    discussion._discussion.cache_clear()
    deadline = Deadline(discipline="elektro", kind="lab", task="Лаб.2", due_text="до пятницы",
                        source_msg="elektro:1", confidence=0.9)
    assert discussion.get_discussion(deadline) == [hit]
