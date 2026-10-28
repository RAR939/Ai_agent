"""Роль 4 (задача 4.10, желательная): напоминания о близких дедлайнах.

due_soon(hours) выбирает активные дедлайны со сроком в ближайшие hours часов.
send_due_reminders() отправляет уведомление ОС по каждому такому дедлайну один раз
(флаг в таблице reminders привязан к сроку: после переноса напоминание уйдёт заново).

Запуск: python -m src.tracker.reminders [--hours 24]
Уведомления: plyer (Windows, macOS, Linux). Если уведомление недоступно, текст печатается.
"""
import argparse
from datetime import datetime, timedelta
from typing import Callable

from src import config
from src.schemas import Deadline
from src.tracker import common, db


def due_soon(hours: int, now: datetime | None = None) -> list[Deadline]:
    """Активные дедлайны со сроком от сейчас до now+hours (размытые без даты не входят)."""
    moment = now or common.now()
    return db.list_deadlines(date_from=common.to_iso(moment),
                             date_to=common.to_iso(moment + timedelta(hours=hours)),
                             status="active")


def reminder_text(d: Deadline) -> tuple[str, str]:
    when = common.parse_dt(d.due_at)
    return (f"Дедлайн: {d.task}",
            f"{config.discipline_name(d.discipline)}, срок {when:%d.%m в %H:%M} ({d.due_text})")


def os_notify(title: str, message: str) -> None:
    """Уведомление ОС через plyer; при недоступности пишет в консоль."""
    try:
        from plyer import notification
        notification.notify(title=title, message=message, app_name="Анализатор чатов", timeout=10)
    except Exception:                                  # нет библиотеки или нет сервиса уведомлений
        print(f"[напоминание] {title}: {message}")


def send_due_reminders(hours: int | None = None, now: datetime | None = None,
                       notify: Callable[[str, str], None] = os_notify) -> list[Deadline]:
    """Отправляет ещё не отправленные напоминания; возвращает дедлайны, о которых напомнили."""
    horizon = hours if hours is not None else int(common.tracker_cfg()["remind_hours"])
    sent = []
    for d in due_soon(horizon, now):
        if db.is_reminded(d.id, d.due_at):
            continue
        title, message = reminder_text(d)
        notify(title, message)
        db.mark_reminded(d.id, d.due_at)
        sent.append(d)
    return sent


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Напоминания о близких дедлайнах")
    parser.add_argument("--hours", type=int, default=None, help="за сколько часов напоминать")
    args = parser.parse_args()
    done = send_due_reminders(args.hours)
    print(f"Отправлено напоминаний: {len(done)}")
