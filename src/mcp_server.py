"""MCP-сервер (роль 5): тонкая обёртка над модулями ролей 2, 3 и 4.

Все инструменты возвращают JSON-строку; при ошибке {"error": "текст на русском"},
исключение наружу не выходит. Названия и параметры совпадают с docs/mcp_tools.md.
Запуск: python -m src.mcp_server (из любой папки, агент делает это сам).
"""
import json
import os
import sys
from datetime import timedelta

# позволяет запускать файл напрямую (mcp dev src/mcp_server.py)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from mcp.server import MCPServer  # noqa: E402

from src.config import load_config  # noqa: E402
from src.ingest import store  # noqa: E402
from src.schemas import Deadline, Message, PendingItem  # noqa: E402
from src.tracker import common, dates, db, match, schedule_import, schedule_query  # noqa: E402

mcp = MCPServer("student-helper")

MAX_NEW_MESSAGES = 30
SEARCH_TOP_K = 5
TOOL_CONFIDENCE = 0.8     # уверенность записи, сделанной через инструмент (ниже порога уходит на подтверждение)
LOW_CONFIDENCE = 0.4      # срок не удалось понять: запись ждёт человека

_KIND_WORDS = (("lab", ("лаб", "лр")), ("hw", ("дз", "домаш")),
               ("midterm", ("рубеж", "контрол", "рк", "кр")), ("exam", ("экзамен", "зач")))


# ---------- вспомогательное ----------
def _to_json(data) -> str:
    """Pydantic-модель или список моделей в JSON-строку."""
    if isinstance(data, list):
        data = [item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in data]
    elif hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    return json.dumps(data, ensure_ascii=False)


def _fail(what: str, error: Exception) -> str:
    """Ошибка инструмента: {"error": "..."}."""
    text = error.args[0] if isinstance(error, KeyError) and error.args else str(error)
    return json.dumps({"error": f"{what}: {text}"}, ensure_ascii=False)


def _check_discipline(discipline: str | None) -> None:
    known = load_config()["disciplines"]
    if discipline and discipline not in known:
        raise ValueError(f"Дисциплина не найдена: {discipline}. Доступные: {', '.join(known)}")


def _search_hits(**kwargs):
    """Поиск роли 3 (импорт внутри: сервер стартует, даже если индекс не установлен)."""
    from src.index.search import search
    return search(**kwargs)


def _message(msg_id: str) -> Message:
    return store.get_message(msg_id)


def _ts_of(msg_id: str) -> str | None:
    try:
        return _message(msg_id).ts
    except KeyError:
        return None


def _guess_kind(task: str) -> str:
    text = task.lower()
    for kind, words in _KIND_WORDS:
        if any(w in text for w in words):
            return kind
    return "other"


def _apply(candidate: Deadline, action: str, source: Message) -> Deadline | PendingItem:
    """Записывает кандидата через сопоставление роли 4 (история, файлы, очередь подтверждений)."""
    outcome = match.apply_candidate(candidate, action, source.ts, source.text, _ts_of)
    if outcome.kind == "pending":
        return next(p for p in db.list_pending() if p.id == outcome.pending_id)
    return db.get_deadline(outcome.deadline_id)


# ---------- инструменты ----------
@mcp.tool()
def search_messages(query: str, discipline: str | None = None, period_days: int = 30,
                    role: str | None = None) -> str:
    """Ищет сообщения в учебных чатах по смыслу. Используй для вопросов о том, что говорили или обсуждали. Не используй для вопросов про сроки сдачи: для них есть list_deadlines."""
    try:
        if not query.strip():
            raise ValueError("Пустой поисковый запрос")
        _check_discipline(discipline)
        date_from = (common.now() - timedelta(days=max(period_days, 0))).date().isoformat()
        hits = _search_hits(query=query, discipline=discipline, date_from=date_from, role=role,
                            top_k=SEARCH_TOP_K)
        return _to_json(hits)
    except Exception as e:
        return _fail("Ошибка поиска", e)


@mcp.tool()
def read_new_messages(chat: str, since: str | None = None) -> str:
    """Показывает новые сообщения чата, которые ещё не обработаны."""
    try:
        done = db.processed_ids(chat)
        msgs = [m for m in store.load_messages(chat)
                if m.id not in done and (not since or m.ts >= since)]
        return _to_json(msgs[:MAX_NEW_MESSAGES])
    except Exception as e:
        return _fail("Ошибка чтения сообщений", e)


