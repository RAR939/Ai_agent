"""Инструменты MCP-сервера на настоящих модулях ролей 3 и 4 (поиск и модель заменены подставными)."""
import json
import sys
from datetime import datetime

import pytest

from src import _fixture_data as fx
from src import mcp_server
from src.schemas import Lesson
from src.tracker import common, db, extract

from tests.conftest import make_deadline, make_file

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=common.MSK)


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    monkeypatch.setattr(common, "now", lambda: NOW)


def call(fn, **kw):
    return json.loads(fn(**kw))


# ---------- search_messages ----------
def test_search_passes_filters_and_period(monkeypatch):
    seen = {}

    def fake(**kw):
        seen.update(kw)
        return list(fx.hits())[:2]
    monkeypatch.setattr(mcp_server, "_search_hits", fake)
    res = call(mcp_server.search_messages, query="лаб2", discipline="elektro", period_days=10, role="starosta")
    assert [h["chunk_id"] for h in res] == ["elektro:1010-1011", "elektro:1040-1041"]
    assert seen == {"query": "лаб2", "discipline": "elektro", "date_from": "2026-10-19",
                    "role": "starosta", "top_k": 5}


def test_search_errors(monkeypatch):
    monkeypatch.setattr(mcp_server, "_search_hits", lambda **kw: [])
    assert "Пустой поисковый запрос" in call(mcp_server.search_messages, query="  ")["error"]
    assert "Дисциплина не найдена" in call(mcp_server.search_messages, query="х", discipline="math")["error"]
    assert call(mcp_server.search_messages, query="ничего") == []

    def boom(**kw):
        raise RuntimeError("индекс не построен")
    monkeypatch.setattr(mcp_server, "_search_hits", boom)
    assert call(mcp_server.search_messages, query="х") == {"error": "Ошибка поиска: индекс не построен"}


# ---------- read_new_messages ----------
def test_read_new_messages_skips_processed(tdb):
    allm = call(mcp_server.read_new_messages, chat="elektro")
    assert len(allm) == 20 and all(m["chat"] == "elektro" for m in allm)
    tdb.mark_processed("elektro:1001", False)
    assert "elektro:1001" not in [m["id"] for m in call(mcp_server.read_new_messages, chat="elektro")]
    late = call(mcp_server.read_new_messages, chat="elektro", since="2026-10-28T00:00:00+03:00")
    assert [m["id"] for m in late] == ["elektro:1090", "elektro:1100", "elektro:1110"]
    assert call(mcp_server.read_new_messages, chat="нет-такого") == []


def test_read_new_messages_limit(tdb):
    assert len(call(mcp_server.read_new_messages, chat="algo")) == 30          # в чате 31 сообщение


# ---------- list_deadlines ----------
def test_list_deadlines_window_and_fuzzy(tdb):
    tdb.add_deadline(make_deadline(task="Лаб.2", due_at="2026-10-30T23:59:00+03:00"))       # в окне
    tdb.add_deadline(make_deadline(task="Лаб.3", due_at="2026-12-01T23:59:00+03:00"))       # вне окна
    tdb.add_deadline(make_deadline(task="Лаб.4", due_at="2026-10-20T23:59:00+03:00"))       # просрочено
    tdb.add_deadline(make_deadline(task="Лаб.5", due_at=None, due_text="на днях", fuzzy=True))
    tasks = [d["task"] for d in call(mcp_server.list_deadlines, days_ahead=14)]
    assert tasks == ["Лаб.2", "Лаб.5"]                                          # размытые показываются всегда
    assert [d["task"] for d in call(mcp_server.list_deadlines, days_ahead=60)] == ["Лаб.2", "Лаб.3", "Лаб.5"]
    assert call(mcp_server.list_deadlines, discipline="models") == []
    assert "Дисциплина не найдена" in call(mcp_server.list_deadlines, discipline="math")["error"]


