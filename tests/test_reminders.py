"""Тесты задачи 4.10: выбор дедлайнов для напоминаний и защита от повторов."""
import runpy
import sys
import types
from datetime import datetime

from src.tracker import common, reminders
from tests.conftest import make_deadline

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=common.MSK)


def seed(tdb):
    tdb.add_deadline(make_deadline(task="Лаб.1", due_at="2026-10-22T18:00:00+03:00"))      # через 6 ч
    tdb.add_deadline(make_deadline(task="Лаб.2", due_at="2026-10-23T11:59:00+03:00"))      # через 24 ч - 1 мин
    tdb.add_deadline(make_deadline(task="Лаб.3", due_at="2026-10-23T12:01:00+03:00"))      # чуть дальше
    tdb.add_deadline(make_deadline(task="Лаб.4", due_at="2026-10-21T10:00:00+03:00"))      # уже прошёл
    tdb.add_deadline(make_deadline(task="Лаб.5", due_at=None, fuzzy=True))                 # без даты
    cancelled = tdb.add_deadline(make_deadline(task="Лаб.6", due_at="2026-10-22T20:00:00+03:00"))
    tdb.set_status(cancelled, "cancelled")


def test_due_soon_window(tdb):
    seed(tdb)
    assert [d.task for d in reminders.due_soon(24, NOW)] == ["Лаб.1", "Лаб.2"]
    assert [d.task for d in reminders.due_soon(7, NOW)] == ["Лаб.1"]
    assert reminders.due_soon(0, NOW) == []


def test_each_reminder_is_sent_once(tdb):
    seed(tdb)
    got = []
    first = reminders.send_due_reminders(24, NOW, notify=lambda t, m: got.append((t, m)))
    assert [d.task for d in first] == ["Лаб.1", "Лаб.2"] and len(got) == 2
    assert got[0][0] == "Дедлайн: Лаб.1" and "22.10 в 18:00" in got[0][1]
    assert reminders.send_due_reminders(24, NOW, notify=lambda t, m: got.append((t, m))) == []
    assert len(got) == 2


def test_moved_deadline_reminds_again(tdb):
    i = tdb.add_deadline(make_deadline(due_at="2026-10-22T18:00:00+03:00"))
    got = []
    reminders.send_due_reminders(24, NOW, notify=lambda t, m: got.append(m))
    tdb.update_due(i, "2026-10-23T09:00:00+03:00", "elektro:40")
    reminders.send_due_reminders(24, NOW, notify=lambda t, m: got.append(m))
    assert len(got) == 2 and "23.10 в 09:00" in got[1]


def test_default_hours_from_config(tdb, set_cfg):
    seed(tdb)
    set_cfg({"tracker": {"remind_hours": 7}})
    assert [d.task for d in reminders.send_due_reminders(now=NOW, notify=lambda *a: None)] == ["Лаб.1"]


def _fake_plyer(monkeypatch, notify):
    mod = types.ModuleType("plyer")
    mod.notification = types.SimpleNamespace(notify=notify)
    monkeypatch.setitem(sys.modules, "plyer", mod)


def test_os_notify_uses_plyer(monkeypatch):
    got = {}
    _fake_plyer(monkeypatch, lambda **kw: got.update(kw))
    reminders.os_notify("Заголовок", "Текст")
    assert got["title"] == "Заголовок" and got["message"] == "Текст"


def test_os_notify_falls_back_to_console(monkeypatch, capsys):
    def broken(**kw):
        raise NotImplementedError
    _fake_plyer(monkeypatch, broken)
    reminders.os_notify("Заголовок", "Текст")
    assert "Заголовок: Текст" in capsys.readouterr().out


def test_reminders_cli(tdb, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["src.tracker.reminders", "--hours", "1"])
    sys.modules.pop("src.tracker.reminders", None)
    runpy.run_module("src.tracker.reminders", run_name="__main__")
    assert "Отправлено напоминаний: 0" in capsys.readouterr().out
