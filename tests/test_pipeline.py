"""Сквозные тесты задач 4.8 и 4.9: конвейер на синтетическом мини-чате с поддельной моделью."""
import json
import pathlib
import re

import pytest

from src.schemas import Lesson, Report
from src.tracker import extract, pipeline

FIX = pathlib.Path(__file__).parent / "fixtures"
EXPECTED = json.loads((FIX / "mini_chat_expected.json").read_text(encoding="utf-8"))
NOT_A_DEADLINE = {"has_deadline": False, "discipline": None, "kind": None, "task": None,
                  "due_text": None, "action": None, "fuzzy": False, "confidence": 0.9}


class FakeModel:
    """Подменяет extract._chat: отвечает по эталону mini_chat_expected.json."""

    def __init__(self):
        self.calls: list[str] = []
        self.by_id = {d["msg_id"]: d["extract"] for d in EXPECTED["deadlines"]}

    def __call__(self, messages):
        msg_id = re.search(r"\[id=([^\]]+)\]", messages[-1]["content"]).group(1)
        self.calls.append(msg_id)
        return json.dumps(self.by_id.get(msg_id, NOT_A_DEADLINE), ensure_ascii=False)


@pytest.fixture
def fake(monkeypatch):
    model = FakeModel()
    monkeypatch.setattr(extract, "_chat", model)
    monkeypatch.setattr(extract, "_log", lambda *a, **k: None)
    return model


@pytest.fixture
def lessons(tdb):
    tdb.replace_lessons([
        Lesson(discipline="elektro", lesson_type="lecture", start="2026-10-29T08:30:00+03:00",
               end="2026-10-29T10:05:00+03:00"),
        Lesson(discipline="elektro", lesson_type="lab", start="2026-11-05T08:30:00+03:00",
               end="2026-11-05T10:05:00+03:00")])
    return tdb


def snapshot(db):
    """Итоговая база в виде, сравнимом с эталоном."""
    out = []
    for d in db.list_deadlines(status=None):
        out.append({"source_msg": d.source_msg, "task": d.task, "status": d.status,
                    "due_at": d.due_at, "fuzzy": d.fuzzy,
                    "files": [f.id for f in d.attachments],
                    "history": [[e.old_due, e.new_due, e.source_msg] for e in db.get_history(d.id)]})
    by_id = {d.id: d for d in db.list_deadlines(status=None)}
    pend = [{"reason": p.reason, "source_msg": p.candidate.source_msg,
             "matched_source": by_id[p.matched_id].source_msg if p.matched_id else None}
            for p in db.list_pending()]
    return out, pend


def test_end_to_end_matches_expected(lessons, fake):
    r1 = pipeline.process_new("elektro")
    r2 = pipeline.process_new("models")
    got, pend = snapshot(lessons)
    key = lambda x: x["source_msg"]
    assert sorted(got, key=key) == sorted(EXPECTED["state"]["deadlines"], key=key)
    assert sorted(pend, key=key) == sorted(EXPECTED["state"]["pending"], key=key)
    # отчёты по чатам
    assert r1.model_dump() == dict(processed=20, added=6, moved=1, cancelled=1, pending=2,
                                   skipped_prefilter=r1.skipped_prefilter, failed=0)
    assert r2.model_dump() == dict(processed=5, added=3, moved=0, cancelled=0, pending=1,
                                   skipped_prefilter=r2.skipped_prefilter, failed=0)


def test_prefilter_saves_model_calls(lessons, fake):
    rep = pipeline.process_new("elektro")
    assert rep.skipped_prefilter >= 8                       # шум и сообщения с файлами без срока
    assert len(fake.calls) == rep.processed - rep.skipped_prefilter
    for noise in ("elektro:1001", "elektro:1002", "elektro:1011", "elektro:1021", "elektro:1032"):
        assert noise not in fake.calls


def test_rerun_changes_nothing(lessons, fake):
    pipeline.process_new("elektro")
    before = snapshot(lessons)
    calls = len(fake.calls)
    rep = pipeline.process_new("elektro")
    assert rep == Report(processed=0, added=0, moved=0, cancelled=0, pending=0,
                         skipped_prefilter=0, failed=0)
    assert snapshot(lessons) == before and len(fake.calls) == calls


def test_files_precision_and_recall(lessons, fake):
    """Карточки заданий содержат ровно ожидаемые файлы (4.9, пункты а–з)."""
    pipeline.process_new("elektro")
    pipeline.process_new("models")
    by_src = {d.source_msg: d for d in lessons.list_deadlines(status=None)}
    lab2 = by_src["elektro:1010"]
    assert {f.id: f.bind for f in lab2.attachments} == {
        "elektro:1010:f1": "same_message", "elektro:1041:f1": "same_author_near"}
    assert {f.id: f.bind for f in by_src["elektro:1031"].attachments} == {
        "elektro:1032:f1": "reply_context"}
    all_ids = {f.id for d in by_src.values() for f in d.attachments}
    assert "elektro:1022:f1" not in all_ids                  # чужой файл в то же время
    assert "elektro:1023:f1" not in all_ids                  # файл через час


def test_pending_keeps_files_until_confirmed(lessons, fake, monkeypatch):
    """Кандидат в очереди хранит файлы внутри candidate_json и привязывает при подтверждении."""
    from src.tracker import attach
    from tests.conftest import make_file
    real = attach.collect_files

    def with_file(msg, chat_msgs):
        files = real(msg, chat_msgs)
        if msg.id == "elektro:1100":
            files.append(make_file("elektro:1100", 1, bind="same_message"))
        return files
    monkeypatch.setattr(attach, "collect_files", with_file)
    pipeline.process_new("elektro")
    (item,) = [p for p in lessons.list_pending() if p.candidate.source_msg == "elektro:1100"]
    assert [f.id for f in item.candidate.attachments] == ["elektro:1100:f1"]
    d = lessons.resolve_pending(item.id, accept=True)
    assert d.source_msg == "elektro:1100" and d.status == "active"
    assert [f.id for f in d.attachments] == ["elektro:1100:f1"]


