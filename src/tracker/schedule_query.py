"""Роль 4 (задача 4.3): запросы к расписанию. Данные берутся из таблицы lessons через db.py."""
from datetime import timedelta

from src.schemas import Lesson
from src.tracker import common, db


def _day_bounds(date_from: str, date_to: str) -> tuple[str, str]:
    d1, d2 = common.parse_date(date_from), common.parse_date(date_to)
    return (common.to_iso(common.parse_dt(d1.isoformat())),
            common.to_iso(common.end_of_day(d2)))


def lessons_on(date: str) -> list[Lesson]:
    """Занятия в один день; date: '2026-10-21' или полный ISO."""
    return lessons_between(date, date)


def lessons_between(date_from: str, date_to: str | None = None,
                    discipline: str | None = None) -> list[Lesson]:
    """Занятия с date_from по date_to включительно (None = один день), по порядку начала."""
    lo, hi = _day_bounds(date_from, date_to or date_from)
    return db.query_lessons(start_from=lo, start_to=hi, discipline=discipline)


def next_lesson(discipline: str, after: str, lesson_type: str | None = None) -> Lesson | None:
    """Ближайшее занятие, начало которого строго позже момента after (ISO или дата).

    Нет занятий в оставшиеся дни: None, а не ошибка. Пятница вечером даёт понедельник.
    """
    moment = common.to_iso(common.parse_dt(after))
    found = db.query_lessons(after=moment, discipline=discipline,
                             lesson_type=lesson_type, limit=1)
    return found[0] if found else None


def lessons_tomorrow(now: str) -> list[Lesson]:
    """Занятия на следующий календарный день после момента now."""
    tomorrow = common.parse_date(now) + timedelta(days=1)
    return lessons_on(tomorrow.isoformat())
