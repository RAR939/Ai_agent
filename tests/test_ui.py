"""Интерфейс: RealProvider на настоящих модулях, подписи, подсветка и сквозной запуск приложения."""
import pathlib

import pytest
from streamlit.testing.v1 import AppTest

from src import _fixture_data as fx
from src.schemas import (
    AgentResult, Deadline, DeadlineCard, DeadlineEvent, IndexStatus, Lesson, MessageContext, PendingItem,
    Report, ScheduleImport,
)
from src.tracker import db, pipeline
from ui import provider as provider_mod
from ui.common import dcolor, dlabel, dname, fmt_date
from ui.highlight import auto_spans, highlight
from ui.provider import MockProvider, RealProvider, make_provider

from tests.conftest import make_deadline

APP = str(pathlib.Path(__file__).resolve().parent.parent / "ui" / "app.py")


@pytest.fixture
def seeded(tdb):
    """База с двумя заданиями: Лаб.2 (с файлом, перенесена), Лаб.3 и записью в очереди."""
    files = [f.model_copy(update={"bind": "same_message"}) for f in fx.message_by_id()["elektro:1010"].attachments]
    lab2 = tdb.add_deadline(make_deadline(task="Лаб.2", source_msg="elektro:1010", attachments=files))
    tdb.update_due(lab2, "2026-10-30T23:59:00+03:00", "elektro:1040")
    tdb.add_deadline(make_deadline(task="Лаб.3", due_at="2026-11-06T23:59:00+03:00", source_msg="elektro:1020"))
    tdb.add_pending(make_deadline(task="ДЗ 7", source_msg="elektro:1090", status="pending", confidence=0.4),
                    None, "no_match_for_move", "ДЗ 7 перенесли на пятницу")
    tdb.replace_lessons([Lesson(discipline="elektro", lesson_type="lecture", start="2026-10-29T08:30:00+03:00",
                                end="2026-10-29T10:05:00+03:00")])
    return tdb


# ---------- подписи ----------
def test_labels_from_config_and_legacy():
    assert dname("elektro") == "Электротехника" and dcolor("elektro") == "#4c78a8"
    assert dname("electro") == "Электротехника" and dcolor("electro") == "#4F46E5"      # ключи старого макета
    assert dname("нет") == "нет" and dcolor("нет") == "#4F46E5"
    assert dlabel("elektro") == "⚡ Электротехника" and dlabel("нет") == "📘 нет"


def test_fmt_date():
    assert fmt_date("2026-10-30T23:59:00+03:00") == "30.10.2026"
    assert fmt_date("2026-11-12T10:00:00+03:00", with_time=True) == "12.11.2026 10:00"
    assert fmt_date("2026-11-12T23:59:00+03:00", with_time=True) == "12.11.2026"
    assert fmt_date(None) == "Срок не указан" and fmt_date("мусор") == "мусор"


# ---------- подсветка ----------
@pytest.mark.parametrize("text,found", [
    ("Лаб.2 по электротехнике сдаём до пятницы",
     [("Лаб.2", "task"), ("электротехнике", "discipline"), ("до пятницы", "deadline")]),
    ("Лаб.2 перенесли на 30.10", [("Лаб.2", "task"), ("на 30.10", "deadline")]),
    ("ДЗ 1 по моделям данных до 12 ноября в 10:00",
     [("ДЗ 1", "task"), ("моделям", "discipline"), ("до 12 ноября в 10:00", "deadline")]),
    ("ЭТ завтра, а эт неважно", [("ЭТ", "discipline"), ("завтра", "deadline")]),
    ("ахах всем привет 😂", []), ("", []),
])
def test_auto_spans(text, found):
    assert [(text[a:b], label) for a, b, label in sorted(auto_spans(text))] == found


def test_highlight_escapes_html():
    text = "<b>Лаб.2</b> до пятницы"
    html = highlight(text, auto_spans(text))
    assert "<b>" not in html and "&lt;b&gt;" in html and html.count("<mark") == 2


# ---------- RealProvider ----------
def test_real_provider_reads_tracker(seeded):
    p = RealProvider()
    all_d = p.list_deadlines()
    assert [d.task for d in all_d] == ["Лаб.2", "Лаб.3"] and all(isinstance(d, Deadline) for d in all_d)
    assert [d.task for d in p.list_deadlines(discipline="elektro", status="active")] == ["Лаб.2", "Лаб.3"]
    assert p.list_deadlines(discipline="models") == []
    hist = p.get_deadline_history(all_d[0].id)
    assert len(hist) == 1 and isinstance(hist[0], DeadlineEvent)
    (item,) = p.list_pending()
    assert isinstance(item, PendingItem) and item.reason == "no_match_for_move"
    assert p.resolve_pending(item.id, accept=False) is None and p.list_pending() == []
    card = p.get_card(all_d[0].id)
    assert isinstance(card, DeadlineCard) and [f.id for f in card.deadline.attachments] == ["elektro:1010:f1"]
    with pytest.raises(LookupError):
        p.get_card(999)
    assert [x.discipline for x in p.lessons_between("2026-10-29", "2026-10-29")] == ["elektro"]


