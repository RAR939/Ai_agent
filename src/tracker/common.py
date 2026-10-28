"""Общие мелочи трекера: настройки, время (Москва), загрузка сообщений чата."""
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from src import config as _config
from src.schemas import Message

try:
    MSK = ZoneInfo("Europe/Moscow")
except Exception:                      # нет базы часовых поясов (например, голый Windows)
    MSK = timezone(timedelta(hours=3))

ROOT = Path(__file__).resolve().parents[2]


def cfg() -> dict:
    """Настройки проекта. Тесты подменяют эту функцию."""
    return _config.load_config()


def tracker_cfg() -> dict:
    return cfg()["tracker"]


def now() -> datetime:
    return datetime.now(MSK)


def now_iso() -> str:
    """Текущее время строкой ISO с поясом +03:00."""
    return now().isoformat(timespec="seconds")


def to_iso(dt: datetime) -> str:
    """datetime -> ISO с поясом Москвы (наивное время считается московским)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MSK)
    return dt.astimezone(MSK).isoformat(timespec="seconds")


def parse_dt(value: str) -> datetime:
    """ISO-строка или просто дата -> datetime с поясом Москвы (дата = 00:00)."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MSK)
    return dt.astimezone(MSK)


def parse_date(value: str) -> date:
    """'2026-10-21' или полный ISO -> date (по московскому времени)."""
    return parse_dt(value).date()


def end_of_day(d: date) -> datetime:
    """Конец дня 23:59:00 (правило контракта для дат без времени)."""
    return datetime(d.year, d.month, d.day, 23, 59, 0, tzinfo=MSK)


def load_chat(chat_id: str) -> list[Message]:
    """Сообщения чата в порядке времени.

    Порядок источников: src.ingest.store.load_messages (роль 2), затем
    data/clean/<chat>.jsonl, затем синтетический tests/fixtures/mini_chat.jsonl.
    """
    msgs: list[Message] | None = None
    try:
        from src.ingest.store import load_messages
        msgs = load_messages(chat_id)
    except (ImportError, AttributeError):   # хранилище роли 2 ещё не готово
        msgs = None
    if msgs is None:
        path = ROOT / "data" / "clean" / f"{chat_id}.jsonl"
        if not path.exists():
            path = ROOT / "tests" / "fixtures" / "mini_chat.jsonl"
        msgs = []
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip() and json.loads(line).get("chat") == chat_id:
                    msgs.append(Message.model_validate_json(line))
    return sorted(msgs, key=lambda m: (parse_dt(m.ts), _num(m.id)))


def _num(msg_id: str) -> int:
    try:
        return int(msg_id.split(":")[1])
    except (IndexError, ValueError):
        return 0
