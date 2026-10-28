"""Тесты задачи 4.3: запросы к расписанию."""
import pytest

from src.schemas import Lesson
from src.tracker import schedule_query as sq


@pytest.fixture
def lessons(tdb):
    def mk(d, h, disc, kind="lecture", dur=95):
        start = f"2026-{d}T{h}:00+03:00"
        hh, mm = map(int, h.split(":"))
        end_min = hh * 60 + mm + dur
        return Lesson(discipline=disc, lesson_type=kind, start=start,
                      end=f"2026-{d}T{end_min // 60:02d}:{end_min % 60:02d}:00+03:00")
    tdb.replace_lessons([
        mk("10-23", "08:30", "elektro"),                 # пятница
        mk("10-23", "10:15", "models", "seminar"),
        mk("10-26", "08:30", "elektro", "lab"),          # понедельник
        mk("10-27", "12:00", "models"),
        mk("10-30", "08:30", "elektro")])                # пятница, последнее занятие
    return tdb


def test_lessons_on_and_between(lessons):
    assert [x.discipline for x in sq.lessons_on("2026-10-23")] == ["elektro", "models"]
    assert sq.lessons_on("2026-10-24") == []                       # суббота
    assert len(sq.lessons_between("2026-10-23", "2026-10-27")) == 4
    assert [x.start[:10] for x in sq.lessons_between("2026-10-23", "2026-10-30", "elektro")] == [
        "2026-10-23", "2026-10-26", "2026-10-30"]
    assert len(sq.lessons_between("2026-10-26")) == 1              # date_to=None: один день
    assert len(sq.lessons_on("2026-10-23T23:59:00+03:00")) == 2    # ISO вместо даты


def test_next_lesson_friday_evening_gives_monday(lessons):
    nxt = sq.next_lesson("elektro", "2026-10-23T19:00:00+03:00")
    assert nxt.start == "2026-10-26T08:30:00+03:00"


def test_next_lesson_is_strictly_later(lessons):
    # за минуту до пары: сама пара подходит; ровно в начало: уже следующая
    assert sq.next_lesson("elektro", "2026-10-23T08:29:00+03:00").start[:10] == "2026-10-23"
    assert sq.next_lesson("elektro", "2026-10-23T08:30:00+03:00").start[:10] == "2026-10-26"


def test_next_lesson_type_filter_and_none(lessons):
    assert sq.next_lesson("elektro", "2026-10-20T00:00:00+03:00", "lab").start[:10] == "2026-10-26"
    assert sq.next_lesson("models", "2026-10-20T00:00:00+03:00", "lab") is None
    assert sq.next_lesson("elektro", "2026-10-30T08:30:00+03:00") is None   # последний день
    assert sq.next_lesson("нет_такой", "2026-10-20T00:00:00+03:00") is None


def test_lessons_tomorrow(lessons):
    assert [x.discipline for x in sq.lessons_tomorrow("2026-10-22T21:00:00+03:00")] == [
        "elektro", "models"]
    assert sq.lessons_tomorrow("2026-10-23T21:00:00+03:00") == []          # завтра суббота
    assert len(sq.lessons_tomorrow("2026-10-25T09:00:00+03:00")) == 1      # воскресенье -> понедельник


def test_empty_schedule_queries(tdb):
    assert sq.lessons_on("2026-10-23") == []
    assert sq.next_lesson("elektro", "2026-10-23T10:00:00+03:00") is None