@mcp.tool()
def list_deadlines(days_ahead: int = 14, discipline: str | None = None, status: str = "active") -> str:
    """Показывает дедлайны на ближайшие дни. Используй для вопросов "что мне сдать", "когда сдавать", "что горит". Не используй для вопросов о том, что обсуждали в чате (для них search_messages)."""
    try:
        _check_discipline(discipline)
        today = common.now().date()
        dated = db.list_deadlines(today.isoformat(), (today + timedelta(days=max(days_ahead, 0))).isoformat(),
                                  discipline, status)
        fuzzy = [d for d in db.list_deadlines(discipline=discipline, status=status) if d.due_at is None]
        return _to_json(dated + fuzzy)           # размытые сроки показываем всегда
    except Exception as e:
        return _fail("Ошибка получения дедлайнов", e)


@mcp.tool()
def add_deadline(discipline: str, task: str, due_text: str, source_msg: str) -> str:
    """Добавляет новый дедлайн. При сомнениях запись ждёт подтверждения человека: тогда возвращается объект с полями candidate и reason, повторять вызов не нужно."""
    try:
        _check_discipline(discipline)
        source = _message(source_msg)
        due_at, fuzzy = dates.resolve_due(due_text, source.ts, discipline)
        candidate = Deadline(discipline=discipline, kind=_guess_kind(task), task=task.strip(),
                             due_at=due_at, due_text=due_text, fuzzy=fuzzy, source_msg=source_msg,
                             confidence=TOOL_CONFIDENCE)
        return _to_json(_apply(candidate, "new", source))
    except Exception as e:
        return _fail("Ошибка добавления", e)


@mcp.tool()
def update_deadline(id: int, new_due_text: str, source_msg: str) -> str:
    """Меняет срок существующего дедлайна, записывая историю переноса. Если срок непонятен, запись ждёт подтверждения человека."""
    try:
        current = db.get_deadline(id)
        if current is None:
            raise KeyError(f"Дедлайн не найден: {id}")
        source = _message(source_msg)
        due_at, fuzzy = dates.resolve_due(new_due_text, source.ts, current.discipline)
        candidate = Deadline(discipline=current.discipline, kind=current.kind, task=current.task,
                             due_at=due_at, due_text=new_due_text, fuzzy=fuzzy, source_msg=source_msg,
                             confidence=TOOL_CONFIDENCE if due_at else LOW_CONFIDENCE)
        return _to_json(_apply(candidate, "move", source))
    except Exception as e:
        return _fail("Ошибка обновления", e)


@mcp.tool()
def get_schedule(date_from: str, date_to: str | None = None, discipline: str | None = None) -> str:
    """Занятия за период. Используй для вопросов "какие пары", "что завтра", "расписание"."""
    try:
        _check_discipline(discipline)
        return _to_json(schedule_query.lessons_between(date_from, date_to or date_from, discipline))
    except Exception as e:
        return _fail("Ошибка получения расписания", e)


@mcp.tool()
def load_schedule(path: str) -> str:
    """Загружает расписание из файла .ics или .xlsx."""
    try:
        return _to_json(schedule_import.load_schedule(path))
    except Exception as e:
        return _fail("Ошибка загрузки расписания", e)


@mcp.tool()
def get_attachments(deadline_id: int) -> str:
    """Показывает файлы (методички, шаблоны), прикрепленные к дедлайну."""
    try:
        if db.get_deadline(deadline_id) is None:
            raise KeyError(f"Дедлайн не найден: {deadline_id}")
        return _to_json(db.list_files(deadline_id))
    except Exception as e:
        return _fail("Ошибка получения файлов", e)


@mcp.tool()
def process_new_messages(chat: str) -> str:
    """Запускает конвейер поиска новых дедлайнов в чате."""
    try:
        from src.tracker import pipeline
        return _to_json(pipeline.process_new(chat))
    except Exception as e:
        return _fail("Ошибка обработки", e)


if __name__ == "__main__":
    # В режиме stdio нельзя печатать в stdout, только в stderr
    print("Запуск MCP-сервера...", file=sys.stderr)
    mcp.run(transport="stdio")