def test_move_without_known_task_waits_in_queue(lessons, fake):
    pipeline.process_new("elektro")
    item = next(p for p in lessons.list_pending() if p.reason == "no_match_for_move")
    assert item.candidate.status == "pending" and item.matched_id is None
    assert item.source_text == "ДЗ 7 перенесли на пятницу"
    assert item.candidate.due_at == "2026-10-30T23:59:00+03:00"


def test_model_unavailable_leaves_messages_for_next_run(lessons, monkeypatch):
    def down(messages):
        raise extract.ModelUnavailable("Ollama недоступна")
    monkeypatch.setattr(extract, "_chat", down)
    monkeypatch.setattr(extract, "_log", lambda *a, **k: None)
    rep = pipeline.process_new("elektro")
    assert rep.failed == 1 and rep.added == 0
    # сообщения до первого, которому нужна модель, обработаны; остальные ждут
    assert len(lessons.processed_ids("elektro")) < 20
    monkeypatch.setattr(extract, "_chat", FakeModel())
    rep2 = pipeline.process_new("elektro")
    assert rep2.added == 6 and rep2.failed == 0


def test_garbage_json_is_logged_and_skipped(lessons, monkeypatch):
    logged = []
    monkeypatch.setattr(extract, "_chat", lambda messages: "это не json")
    monkeypatch.setattr(extract, "_log", lambda name, rec: logged.append((name, rec)))
    rep = pipeline.process_new("models")
    assert rep.failed >= 1 and rep.added == 0
    assert all(n == "extract_failures.jsonl" for n, _ in logged)
    assert lessons.processed_ids("models")                   # помечены обработанными, не зацикливаются
    assert pipeline.process_new("models").failed == 0


def test_unknown_discipline_is_logged_not_stored(lessons, monkeypatch):
    """Ключа дисциплины нет: в базу и в очередь не пишем (нельзя выдумывать ключ), лог и failed."""
    bad = dict(NOT_A_DEADLINE, has_deadline=True, discipline="философия", kind="hw",
               task="ДЗ 1", due_text="до пятницы", action="new", confidence=0.95)
    logged = []
    monkeypatch.setattr(extract, "_chat", lambda m: json.dumps(bad, ensure_ascii=False))
    monkeypatch.setattr(extract, "_log", lambda name, rec: logged.append((name, rec)))
    monkeypatch.setattr(pipeline.common, "load_chat",
                        lambda chat: _single_message("other", "Сдать ДЗ 1 до пятницы"))
    rep = pipeline.process_new("other")
    assert rep.failed == 1 and rep.added == 0 and rep.pending == 0
    assert lessons.list_deadlines(status=None) == [] and lessons.list_pending() == []
    assert "не определена дисциплина" in logged[-1][1]["error"]
    assert pipeline.process_new("other").processed == 0           # не зацикливается


def _single_message(chat, text):
    from src.schemas import Message
    return [Message(id=f"{chat}:1", chat=chat, ts="2026-10-20T10:00:00+03:00", author="STAROSTA",
                    role="starosta", text=text, src="m.html#message1")]


def test_out_of_order_old_message_does_not_overwrite(lessons, fake):
    """Свежее побеждает: старое сообщение, обработанное позже, срок не затирает."""
    from src.schemas import Message
    msgs = [
        Message(id="elektro:2", chat="elektro", ts="2026-10-25T10:00:00+03:00", author="STAROSTA",
                role="starosta", text="Лаб.9 перенесли на 5.11", src="m#2"),
        Message(id="elektro:1", chat="elektro", ts="2026-10-20T10:00:00+03:00", author="STAROSTA",
                role="starosta", text="Лаб.9 сдаём до 30.10", src="m#1")]
    fake.by_id = {
        "elektro:1": dict(NOT_A_DEADLINE, has_deadline=True, discipline="elektro", kind="lab",
                          task="Лаб.9", due_text="до 30.10", action="new"),
        "elektro:2": dict(NOT_A_DEADLINE, has_deadline=True, discipline="elektro", kind="lab",
                          task="Лаб.9", due_text="на 5.11", action="move")}
    # сначала в базу попадает новое (id 2), затем старое (id 1)
    from src.tracker import match, db as tdb_mod
    ts_of = {m.id: m.ts for m in msgs}.get
    from src.schemas import Deadline
    new = Deadline(discipline="elektro", kind="lab", task="Лаб.9", due_at="2026-11-05T23:59:00+03:00",
                   due_text="на 5.11", source_msg="elektro:2", confidence=0.9)
    old = Deadline(discipline="elektro", kind="lab", task="Лаб.9", due_at="2026-10-30T23:59:00+03:00",
                   due_text="до 30.10", source_msg="elektro:1", confidence=0.9)
    assert match.apply_candidate(new, "new", msgs[0].ts, "t", ts_of).kind == "added"
    out = match.apply_candidate(old, "move", msgs[1].ts, "t", ts_of)
    assert out.kind == "stale"
    (d,) = tdb_mod.list_deadlines()
    assert d.due_at == "2026-11-05T23:59:00+03:00" and tdb_mod.get_history(d.id) == []


def test_main_prints_report(lessons, fake, capsys):
    pipeline.main(["--chat", "models"])
    out = json.loads(capsys.readouterr().out)
    assert out["processed"] == 5 and out["added"] == 3 and out["failed"] == 0


def test_main_requires_chat():
    with pytest.raises(SystemExit):
        pipeline.main([])
