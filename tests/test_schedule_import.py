"""Тесты задачи 4.2: импорт расписания (.ics, Excel)."""
import json
import runpy
import sys
from datetime import date, time

import pytest
from openpyxl import Workbook

from src.tracker import schedule_import as si
from src.tracker import schedule_query as sq

HEADER = si.REQUIRED_COLUMNS


def make_xlsx(path, rows, header=HEADER):
    wb = Workbook()
    ws = wb.active
    ws.append(header)
    for r in rows:
        ws.append(r)
    wb.save(path)
    return str(path)


@pytest.fixture
def sem(set_cfg):
    """Короткий семестр: 01.09.2026 (вторник) .. 28.09.2026, первая неделя нечётная."""
    return set_cfg({"schedule": {"semester_start": "2026-09-01", "semester_end": "2026-09-28",
                                 "first_week_parity": "odd", "holidays": []}})


# ---------- чётность ----------
def test_week_parity_from_semester_start():
    start = date(2026, 9, 1)
    assert si.week_parity(date(2026, 9, 1), start, "odd") == "odd"
    assert si.week_parity(date(2026, 9, 7), start, "odd") == "odd"     # воскресенье 1-й недели
    assert si.week_parity(date(2026, 9, 8), start, "odd") == "even"
    assert si.week_parity(date(2026, 9, 15), start, "odd") == "odd"
    assert si.week_parity(date(2026, 9, 1), start, "even") == "even"   # первая неделя чётная


# ---------- Excel ----------
def test_excel_every_week(tdb, sem, tmp_path):
    f = make_xlsx(tmp_path / "s.xlsx", [
        ["Электротехника", "лекция", "Иванов", "А-201", "вторник", "08:30", "10:05", "каждая"]])
    res = si.load_schedule(f)
    assert res.ok and res.errors == [] and res.replaced == 0
    assert [x.start[:10] for x in res.lessons] == [
        "2026-09-01", "2026-09-08", "2026-09-15", "2026-09-22"]
    first = res.lessons[0]
    assert first.discipline == "elektro" and first.lesson_type == "lecture"
    assert first.start == "2026-09-01T08:30:00+03:00" and first.end == "2026-09-01T10:05:00+03:00"
    assert first.teacher == "Иванов" and first.room == "А-201"
    assert tdb.count_lessons() == 4


def test_excel_odd_and_even_weeks(tdb, sem, tmp_path):
    f = make_xlsx(tmp_path / "s.xlsx", [
        ["электра", "лабораторная", None, None, "чт", "10:15", "11:50", "нечёт"],
        ["МД", "семинар", None, None, "пт", "12:00", "13:35", "чёт"]])
    res = si.load_schedule(f)
    assert res.ok
    odd = [x.start[:10] for x in res.lessons if x.discipline == "elektro"]
    even = [x.start[:10] for x in res.lessons if x.discipline == "models"]
    assert odd == ["2026-09-03", "2026-09-17"]          # 1-я и 3-я недели
    assert even == ["2026-09-11", "2026-09-25"]         # 2-я и 4-я недели
    assert res.lessons[0].teacher is None and res.lessons[0].room is None


def test_excel_even_first_week(tdb, sem, set_cfg, tmp_path):
    set_cfg({"schedule": {"semester_start": "2026-09-01", "semester_end": "2026-09-28",
                          "first_week_parity": "even", "holidays": []}})
    f = make_xlsx(tmp_path / "s.xlsx", [
        ["электра", "лекция", None, None, "вт", "08:30", "10:05", "чёт"]])
    assert [x.start[:10] for x in si.load_schedule(f).lessons] == ["2026-09-01", "2026-09-15"]


def test_excel_holidays_are_skipped(tdb, set_cfg, tmp_path):
    set_cfg({"schedule": {"semester_start": "2026-09-01", "semester_end": "2026-09-28",
                          "first_week_parity": "odd", "holidays": ["2026-09-08"]}})
    f = make_xlsx(tmp_path / "s.xlsx", [
        ["электра", "лекция", None, None, "вт", "08:30", "10:05", "каждая"]])
    assert [x.start[:10] for x in si.load_schedule(f).lessons] == [
        "2026-09-01", "2026-09-15", "2026-09-22"]


def test_excel_time_cells_as_time_objects(tdb, sem, tmp_path):
    f = make_xlsx(tmp_path / "s.xlsx", [
        ["электра", "лекция", None, None, "вт", time(8, 30), time(10, 5), "каждая"]])
    res = si.load_schedule(f)
    assert res.ok and res.lessons[0].start.endswith("T08:30:00+03:00")


def test_excel_collects_all_errors_at_once(tdb, sem, tmp_path):
    f = make_xlsx(tmp_path / "s.xlsx", [
        ["электра", "лекция", None, None, "вт", "08:30", "10:05", "каждая"],      # строка 2 ок
        ["электрот", "лекция", None, None, "вт", "08:30", "10:05", "каждая"],     # строка 3 ошибка (пример из задания)
        ["философия", "лекция", None, None, "вт", "08:30", "10:05", "каждая"],    # строка 4 ошибка
        ["электра", "лекция", None, None, "вт", "11:00", "10:00", "каждая"],      # строка 5 ошибка
        ["электра", "лекция", None, None, "вт", None, "10:00", "каждая"],         # строка 6 ошибка
        ["электра", "лекция", None, None, "когда-то", "08:30", "10:05", "каждая"],  # строка 7
        [None, "лекция", None, None, "вт", "08:30", "10:05", "каждая"]])          # строка 8
    res = si.load_schedule(f)
    assert not res.ok and res.replaced == 0
    text = "\n".join(res.errors)
    assert 'Строка 3: не найдена дисциплина "электрот", добавьте алиас в disciplines.yaml' in text
    assert 'Строка 4: не найдена дисциплина "философия", добавьте алиас в disciplines.yaml' in text
    assert "Строка 5: начало" in text and "Строка 6: не указано время" in text
    assert "Строка 7: непонятный день недели" in text and "Строка 8: не указана дисциплина" in text
    assert len(res.errors) == 6
    assert tdb.count_lessons() == 0                      # при ошибках ничего не записано


