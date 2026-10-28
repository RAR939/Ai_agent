"""Тесты задач 4.1 и 4.9 (функции файлов и карточка): база в памяти."""
import pytest

from src.schemas import DeadlineCard
from tests.conftest import make_deadline, make_file


def test_init_is_idempotent(tdb):
    tdb.init_db()
    tdb.init_db()
    assert tdb.list_deadlines() == []


def test_add_and_get(tdb):
    new_id = tdb.add_deadline(make_deadline())
    d = tdb.get_deadline(new_id)
    assert d.id == new_id and d.task == "Лаб.2" and d.status == "active"
    assert d.updated_at is not None and d.attachments == []
    assert tdb.get_deadline(999) is None


def test_foreign_keys_are_enforced(tdb):
    with pytest.raises(Exception):
        with tdb._connect() as conn:
            conn.execute("INSERT INTO deadline_history(deadline_id, old_due, new_due, "
                         "source_msg, changed_at) VALUES (404, NULL, NULL, 'x', 'y')")


def test_fuzzy_deadline_has_no_date(tdb):
    i = tdb.add_deadline(make_deadline(due_at=None, fuzzy=True, due_text="на днях"))
    d = tdb.get_deadline(i)
    assert d.due_at is None and d.fuzzy is True


def test_list_filters(tdb):
    tdb.add_deadline(make_deadline(task="Лаб.1", due_at="2026-10-20T23:59:00+03:00"))
    tdb.add_deadline(make_deadline(task="Лаб.2", due_at="2026-10-25T23:59:00+03:00"))
    tdb.add_deadline(make_deadline(task="ЛР1", discipline="models",
                                   due_at="2026-10-22T10:00:00+03:00"))
    tdb.add_deadline(make_deadline(task="Лаб.3", due_at=None, fuzzy=True))
    assert [d.task for d in tdb.list_deadlines()] == ["Лаб.1", "ЛР1", "Лаб.2", "Лаб.3"]
    assert [d.task for d in tdb.list_deadlines(discipline="models")] == ["ЛР1"]
    # границы включены, дата без времени = целые сутки; размытые не попадают
    got = tdb.list_deadlines(date_from="2026-10-20", date_to="2026-10-22")
    assert [d.task for d in got] == ["Лаб.1", "ЛР1"]
    assert tdb.list_deadlines(date_from="2026-12-01") == []


def test_list_status_filter(tdb):
    a = tdb.add_deadline(make_deadline(task="Лаб.1"))
    tdb.add_deadline(make_deadline(task="Лаб.2"))
    tdb.set_status(a, "cancelled")
    assert [d.task for d in tdb.list_deadlines()] == ["Лаб.2"]
    assert [d.task for d in tdb.list_deadlines(status="cancelled")] == ["Лаб.1"]
    assert len(tdb.list_deadlines(status=None)) == 2


def test_set_status_validation(tdb):
    i = tdb.add_deadline(make_deadline())
    tdb.set_status(i, "done")
    assert tdb.get_deadline(i).status == "done"
    with pytest.raises(ValueError):
        tdb.set_status(i, "weird")
    with pytest.raises(LookupError):
        tdb.set_status(404, "done")


def test_move_writes_history(tdb):
    i = tdb.add_deadline(make_deadline())
    tdb.update_due(i, "2026-10-30T23:59:00+03:00", "elektro:40")
    d = tdb.get_deadline(i)
    assert d.due_at == "2026-10-30T23:59:00+03:00"
    (ev,) = tdb.get_history(i)
    assert ev.old_due == "2026-10-23T23:59:00+03:00"
    assert ev.new_due == "2026-10-30T23:59:00+03:00"
    assert ev.source_msg == "elektro:40" and ev.deadline_id == i


def test_second_move_keeps_chain(tdb):
    i = tdb.add_deadline(make_deadline())
    tdb.update_due(i, "2026-10-30T23:59:00+03:00", "elektro:40")
    tdb.update_due(i, "2026-11-06T23:59:00+03:00", "elektro:55")
    h = tdb.get_history(i)
    assert [(e.old_due[:10], e.new_due[:10]) for e in h] == [
        ("2026-10-23", "2026-10-30"), ("2026-10-30", "2026-11-06")]
    assert h[0].id < h[1].id


