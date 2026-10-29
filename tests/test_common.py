"""Тесты вспомогательных функций трекера: время, загрузка чата, мелкие функции db."""
from datetime import date, datetime

import pytest

from src.schemas import Lesson, Message
from src.tracker import common, db
from tests.conftest import make_deadline


# ---------- common ----------
def test_time_helpers():
    assert common.to_iso(datetime(2026, 10, 21, 14, 3)) == "2026-10-21T14:03:00+03:00"   # наивное = Москва
    utc = datetime.fromisoformat("2026-10-21T11:03:00+00:00")
    assert common.to_iso(utc) == "2026-10-21T14:03:00+03:00"
    assert common.parse_dt("2026-10-21").isoformat() == "2026-10-21T00:00:00+03:00"
    assert common.parse_date("2026-10-21T23:30:00+00:00") == date(2026, 10, 22)   # по Москве уже завтра
    assert common.end_of_day(date(2026, 10, 21)).isoformat() == "2026-10-21T23:59:00+03:00"
    assert common.now_iso().endswith("+03:00")


def test_load_chat_falls_back_to_fixture_sorted():
    msgs = common.load_chat("elektro")
    assert msgs and all(m.chat == "elektro" for m in msgs)
    assert [m.ts for m in msgs] == sorted(m.ts for m in msgs)
    assert common.load_chat("нет_такого_чата") == []


def test_load_chat_prefers_clean_file(tmp_path, monkeypatch):
    import src.ingest.store as store
    monkeypatch.delattr(store, "load_messages", raising=False)   # запасной путь: хранилища (или заглушки) нет
    (tmp_path / "data" / "clean").mkdir(parents=True)
    m = Message(id="x:2", chat="x", ts="2026-10-20T10:00:00+03:00", author="STAROSTA",
                role="starosta", text="b", src="s")
    m1 = m.model_copy(update={"id": "x:1", "text": "a", "ts": "2026-10-20T11:00:00+03:00"})
    (tmp_path / "data" / "clean" / "x.jsonl").write_text(
        "\n".join(x.model_dump_json() for x in (m1, m)) + "\n", encoding="utf-8")
    monkeypatch.setattr(common, "ROOT", tmp_path)
    assert [x.id for x in common.load_chat("x")] == ["x:2", "x:1"]          # по времени


def test_load_chat_uses_ingest_store_when_ready(monkeypatch):
    import src.ingest.store as store
    m = Message(id="x:1", chat="x", ts="2026-10-20T10:00:00+03:00", author="A", role="student",
                text="a", src="s")
    monkeypatch.setattr(store, "load_messages", lambda chat: [m], raising=False)
    assert common.load_chat("x") == [m]


# ---------- db: мелочи ----------
def test_count_deadlines_by_chat(tdb):
    tdb.add_deadline(make_deadline(source_msg="elektro:1"))
    tdb.add_deadline(make_deadline(source_msg="models:1"))
    assert tdb.count_deadlines() == 2 and tdb.count_deadlines("elektro") == 1
    assert tdb.count_deadlines("пусто") == 0


def test_update_deadline_text(tdb):
    i = tdb.add_deadline(make_deadline())
    tdb.update_deadline_text(i, "на 5 ноября", True, 0.5)
    d = tdb.get_deadline(i)
    assert (d.due_text, d.fuzzy, d.confidence) == ("на 5 ноября", True, 0.5)
    with pytest.raises(LookupError):
        tdb.update_deadline_text(404, "x", False, 1.0)


def test_query_lessons_filters(tdb):
    mk = lambda d, disc, kind: Lesson(discipline=disc, lesson_type=kind,
                                      start=f"2026-10-{d}T10:00:00+03:00", end=f"2026-10-{d}T11:30:00+03:00")
    tdb.replace_lessons([mk(20, "elektro", "lab"), mk(21, "models", "lecture"), mk(22, "elektro", "lecture")])
    assert len(tdb.query_lessons()) == 3
    assert [x.discipline for x in tdb.query_lessons(discipline="elektro")] == ["elektro", "elektro"]
    assert [x.start[8:10] for x in tdb.query_lessons(lesson_type="lecture")] == ["21", "22"]
    got = tdb.query_lessons(start_from="2026-10-21T00:00:00+03:00", start_to="2026-10-21T23:59:59+03:00")
    assert len(got) == 1 and got[0].discipline == "models"
    assert len(tdb.query_lessons(limit=1)) == 1


def test_set_db_path_none_uses_config_path(set_cfg, tmp_path):
    set_cfg({"paths": {"db": str(tmp_path / "from_cfg.db")}})
    db.set_db_path(None)
    db.init_db()
    assert (tmp_path / "from_cfg.db").exists()
