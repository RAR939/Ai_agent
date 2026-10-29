"""Тесты задачи 4.7: сопоставление, переносы, отмены, очередь подтверждений."""
import pytest

from src.tracker import match
from tests.conftest import make_deadline, make_file

T = {"m1": "2026-10-20T10:00:00+03:00", "m2": "2026-10-23T18:00:00+03:00",
     "m3": "2026-10-25T09:00:00+03:00"}


def ts_of(msg_id):
    return T.get(msg_id)


@pytest.mark.parametrize("task,expected", [
    ("Лаб.2", ("lab", 2)), ("Лаб. 2", ("lab", 2)), ("лабораторная 2", ("lab", 2)),
    ("ЛР2", ("lab", 2)), ("лабу №3", ("lab", 3)), ("Лабораторная работа № 4", ("lab", 4)),
    ("ДЗ 1", ("hw", 1)), ("домашка 2", ("hw", 2)), ("РК 1", ("midterm", 1)),
    ("Рубежка", ("midterm", None)), ("Экзамен", ("exam", None)),
    ("Курсовая работа этап 2", ("course", 2)), ("Отчёт", (None, None)),
])
def test_task_key(task, expected):
    assert match.task_key(task) == expected


def test_task_key_uses_kind_when_no_type_word():
    assert match.task_key("Отчёт 3", "lab") == ("lab", 3)
    assert match.task_key("Отчёт 3", "other") == (None, 3)


def test_mentioned_tasks():
    assert match.mentioned_tasks("сдаём Лаб.2 и ЛР3, а ДЗ 1 отменили") == {
        ("lab", 2), ("lab", 3), ("hw", 1)}
    assert match.mentioned_tasks("ничего") == set()


def seed(tdb, **kw):
    return tdb.add_deadline(make_deadline(source_msg="m1", **kw))


def cand(**kw):
    base = dict(due_at="2026-11-05T23:59:00+03:00", due_text="на 5 ноября", source_msg="m2",
                confidence=0.9)
    base.update(kw)
    return make_deadline(**base)


# ---------- поиск ----------
def test_find_match_variants_of_name(tdb):
    i = seed(tdb)
    for name in ("Лаб.2", "лабораторная 2", "ЛР2", "Лаб. 2"):
        assert match.find_match(cand(task=name)).id == i


def test_no_match_other_number_or_discipline(tdb):
    seed(tdb)
    assert match.find_match(cand(task="Лаб.3")) is None
    assert match.find_match(cand(task="Лаб.2", discipline="models")) is None


def test_inactive_deadlines_are_not_matched(tdb):
    i = seed(tdb)
    tdb.set_status(i, "cancelled")
    assert match.find_match(cand()) is None


def test_fuzzy_name_without_number(tdb):
    i = tdb.add_deadline(make_deadline(task="Курсовая работа", kind="other", source_msg="m1"))
    assert match.find_match(cand(task="курсовая работа", kind="other")).id == i
    assert match.find_match(cand(task="Презентация проекта", kind="other")) is None


def test_two_equal_candidates_are_ambiguous(tdb):
    a = seed(tdb, task="Курсовая этап 1", kind="other")
    b = seed(tdb, task="Курсовая этап 2", kind="other")
    found = match.find_candidates(cand(task="Курсовая", kind="other"))
    assert {d.id for d in found} == {a, b}
    assert match.find_match(cand(task="Курсовая", kind="other")) is None


# ---------- решения ----------
def test_new_without_match_is_inserted(tdb):
    out = match.apply_candidate(cand(), "new", T["m2"], "текст", ts_of)
    assert out.kind == "added" and tdb.get_deadline(out.deadline_id).status == "active"


def test_new_inserts_files(tdb):
    f = make_file("m2", bind="same_message")
    out = match.apply_candidate(cand(attachments=[f]), "new", T["m2"], "t", ts_of)
    assert [x.id for x in tdb.list_files(out.deadline_id)] == [f.id]


def test_move_updates_and_writes_history(tdb):
    i = seed(tdb)
    out = match.apply_candidate(cand(), "move", T["m2"], "t", ts_of)
    assert out.kind == "moved" and out.deadline_id == i
    d = tdb.get_deadline(i)
    assert d.due_at == "2026-11-05T23:59:00+03:00" and d.due_text == "на 5 ноября"
    assert [(e.old_due[:10], e.new_due[:10], e.source_msg) for e in tdb.get_history(i)] == [
        ("2026-10-23", "2026-11-05", "m2")]


def test_move_keeps_old_files_and_adds_new(tdb):
    i = seed(tdb)
    tdb.attach_files(i, [make_file("m1", 1)], "same_message")
    match.apply_candidate(cand(attachments=[make_file("m2", 1, bind="same_author_near")]),
                          "move", T["m2"], "t", ts_of)
    assert [f.id for f in tdb.list_files(i)] == ["m1:f1", "m2:f1"]