# ---------- add_deadline ----------
def test_add_deadline_new(tdb):
    res = call(mcp_server.add_deadline, discipline="elektro", task="Лаб.7", due_text="до 12 ноября",
               source_msg="elektro:1080")
    assert res["task"] == "Лаб.7" and res["kind"] == "lab" and res["status"] == "active"
    assert res["due_at"] == "2026-11-12T23:59:00+03:00" and res["id"]
    assert tdb.get_deadline(res["id"]).source_msg == "elektro:1080"


def test_add_deadline_same_again_is_noop(tdb):
    args = dict(discipline="elektro", task="Лаб.7", due_text="до 12 ноября", source_msg="elektro:1080")
    first, second = call(mcp_server.add_deadline, **args), call(mcp_server.add_deadline, **args)
    assert first["id"] == second["id"] and tdb.count_deadlines() == 1


def test_add_deadline_goes_to_queue_when_unsure(tdb, set_cfg):
    set_cfg({"tracker": {"confidence_threshold": 0.95}})
    res = call(mcp_server.add_deadline, discipline="elektro", task="Лаб.7", due_text="до 12 ноября",
               source_msg="elektro:1080")
    assert res["reason"] == "low_confidence" and res["candidate"]["task"] == "Лаб.7"
    assert [p.id for p in tdb.list_pending()] == [res["id"]] and tdb.count_deadlines() == 0


def test_add_deadline_errors(tdb):
    bad = call(mcp_server.add_deadline, discipline="elektro", task="Лаб.7", due_text="завтра", source_msg="elektro:0")
    assert "Сообщение не найдено" in bad["error"]
    assert "Дисциплина не найдена" in call(mcp_server.add_deadline, discipline="math", task="Лаб.7",
                                           due_text="завтра", source_msg="elektro:1080")["error"]


# ---------- update_deadline ----------
def test_update_deadline_writes_history(tdb):
    added = call(mcp_server.add_deadline, discipline="elektro", task="Лаб.2", due_text="до пятницы",
                 source_msg="elektro:1010")
    res = call(mcp_server.update_deadline, id=added["id"], new_due_text="на 30.10", source_msg="elektro:1040")
    assert res["id"] == added["id"] and res["due_at"] == "2026-10-30T23:59:00+03:00"
    (event,) = tdb.get_history(added["id"])
    assert (event.old_due, event.new_due, event.source_msg) == (
        "2026-10-23T23:59:00+03:00", "2026-10-30T23:59:00+03:00", "elektro:1040")


def test_update_deadline_unclear_date_goes_to_queue(tdb):
    added = call(mcp_server.add_deadline, discipline="elektro", task="Лаб.2", due_text="до пятницы",
                 source_msg="elektro:1010")
    res = call(mcp_server.update_deadline, id=added["id"], new_due_text="потом скажу", source_msg="elektro:1040")
    assert res["reason"] == "low_confidence"
    assert tdb.get_deadline(added["id"]).due_at == "2026-10-23T23:59:00+03:00"      # срок не тронут


def test_update_deadline_errors(tdb):
    assert "Дедлайн не найден" in call(mcp_server.update_deadline, id=999, new_due_text="завтра",
                                       source_msg="elektro:1040")["error"]
    added = call(mcp_server.add_deadline, discipline="elektro", task="Лаб.2", due_text="до пятницы",
                 source_msg="elektro:1010")
    assert "Сообщение не найдено" in call(mcp_server.update_deadline, id=added["id"], new_due_text="завтра",
                                          source_msg="elektro:0")["error"]


