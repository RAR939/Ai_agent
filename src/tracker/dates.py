"""Роль 4 (задача 4.6): вычисление дат. Считает код, а не модель.

resolve_due("до пятницы", "2026-10-20T14:00:00+03:00", "elektro") -> ("2026-10-23T23:59:00+03:00", False)

Правила:
- точка отсчёта это время сообщения (msg_ts), всегда берётся будущее;
- день недели означает ближайший такой день СТРОГО после дня сообщения
  («в понедельник» в понедельник утром это следующий понедельник); «в эту пятницу»
  допускает сегодняшний день, «в следующую пятницу» это пятница следующей недели;
- дата без времени получает 23:59:00;
- «на следующей паре по X» считается по расписанию (время начала занятия);
- размытые сроки («на днях», «скоро») и всё нераспознанное дают (None, True).
"""
import calendar
import re
from datetime import date, datetime, timedelta

from src import config
from src.tracker import common, schedule_query

FUZZY = (None, True)

_WEEKDAYS = {"понедельник": 0, "пн": 0, "вторник": 1, "вт": 1, "сред": 2, "ср": 2,
             "четверг": 3, "чт": 3, "пятниц": 4, "пт": 4, "суббот": 5, "сб": 5,
             "воскресен": 6, "вс": 6}
_MONTHS = {"январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6, "июл": 7,
           "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12}
_NUMBER_WORDS = {"один": 1, "одну": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5,
                 "шесть": 6, "семь": 7, "восемь": 8, "десять": 10, "пару": 2}
_MONTH_RE = ("январ[яь]|феврал[яь]|марта?|апрел[яь]|ма[яй]|июн[яь]|июл[яь]|август[а]?|"
             "сентябр[яь]|октябр[яь]|ноябр[яь]|декабр[яь]")
_WD_RE = ("понедельник\\w*|вторник\\w*|сред[аыуе]|четверг\\w*|пятниц\\w*|суббот\\w*|"
          "воскресен\\w*|пн|вт|ср|чт|пт|сб|вс")

_FUZZY_RE = re.compile(
    r"\bна днях\b|\bскоро\b|\bв ближайшее время\b|\bв ближайшие дни\b|\bпозже\b|\bпотом\b|"
    r"\bкогда[- ]нибудь\b|\bна (?:этой |следующей |той |будущей )?неделе\b|"
    r"\bв (?:этом |следующем )?месяце\b|\bна (?:этих )?выходных\b|\bсо дня на день\b|"
    r"\bдо экзамен\w*|\bк сессии\b|\bпосле (?:зачет|экзамен|лекци)\w*")
_EVENT_RE = re.compile(
    r"\b(?:на|к|до|перед)\s+(?:(?:следующ|ближайш|очередн)\w+\s+)?"
    r"(?P<noun>пар\w*|занят\w*|лекци\w*|семинар\w*|практик\w*|лаб\w*)\b")


def _norm(text: str) -> str:
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[«»\"'(),;!?]+", " ", text)
    return re.sub(r"\s+", " ", text).strip(" .")


def _weekday(token: str) -> int | None:
    token = token.lower()
    for stem, num in _WEEKDAYS.items():
        if len(stem) == 2:
            if token == stem:
                return num
        elif token.startswith(stem):
            return num
    return None


def _month(token: str) -> int | None:
    for stem, num in _MONTHS.items():
        if stem == "ма":
            if token in ("мая", "май"):
                return num
        elif token.startswith(stem):
            return num
    return None


def _extract_time(text: str) -> tuple[tuple[int, int] | None, str]:
    """Явное время суток («18:00», «в 6 вечера») и текст без него."""
    m = re.search(r"(?<![\d.])([01]?\d|2[0-3]):([0-5]\d)(?!\d)", text)
    if m:
        return (int(m.group(1)), int(m.group(2))), (text[:m.start()] + " " + text[m.end():])
    m = re.search(r"\b(?:в|к|до)\s+(\d{1,2})\s*(?:час\w*|ч)\b(?:\s+(утра|вечера|дня|ночи))?", text) \
        or re.search(r"\b(?:в|к|до)\s+(\d{1,2})\s+(дня)\b", text) \
        or re.search(r"\b(\d{1,2})\s*(утра|вечера|ночи)\b", text)
    if m:
        hour = int(m.group(1))
        part = m.group(2) if m.lastindex and m.lastindex >= 2 else None
        if part in ("вечера", "дня") and hour < 12:
            hour += 12
        if hour < 24:
            return (hour, 0), (text[:m.start()] + " " + text[m.end():])
    # «18.00» читается как время, только если это не дата вида 12.11
    for m in re.finditer(r"(?<![\d.])(\d{1,2})\.(\d{2})(?![\d.])", text):
        a, b = int(m.group(1)), int(m.group(2))
        if (b > 12 or b == 0) and a <= 23 and b <= 59:
            return (a, b), (text[:m.start()] + " " + text[m.end():])
    return None, text


def _with_time(day: date, hm: tuple[int, int] | None) -> datetime:
    if hm is None:
        return common.end_of_day(day)
    return datetime(day.year, day.month, day.day, hm[0], hm[1], 0, tzinfo=common.MSK)


def _year_for(day: int, month: int, base: date) -> date | None:
    """Дата дд.мм без года: этот год, а если она заметно в прошлом, то следующий."""
    for year in (base.year, base.year + 1):
        try:
            cand = date(year, month, day)
        except ValueError:
            continue
        if cand >= base - timedelta(days=int(common.tracker_cfg()["date_rollover_days"])):
            return cand
    return None


def _strictly_after(base: date, weekday: int) -> date:
    return base + timedelta(days=(weekday - base.weekday() - 1) % 7 + 1)


def _absolute_date(text: str, base: date) -> date | None:
    m = re.search(r"(?<![\d.])(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?(?![\d.])", text)
    if m and 1 <= int(m.group(2)) <= 12 and 1 <= int(m.group(1)) <= 31:
        day, month = int(m.group(1)), int(m.group(2))
        if m.group(3):
            year = int(m.group(3))
            year += 2000 if year < 100 else 0
            try:
                return date(year, month, day)
            except ValueError:
                return None
        return _year_for(day, month, base)
    m = re.search(rf"(?<!\d)(\d{{1,2}})\s+({_MONTH_RE})(?:\s+(\d{{4}}))?", text)
    if m:
        day, month = int(m.group(1)), _month(m.group(2))
        if m.group(3):
            try:
                return date(int(m.group(3)), month, day)
            except ValueError:
                return None
        return _year_for(day, month, base)
    return None


def _relative_date(text: str, base: date) -> date | None:
    if re.search(r"\bпосле\s?завтра\b", text):
        return base + timedelta(days=2)
    if re.search(r"\bзавтра\b", text):
        return base + timedelta(days=1)
    if re.search(r"\b(?:сегодня|до конца дня|до вечера|до ночи|до полуночи)\b", text):
        return base
    m = re.search(r"\bчерез\s+(\d+|[а-я]+)\s+(дн\w+|день|недел\w+|месяц\w*)\b", text) \
        or re.search(r"\bчерез\s+()(недел\w+|месяц\w*)\b", text)
    if m:
        raw = m.group(1)
        n = 1 if raw == "" else int(raw) if raw.isdigit() else _NUMBER_WORDS.get(raw)
        if n is None:
            return None
        unit = m.group(2)
        if unit.startswith("дн") or unit == "день":
            return base + timedelta(days=n)
        if unit.startswith("недел"):
            return base + timedelta(weeks=n)
        month_index = base.month - 1 + n
        year, month = base.year + month_index // 12, month_index % 12 + 1
        return date(year, month, min(base.day, calendar.monthrange(year, month)[1]))
    m = re.search(r"\b(?:до )?(?:конц[ае]|концу) (следующей )?(месяца|недели)\b", text)
    if m:
        if m.group(2) == "месяца":
            return date(base.year, base.month, calendar.monthrange(base.year, base.month)[1])
        sunday = base + timedelta(days=6 - base.weekday())
        return sunday + timedelta(weeks=1) if m.group(1) else sunday
    return None


def _weekday_date(text: str, base: date) -> date | None:
    m = re.search(rf"\b(?P<adj>следующ\w+|будущ\w+|эт\w+|ближайш\w+)?\s*(?P<wd>{_WD_RE})\b", text)
    if not m:
        return None
    wd = _weekday(m.group("wd"))
    if wd is None:
        return None
    adj = m.group("adj") or ""
    if adj.startswith(("следующ", "будущ")) or re.search(r"\bследующ\w* недел", text):
        monday_next = base + timedelta(days=7 - base.weekday())
        return monday_next + timedelta(days=wd)
    if adj.startswith("эт") and wd == base.weekday():
        return base
    return _strictly_after(base, wd)


def _event_date(text: str, base_dt: datetime, discipline: str | None) -> datetime | None:
    m = _EVENT_RE.search(text)
    if not m:
        return None
    noun = m.group("noun")
    lesson_type = ("lecture" if noun.startswith("лекци") else
                   "seminar" if noun.startswith(("семинар", "практик")) else
                   "lab" if noun.startswith("лаб") else None)
    disc = config.find_discipline(text) or discipline
    if not disc:
        return None
    lesson = schedule_query.next_lesson(disc, base_dt.isoformat(timespec="seconds"), lesson_type)
    return common.parse_dt(lesson.start) if lesson else None


def _dateparser_fallback(text: str, base_dt: datetime) -> datetime | None:
    """Запасной разбор библиотекой dateparser для того, что не поймали правила."""
    import dateparser

    cleaned = re.sub(r"^(?:до|к|на|в|по|с)\s+", "", text).strip()
    if not cleaned or not re.search(r"\d|" + _MONTH_RE, cleaned):
        return None
    parsed = dateparser.parse(cleaned, languages=["ru"], settings={
        "RELATIVE_BASE": base_dt.replace(tzinfo=None), "PREFER_DATES_FROM": "future",
        "TIMEZONE": "Europe/Moscow", "RETURN_AS_TIMEZONE_AWARE": True, "DATE_ORDER": "DMY"})
    return parsed.astimezone(common.MSK) if parsed else None


def resolve_due(due_text: str, msg_ts: str, discipline: str | None = None) -> tuple[str | None, bool]:
    """Срок строкой -> (дата ISO с поясом +03:00, признак размытости).

    (None, True): срок размытый или не распознан (даты нет, пользователь увидит due_text).
    """
    if not due_text or not due_text.strip():
        return FUZZY
    base_dt = common.parse_dt(msg_ts)
    base = base_dt.date()
    text = _norm(due_text)
    hm, rest = _extract_time(text)

    # «через N часов/час»: точное время от момента сообщения
    m = re.search(r"\bчерез\s+(\d+|[а-я]+)?\s*час\w*", rest)
    if m:
        raw = m.group(1)
        n = 1 if not raw else int(raw) if raw.isdigit() else _NUMBER_WORDS.get(raw)
        if n:
            return common.to_iso(base_dt + timedelta(hours=n)), False

    day = (_absolute_date(rest, base) or _relative_date(rest, base)
           or _weekday_date(rest, base))
    if day:
        return common.to_iso(_with_time(day, hm)), False

    if hm is not None and not _EVENT_RE.search(rest) and not _FUZZY_RE.search(rest):
        # только время («до 18:00», «к 9 утра»): ближайшее такое время после сообщения
        cand = _with_time(base, hm)
        return common.to_iso(cand if cand > base_dt else cand + timedelta(days=1)), False

    event = _event_date(rest, base_dt, discipline)
    if event:
        return common.to_iso(event), False
    if _EVENT_RE.search(rest):             # событие названо, но расписания или дисциплины нет
        return FUZZY

    if _FUZZY_RE.search(rest):
        return FUZZY
    fallback = _dateparser_fallback(rest, base_dt)
    if fallback:
        return common.to_iso(_with_time(fallback.date(), hm)), False
    return FUZZY
