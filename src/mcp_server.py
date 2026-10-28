# path/to/src/mcp_server.py
"""
MCP-сервер (Роль 5). Тонкая обертка над функциями ролей 3 и 4.
Возвращает только JSON-строки.
"""
# path/to/src/mcp_server.py
import sys
import os

# Добавляем корень проекта в sys.path, чтобы mcp dev мог найти модуль src
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import json
# ... дальше твои остальные импорты
from mcp.server import MCPServer
from src.schemas import Deadline, PendingItem
import src.mocks as mocks
import json
import sys
from mcp.server import MCPServer

from src.schemas import Deadline, PendingItem
# В будущем, когда роли 3 и 4 будут готовы, мы заменим src.mocks на src.index и src.tracker
import src.mocks as mocks

# Создаем сервер
mcp = MCPServer("student-helper")

def _to_json(data) -> str:
    """Вспомогательная функция для сериализации Pydantic-моделей или списков в JSON."""
    if isinstance(data, list):
        return json.dumps([item.model_dump() for item in data], ensure_ascii=False)
    elif hasattr(data, "model_dump"):
        return json.dumps(data.model_dump(), ensure_ascii=False)
    return json.dumps(data, ensure_ascii=False)

@mcp.tool()
def search_messages(query: str, discipline: str | None = None, period_days: int = 30, role: str | None = None) -> str:
    """Ищет сообщения в учебных чатах по смыслу. Используй для вопросов о том, что говорили или обсуждали. Не используй для вопросов про сроки сдачи: для них есть list_deadlines."""
    try:
        hits = mocks.search(query=query, discipline=discipline, top_k=5)
        return _to_json(hits)
    except Exception as e:
        return json.dumps({"error": f"Ошибка поиска: {str(e)}"}, ensure_ascii=False)

@mcp.tool()
def read_new_messages(chat: str, since: str | None = None) -> str:
    """Показывает новые сообщения чата, которые ещё не обработаны."""
    try:
        msgs = mocks.read_messages(chat=chat, since=since)
        return _to_json(msgs[:30])
    except Exception as e:
        return json.dumps({"error": f"Ошибка чтения сообщений: {str(e)}"}, ensure_ascii=False)

@mcp.tool()
def list_deadlines(days_ahead: int = 14, discipline: str | None = None, status: str = "active") -> str:
    """Показывает дедлайны на ближайшие дни. Используй для вопросов "что мне сдать", "когда сдавать", "что горит". Не используй для вопросов о том, что обсуждали в чате (для них search_messages)."""
    try:
        items = mocks.list_deadlines(discipline=discipline, status=status)
        return _to_json(items)
    except Exception as e:
        return json.dumps({"error": f"Ошибка получения дедлайнов: {str(e)}"}, ensure_ascii=False)

@mcp.tool()
def add_deadline(discipline: str, task: str, due_text: str, source_msg: str) -> str:
    """Добавляет новый дедлайн. При сомнениях возвращает 'Ожидает подтверждения'."""
    try:
        res = mocks.add_deadline(discipline, task, due_text, source_msg)
        if isinstance(res, PendingItem):
            return json.dumps({
                "status": "pending", 
                "message": f"Ожидает подтверждения (номер {res.id}): найдено '{res.candidate.task} до {res.candidate.due_text}'. Подтвердите в интерфейсе.",
                "data": res.model_dump()
            }, ensure_ascii=False)
        return _to_json(res)
    except Exception as e:
        return json.dumps({"error": f"Ошибка добавления: {str(e)}"}, ensure_ascii=False)

@mcp.tool()
def update_deadline(id: int, new_due_text: str, source_msg: str) -> str:
    """Меняет срок существующего дедлайна, записывая историю переноса."""
    try:
        res = mocks.update_due(id, new_due_text, source_msg)
        return _to_json(res)
    except Exception as e:
        return json.dumps({"error": f"Ошибка обновления: {str(e)}"}, ensure_ascii=False)

@mcp.tool()
def get_schedule(date_from: str, date_to: str | None = None, discipline: str | None = None) -> str:
    """Занятия за период. Используй для вопросов "какие пары", "что завтра", "расписание"."""
    try:
        lessons = mocks.lessons_between(date_from, date_to, discipline)
        return _to_json(lessons)
    except Exception as e:
        return json.dumps({"error": f"Ошибка получения расписания: {str(e)}"}, ensure_ascii=False)

@mcp.tool()
def load_schedule(path: str) -> str:
    """Загружает расписание из файла .ics или .xlsx."""
    try:
        res = mocks.load_schedule(path)
        return _to_json(res)
    except Exception as e:
        return json.dumps({"error": f"Ошибка загрузки расписания: {str(e)}"}, ensure_ascii=False)

@mcp.tool()
def get_attachments(deadline_id: int) -> str:
    """Показывает файлы (методички, шаблоны), прикрепленные к дедлайну."""
    try:
        files = mocks.get_attachments(deadline_id)
        return _to_json(files)
    except Exception as e:
        return json.dumps({"error": f"Ошибка получения файлов: {str(e)}"}, ensure_ascii=False)

@mcp.tool()
def process_new_messages(chat: str) -> str:
    """Запускает конвейер поиска новых дедлайнов в чате."""
    try:
        rep = mocks.process_new(chat)
        return _to_json(rep)
    except Exception as e:
        return json.dumps({"error": f"Ошибка обработки: {str(e)}"}, ensure_ascii=False)

if __name__ == "__main__":
    # Важно: в режиме stdio нельзя печатать в stdout!
    print("Запуск MCP-сервера...", file=sys.stderr)
    mcp.run(transport="stdio")