# ---------- расписание ----------
def test_get_schedule(tdb):
    tdb.replace_lessons([
        Lesson(discipline="elektro", lesson_type="lecture", start="2026-10-29T08:30:00+03:00",
               end="2026-10-29T10:05:00+03:00"),
        Lesson(discipline="models", lesson_type="seminar", start="2026-10-30T10:15:00+03:00",
               end="2026-10-30T11:50:00+03:00")])
    assert [x["discipline"] for x in call(mcp_server.get_schedule, date_from="2026-10-29")] == ["elektro"]
    both = call(mcp_server.get_schedule, date_from="2026-10-29", date_to="2026-10-30")
    assert [x["discipline"] for x in both] == ["elektro", "models"]
    assert [x["discipline"] for x in call(mcp_server.get_schedule, date_from="2026-10-29", date_to="2026-10-30",
                                          discipline="models")] == ["models"]
    assert call(mcp_server.get_schedule, date_from="2027-01-01") == []


def test_load_schedule(tdb, tmp_path):
    ics = tmp_path / "s.ics"
    ics.write_text("BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//t//\nBEGIN:VEVENT\nUID:1@t\n"
                   "DTSTART;TZID=Europe/Moscow:20261103T103000\nDTEND;TZID=Europe/Moscow:20261103T120000\n"
                   "SUMMARY:Электротехника\nEND:VEVENT\nEND:VCALENDAR\n", encoding="utf-8")
    res = call(mcp_server.load_schedule, path=str(ics))
    assert res["ok"] and res["lessons"][0]["discipline"] == "elektro"
    assert call(mcp_server.get_schedule, date_from="2026-11-03")[0]["start"] == "2026-11-03T10:30:00+03:00"
    missing = call(mcp_server.load_schedule, path=str(tmp_path / "нет.ics"))
    assert "error" in missing or missing["ok"] is False


# ---------- файлы и конвейер ----------
def test_get_attachments(tdb):
    i = tdb.add_deadline(make_deadline(attachments=[make_file("elektro:1010", 1, bind="same_message")]))
    assert [f["id"] for f in call(mcp_server.get_attachments, deadline_id=i)] == ["elektro:1010:f1"]
    j = tdb.add_deadline(make_deadline(task="Лаб.9", source_msg="elektro:2"))
    assert call(mcp_server.get_attachments, deadline_id=j) == []
    assert "Дедлайн не найден" in call(mcp_server.get_attachments, deadline_id=999)["error"]


def test_process_new_messages(monkeypatch):
    from src.schemas import Report
    from src.tracker import pipeline
    rep = Report(processed=3, added=1, moved=0, cancelled=0, pending=0, skipped_prefilter=2, failed=0)
    monkeypatch.setattr(pipeline, "process_new", lambda chat: rep)
    assert call(mcp_server.process_new_messages, chat="elektro") == rep.model_dump()

    def down(chat):
        raise extract.ModelUnavailable("Ollama недоступна")
    monkeypatch.setattr(pipeline, "process_new", down)
    assert call(mcp_server.process_new_messages, chat="elektro") == {"error": "Ошибка обработки: Ollama недоступна"}


# ---------- вспомогательное ----------
@pytest.mark.parametrize("task,kind", [("Лаб.2", "lab"), ("ЛР 3", "lab"), ("ДЗ 1", "hw"), ("домашка", "hw"),
                                       ("Рубежка", "midterm"), ("Контрольная", "midterm"),
                                       ("Экзамен", "exam"), ("зачёт", "exam"), ("Курсовая", "other"), ("", "other")])
def test_guess_kind(task, kind):
    assert mcp_server._guess_kind(task) == kind


# ---------- настоящий сервер по stdio ----------
@pytest.mark.anyio
async def test_real_server_lists_nine_tools_and_returns_json_errors():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    params = StdioServerParameters(command=sys.executable, args=["-m", "src.mcp_server"], cwd=str(common.ROOT))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            names = {t.name for t in (await session.list_tools()).tools}
            assert names == {"search_messages", "read_new_messages", "list_deadlines", "add_deadline",
                             "update_deadline", "get_schedule", "load_schedule", "get_attachments",
                             "process_new_messages"}
            res = await session.call_tool("search_messages", {"query": "  "})
            assert json.loads(res.content[0].text)["error"].endswith("Пустой поисковый запрос")