def test_real_provider_messages_and_files(seeded):
    p = RealProvider()
    ctx = p.get_message_context("elektro:1031", before=1, after=1)
    assert isinstance(ctx, MessageContext) and ctx.target.id == "elektro:1031" and len(ctx.before) == 1
    f = fx.message_by_id()["elektro:1010"].attachments[0]
    assert pathlib.Path(p.file_abs_path(f)).is_file()


def test_real_provider_index_status_and_stats(seeded, monkeypatch):
    p = RealProvider()
    status = {s.chat: s for s in p.index_status()}
    assert set(status) == {"algo", "elektro", "models"} and isinstance(status["elektro"], IndexStatus)
    assert status["elektro"].messages == 20 and status["elektro"].deadlines == 2
    assert status["elektro"].last_processed is None and status["algo"].chunks == 0       # индекса нет
    db.mark_processed("elektro:1001", False)
    assert {s.chat: s for s in p.index_status()}["elektro"].last_processed.endswith("+03:00")
    stats = p.corpus_stats()
    assert stats == {"messages": 56, "deadlines": 2, "chunks": 0, "chats": 3}


def test_real_provider_all_chats(seeded, monkeypatch):
    calls = []

    def fake_process(chat):
        calls.append(chat)
        return Report(processed=2, added=1, moved=0, cancelled=0, pending=1, skipped_prefilter=1, failed=0)
    monkeypatch.setattr(pipeline, "process_new", fake_process)
    rep = RealProvider().process_new("all")
    assert calls == ["algo", "elektro", "models"] and (rep.processed, rep.added, rep.pending) == (6, 3, 3)
    assert RealProvider().process_new("elektro").processed == 2

    import src.index.build as build
    monkeypatch.setattr(build, "reindex", lambda chat: {"added": 1, "updated": 2, "total": 10})
    res = RealProvider().reindex("all")
    assert res == {"chat": "all", "status": "ok", "chunks": 10, "added": 3, "updated": 6}

    def broken(chat):
        raise RuntimeError("Ollama недоступна")
    monkeypatch.setattr(build, "reindex", broken)
    assert RealProvider().reindex("elektro") == {"chat": "elektro", "status": "error", "error": "Ollama недоступна"}


def test_real_provider_schedule(seeded, tmp_path):
    ics = tmp_path / "s.ics"
    ics.write_text("BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//t//\nBEGIN:VEVENT\nUID:1@t\n"
                   "DTSTART;TZID=Europe/Moscow:20261103T103000\nDTEND;TZID=Europe/Moscow:20261103T120000\n"
                   "SUMMARY:Электротехника\nEND:VEVENT\nEND:VCALENDAR\n", encoding="utf-8")
    p = RealProvider()
    preview = p.load_schedule(str(ics), dry_run=True)
    assert isinstance(preview, ScheduleImport) and preview.ok and p.lessons_between("2026-11-03", "2026-11-03") == []
    assert p.load_schedule(str(ics)).ok and len(p.lessons_between("2026-11-03", "2026-11-03")) == 1


def test_real_provider_ask(monkeypatch):
    async def fake(question, history):
        return AgentResult(text=f"ответ на {question}")
    import src.agent
    monkeypatch.setattr(src.agent, "run_agent", fake)
    assert RealProvider().ask("привет", []).text == "ответ на привет"

    async def down(question, history):
        raise ConnectionError("Ollama не запущена")
    monkeypatch.setattr(src.agent, "run_agent", down)
    assert "Не удалось получить ответ" in RealProvider().ask("привет", []).text


def test_make_provider_follows_config(monkeypatch):
    import src.config
    real = src.config.load_config()
    for flag, cls in ((True, MockProvider), (False, RealProvider)):
        cfg = {**real, "ui": {"use_mock": flag}}
        monkeypatch.setattr(src.config, "load_config", lambda cfg=cfg: cfg)
        assert type(make_provider()) is cls
    monkeypatch.setattr(src.config, "load_config", lambda: {**real, "ui": {}})
    assert type(make_provider()) is MockProvider                      # по умолчанию макет


# ---------- сквозной запуск приложения ----------
def _tab_text(at: AppTest) -> str:
    return " ".join(m.value for m in at.markdown) + " " + " ".join(c.value for c in at.caption)


def test_app_runs_with_mock_provider():
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception and len(at.tabs) == 4
    assert "Лабораторная №2" in _tab_text(at)


def test_app_runs_on_real_data_and_shows_card(seeded, monkeypatch):
    monkeypatch.setattr(provider_mod, "make_provider", lambda: RealProvider())
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    text = _tab_text(at)
    assert "ДЗ 7" in text and "Электротехника" in text                 # очередь и названия из конфига
    card = at.selectbox(key="card_deadline_id")
    assert card.value == next(d.id for d in db.list_deadlines() if d.task == "Лаб.2")
    assert "lab2_elektro.pdf" in text and "Срок не переносили" not in text     # материалы и история в карточке
    lab3 = next(d.id for d in db.list_deadlines() if d.task == "Лаб.3")
    at.selectbox(key="card_deadline_id").select(lab3).run()
    assert not at.exception and "Срок не переносили." in _tab_text(at)
    assert "К заданию не прикреплено файлов." in _tab_text(at)