def test_move_without_match_goes_to_pending(tdb):
    out = match.apply_candidate(cand(task="ДЗ 9", kind="hw"), "move", T["m2"], "перенесли ДЗ 9", ts_of)
    assert out.kind == "pending" and tdb.list_deadlines() == []
    (p,) = tdb.list_pending()
    assert p.reason == "no_match_for_move" and p.matched_id is None
    assert p.source_text == "перенесли ДЗ 9" and p.candidate.status == "pending"


def test_cancel(tdb):
    i = seed(tdb)
    out = match.apply_candidate(cand(), "cancel", T["m2"], "t", ts_of)
    assert out.kind == "cancelled" and tdb.get_deadline(i).status == "cancelled"
    assert tdb.get_history(i) == []


def test_cancel_without_match_does_nothing(tdb):
    out = match.apply_candidate(cand(task="Лаб.9"), "cancel", T["m2"], "t", ts_of)
    assert out.kind == "noop" and tdb.list_pending() == [] and tdb.list_deadlines(status=None) == []


def test_low_confidence_goes_to_pending_even_with_match(tdb):
    i = seed(tdb)
    out = match.apply_candidate(cand(confidence=0.5), "move", T["m2"], "t", ts_of)
    assert out.kind == "pending"
    (p,) = tdb.list_pending()
    assert p.reason == "low_confidence" and p.matched_id == i
    assert tdb.get_deadline(i).due_at == "2026-10-23T23:59:00+03:00"      # не тронут


def test_confidence_threshold_comes_from_config(tdb, set_cfg):
    set_cfg({"tracker": {"confidence_threshold": 0.95}})
    out = match.apply_candidate(cand(confidence=0.9), "new", T["m2"], "t", ts_of)
    assert out.kind == "pending"


def test_two_similar_tasks_go_to_pending(tdb):
    a = seed(tdb, task="Курсовая этап 1", kind="other")
    seed(tdb, task="Курсовая этап 2", kind="other")
    out = match.apply_candidate(cand(task="Курсовая", kind="other"), "move", T["m2"], "t", ts_of)
    assert out.kind == "pending"
    (p,) = tdb.list_pending()
    assert p.reason == "ambiguous_match" and p.matched_id == a


def test_new_with_same_due_is_duplicate(tdb):
    i = seed(tdb)
    out = match.apply_candidate(cand(due_at="2026-10-23T23:59:00+03:00"), "new", T["m2"], "t", ts_of)
    assert out.kind == "noop" and out.deadline_id == i
    assert len(tdb.list_deadlines()) == 1 and tdb.get_history(i) == []


def test_new_with_other_due_is_treated_as_move(tdb):
    i = seed(tdb)
    out = match.apply_candidate(cand(), "new", T["m2"], "t", ts_of)
    assert out.kind == "moved" and len(tdb.list_deadlines()) == 1
    assert tdb.get_deadline(i).due_at == "2026-11-05T23:59:00+03:00"


def test_fresher_message_wins_over_older_one(tdb):
    """Сообщение m1 (старое) обработано после m2: срок от m2 не затирается."""
    i = tdb.add_deadline(make_deadline(source_msg="m2", due_at="2026-11-05T23:59:00+03:00"))
    out = match.apply_candidate(cand(source_msg="m1", due_at="2026-10-30T23:59:00+03:00"),
                                "move", T["m1"], "t", ts_of)
    assert out.kind == "stale"
    assert tdb.get_deadline(i).due_at == "2026-11-05T23:59:00+03:00" and tdb.get_history(i) == []


def test_old_cancel_does_not_cancel_after_newer_move(tdb):
    i = seed(tdb)
    match.apply_candidate(cand(source_msg="m3"), "move", T["m3"], "t", ts_of)   # перенос от m3 (25.10)
    out = match.apply_candidate(cand(source_msg="m2"), "cancel", T["m2"], "t", ts_of)   # отмена от 23.10
    assert out.kind == "stale" and tdb.get_deadline(i).status == "active"


def test_equal_timestamps_are_not_stale(tdb):
    i = seed(tdb)
    out = match.apply_candidate(cand(source_msg="mX"), "move", T["m1"], "t", ts_of)
    assert out.kind == "moved"


def test_no_timestamps_available_skips_freshness_check(tdb):
    seed(tdb)
    assert match.apply_candidate(cand(), "move", T["m1"], "t").kind == "moved"


def test_missing_action_is_new(tdb):
    assert match.apply_candidate(cand(), None, T["m2"], "t", ts_of).kind == "added"


def test_fuzzy_move_makes_due_none(tdb):
    i = seed(tdb)
    out = match.apply_candidate(cand(due_at=None, fuzzy=True, due_text="на днях"),
                                "move", T["m2"], "t", ts_of)
    d = tdb.get_deadline(i)
    assert out.kind == "moved" and d.due_at is None and d.fuzzy is True