def test_move_to_same_due_is_noop(tdb):
    i = tdb.add_deadline(make_deadline())
    tdb.update_due(i, "2026-10-23T23:59:00+03:00", "elektro:41")
    assert tdb.get_history(i) == []


def test_move_to_none_makes_fuzzy(tdb):
    i = tdb.add_deadline(make_deadline())
    tdb.update_due(i, None, "elektro:41")
    d = tdb.get_deadline(i)
    assert d.due_at is None and d.fuzzy is True
    assert tdb.get_history(i)[0].new_due is None


def test_move_rejects_bad_time_and_unknown_id(tdb):
    i = tdb.add_deadline(make_deadline())
    with pytest.raises(ValueError):
        tdb.update_due(i, "2026-10-30T23:59:00", "x")      # без пояса
    with pytest.raises(LookupError):
        tdb.update_due(404, "2026-10-30T23:59:00+03:00", "x")
    assert tdb.get_history(i) == []


def test_pending_roundtrip_accept_new(tdb):
    cand = make_deadline(status="pending", confidence=0.4)
    pid = tdb.add_pending(cand, None, "low_confidence", "Сдать лабу до пятницы")
    (item,) = tdb.list_pending()
    assert item.id == pid and item.reason == "low_confidence"
    assert item.candidate.confidence == 0.4 and item.source_text == "Сдать лабу до пятницы"
    d = tdb.resolve_pending(pid, accept=True)
    assert d.status == "active" and d.id is not None
    assert tdb.list_pending() == []
    assert tdb.get_deadline(d.id).task == "Лаб.2"


def test_pending_reject(tdb):
    pid = tdb.add_pending(make_deadline(), None, "no_match_for_move", "текст")
    assert tdb.resolve_pending(pid, accept=False) is None
    assert tdb.list_pending() == [] and tdb.list_deadlines() == []


def test_pending_accept_updates_matched(tdb):
    i = tdb.add_deadline(make_deadline())
    cand = make_deadline(due_at="2026-11-05T23:59:00+03:00", due_text="на 5 ноября",
                         source_msg="elektro:60", confidence=0.5)
    pid = tdb.add_pending(cand, i, "low_confidence", "перенесли на 5 ноября")
    d = tdb.resolve_pending(pid, accept=True)
    assert d.id == i and d.due_at == "2026-11-05T23:59:00+03:00"
    assert d.due_text == "на 5 ноября"
    assert len(tdb.list_deadlines()) == 1
    assert tdb.get_history(i)[0].source_msg == "elektro:60"


def test_pending_accept_cancel_candidate(tdb):
    i = tdb.add_deadline(make_deadline())
    pid = tdb.add_pending(make_deadline(status="cancelled"), i, "low_confidence", "отмена")
    assert tdb.resolve_pending(pid, True).status == "cancelled"


def test_pending_unknown_id_and_bad_reason(tdb):
    assert tdb.resolve_pending(404, True) is None
    with pytest.raises(ValueError):
        tdb.add_pending(make_deadline(), None, "because", "x")


def test_processed_ids_by_chat(tdb):
    tdb.mark_processed("elektro:1", False)
    tdb.mark_processed("elektro:2", True)
    tdb.mark_processed("elektro2:1", True)        # чат с похожим префиксом не мешает
    tdb.mark_processed("models:7", False)
    assert tdb.processed_ids("elektro") == {"elektro:1", "elektro:2"}
    assert tdb.deadline_msg_ids("elektro") == {"elektro:2"}
    assert tdb.processed_ids("пусто") == set()
    tdb.mark_processed("elektro:1", True)          # повтор не падает
    assert tdb.deadline_msg_ids("elektro") == {"elektro:1", "elektro:2"}


def test_labels_keep_human_json(tdb):
    tdb.save_label("elektro:1", '{"a": 1}', "extract_v1", "qwen3:8b")
    with tdb._connect() as conn:
        conn.execute("UPDATE labels SET human_json = 'H' WHERE msg_id = 'elektro:1'")
    tdb.save_label("elektro:1", '{"a": 2}', "extract_v1", "qwen3:8b")
    lab = tdb.get_label("elektro:1")
    assert lab["model_json"] == '{"a": 2}' and lab["human_json"] == "H"
    assert tdb.get_label("нет") is None