def test_excel_missing_columns(tdb, sem, tmp_path):
    f = make_xlsx(tmp_path / "s.xlsx", [["электра", "вт"]], header=["дисциплина", "день_недели"])
    res = si.load_schedule(f)
    assert not res.ok and "нет обязательных колонок" in res.errors[0]


def test_excel_bad_week_value(tdb, sem, tmp_path):
    f = make_xlsx(tmp_path / "s.xlsx", [
        ["электра", "лекция", None, None, "вт", "08:30", "10:05", "иногда"]])
    assert "колонка «неделя»" in si.load_schedule(f).errors[0]


def test_dry_run_writes_nothing(tdb, sem, tmp_path):
    f = make_xlsx(tmp_path / "s.xlsx", [
        ["электра", "лекция", None, None, "вт", "08:30", "10:05", "каждая"]])
    res = si.load_schedule(f, dry_run=True)
    assert res.ok and len(res.lessons) == 4 and tdb.count_lessons() == 0


def test_reload_replaces_not_duplicates(tdb, sem, tmp_path):
    f = make_xlsx(tmp_path / "s.xlsx", [
        ["электра", "лекция", None, None, "вт", "08:30", "10:05", "каждая"]])
    si.load_schedule(f)
    res = si.load_schedule(f)
    assert res.replaced == 4 and tdb.count_lessons() == 4
    assert si.load_schedule(f, dry_run=True).replaced == 4      # dry_run только сообщает число


def test_unsupported_and_missing_file(tdb, sem, tmp_path):
    pdf = tmp_path / "s.pdf"
    pdf.write_bytes(b"%PDF")
    assert "не поддерживается" in si.load_schedule(str(pdf)).errors[0]
    assert "не найден" in si.load_schedule(str(tmp_path / "нет.xlsx")).errors[0]
    broken = tmp_path / "broken.xlsx"
    broken.write_bytes(b"not a zip")
    res = si.load_schedule(str(broken))
    assert not res.ok and "Не удалось прочитать" in res.errors[0]


def test_empty_schedule_is_error(tdb, sem, tmp_path):
    f = make_xlsx(tmp_path / "s.xlsx", [])
    assert "ни одного занятия" in si.load_schedule(f).errors[0]


def test_template_is_valid(tdb, sem, tmp_path):
    path = tmp_path / "t.xlsx"
    si.make_template(str(path))
    res = si.load_schedule(str(path), dry_run=True)
    assert res.ok and {x.discipline for x in res.lessons} == {"elektro", "models"}


# ---------- .ics ----------
ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//RU
BEGIN:VEVENT
UID:1@test
DTSTART;TZID=Europe/Moscow:20260901T083000
DTEND;TZID=Europe/Moscow:20260901T100500
RRULE:FREQ=WEEKLY;COUNT=4
EXDATE;TZID=Europe/Moscow:20260908T083000
SUMMARY:Лекция Электротехника
LOCATION:А-201
DESCRIPTION:Преподаватель: Иванов И. И.
END:VEVENT
BEGIN:VEVENT
UID:2@test
DTSTART:20260904T070000Z
DTEND:20260904T083500Z
SUMMARY:Лабораторная: модели данных
END:VEVENT
BEGIN:VEVENT
UID:3@test
DTSTART;VALUE=DATE:20260905
SUMMARY:Электротехника (целодневное)
END:VEVENT
END:VCALENDAR
"""


def test_ics_recurrence_exdate_and_timezones(tdb, sem, tmp_path):
    p = tmp_path / "s.ics"
    p.write_text(ICS, encoding="utf-8")
    res = si.load_schedule(str(p))
    assert res.ok, res.errors
    el = [x for x in res.lessons if x.discipline == "elektro"]
    assert [x.start[:10] for x in el] == ["2026-09-01", "2026-09-15", "2026-09-22"]   # 8.09 исключена
    assert el[0].lesson_type == "lecture" and el[0].room == "А-201"
    assert el[0].teacher == "Иванов И. И." and el[0].start.endswith("T08:30:00+03:00")
    (md,) = [x for x in res.lessons if x.discipline == "models"]
    assert md.start == "2026-09-04T10:00:00+03:00"        # 07:00 UTC -> 10:00 по Москве
    assert md.lesson_type == "lab"
    assert len(res.lessons) == 4                          # целодневное событие не считается парой


def test_ics_unknown_discipline_reported(tdb, sem, tmp_path):
    p = tmp_path / "s.ics"
    p.write_text(ICS.replace("Лабораторная: модели данных", "Йога"), encoding="utf-8")
    res = si.load_schedule(str(p))
    assert not res.ok and 'не найдена дисциплина' in res.errors[0] and "Йога" in res.errors[0]


def test_schedule_cli_dry_run_and_template(tdb, tmp_path, monkeypatch, capsys):
    def run(argv):
        monkeypatch.setattr(sys, "argv", ["src.tracker.schedule_import"] + argv)
        sys.modules.pop("src.tracker.schedule_import", None)
        runpy.run_module("src.tracker.schedule_import", run_name="__main__")
    tpl = tmp_path / "t.xlsx"
    run(["--template", str(tpl)])
    assert tpl.exists()
    run([str(tpl), "--dry-run"])
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["lessons"] > 0 and tdb.count_lessons() == 0