# ---------- файлы и карточка (4.9) ----------
def test_attach_files_idempotent(tdb):
    i = tdb.add_deadline(make_deadline())
    f = make_file("elektro:10")
    tdb.attach_files(i, [f], "same_message")
    tdb.attach_files(i, [f], "same_message")
    tdb.attach_files(i, [f], "reply_context")          # повтор с другим bind ничего не меняет
    files = tdb.list_files(i)
    assert [x.id for x in files] == ["elektro:10:f1"]
    assert files[0].bind == "same_message"
    assert tdb.get_deadline(i).attachments[0].id == "elektro:10:f1"


def test_attach_files_validation(tdb):
    i = tdb.add_deadline(make_deadline())
    with pytest.raises(ValueError):
        tdb.attach_files(i, [make_file()], "by_name")
    with pytest.raises(LookupError):
        tdb.attach_files(404, [make_file()], "same_message")
    tdb.attach_files(i, [], "same_message")             # пустой список допустим
    assert tdb.list_files(i) == []


def test_file_shared_by_two_deadlines(tdb):
    a = tdb.add_deadline(make_deadline(task="Лаб.1"))
    b = tdb.add_deadline(make_deadline(task="Лаб.2"))
    f = make_file("elektro:5")
    tdb.attach_files(a, [f], "same_message")
    tdb.attach_files(b, [f], "reply_context")
    assert tdb.list_files(a)[0].bind == "same_message"
    assert tdb.list_files(b)[0].bind == "reply_context"


def test_add_deadline_with_attachments(tdb):
    i = tdb.add_deadline(make_deadline(attachments=[make_file("elektro:10", bind="same_message"),
                                                    make_file("elektro:11", bind="reply_context")]))
    assert [(f.id, f.bind) for f in tdb.list_files(i)] == [
        ("elektro:10:f1", "same_message"), ("elektro:11:f1", "reply_context")]


def test_get_card(tdb):
    i = tdb.add_deadline(make_deadline())
    tdb.attach_files(i, [make_file("elektro:10")], "same_message")
    tdb.update_due(i, "2026-10-30T23:59:00+03:00", "elektro:40")
    card = tdb.get_card(i)
    assert isinstance(card, DeadlineCard)
    assert card.deadline.attachments[0].id == "elektro:10:f1"
    assert len(card.history) == 1
    assert isinstance(card.discussion, list)
    with pytest.raises(LookupError):
        tdb.get_card(404)


def test_lessons_replace_and_query(tdb):
    from src.schemas import Lesson
    ls = [Lesson(discipline="elektro", lesson_type="lab", start=f"2026-10-{d}T10:00:00+03:00",
                 end=f"2026-10-{d}T11:30:00+03:00") for d in (20, 22, 27)]
    assert tdb.replace_lessons(ls) == 0
    assert tdb.replace_lessons(ls[:2]) == 3                  # старые заменены, не удвоены
    assert tdb.count_lessons() == 2
    got = tdb.query_lessons(after="2026-10-20T10:00:00+03:00")
    assert [x.start[:10] for x in got] == ["2026-10-22"]


def test_reminder_flag(tdb):
    i = tdb.add_deadline(make_deadline())
    assert not tdb.is_reminded(i, "2026-10-23T23:59:00+03:00")
    tdb.mark_reminded(i, "2026-10-23T23:59:00+03:00")
    tdb.mark_reminded(i, "2026-10-23T23:59:00+03:00")
    assert tdb.is_reminded(i, "2026-10-23T23:59:00+03:00")
    assert not tdb.is_reminded(i, "2026-10-30T23:59:00+03:00")


def test_file_database_persists(tmp_path):
    from src.tracker import db
    db.set_db_path(str(tmp_path / "sub" / "t.db"))
    try:
        i = db.add_deadline(make_deadline())
        assert db.get_deadline(i).task == "Лаб.2"
        assert (tmp_path / "sub" / "t.db").exists()
    finally:
        db.set_db_path(None)
