# path/to/src/mocks.py
"""
Заглушки для ролей 3 (поиск) и 4 (трекер).
Используются Ролью 5 для тестирования MCP-сервера.
"""
import json
from datetime import datetime, timezone, timedelta
from src.schemas import Deadline, SearchHit, AttachedFile, Lesson, Report, ScheduleImport, Message, PendingItem

MSK = timezone(timedelta(hours=3))
NOW = datetime.now(MSK).isoformat(timespec='seconds')

# --- Роль 3: Индексация и поиск ---
def search(query: str, discipline: str | None = None, date_from: str | None = None,
           date_to: str | None = None, role: str | None = None, top_k: int = 5) -> list[SearchHit]:
    if not query:
        raise ValueError("Пустой поисковый запрос")
    return [
        SearchHit(
            chunk_id="elektro:1040-1051", chat="elektro",
            text="Лаб.2 по электротехнике сдаём до пятницы. Отчет в docx.",
            ts_from="2026-10-21T14:01:00+03:00", ts_to="2026-10-21T14:20:00+03:00",
            roles=["starosta", "student"], msg_ids=["elektro:1040", "elektro:1041"],
            discipline="elektro", score=0.83
        )
    ]

# --- Роль 4: Трекер и расписание ---
def list_deadlines(date_from: str | None = None, date_to: str | None = None,
                   discipline: str | None = None, status: str = "active") -> list[Deadline]:
    if discipline and discipline not in ["elektro", "models"]:
        raise ValueError(f"Дисциплина не найдена: {discipline}. Доступные: elektro, models")
    return [
        Deadline(
            id=5, discipline="elektro", kind="lab", task="Лаб.2",
            due_at="2026-10-24T23:59:00+03:00", due_text="до пятницы, 24.10",
            fuzzy=False, status="active", source_msg="elektro:1042", confidence=0.93,
            updated_at="2026-10-21T14:10:00+03:00",
            attachments=[
                AttachedFile(id="elektro:1042:f1", msg_id="elektro:1042", name="lab2_elektro.pdf",
                             ext="pdf", size_bytes=184320, path="files/lab2_elektro.pdf", bind="same_message")
            ]
        )
    ]

def get_attachments(deadline_id: int) -> list[AttachedFile]:
    dl = list_deadlines()
    for d in dl:
        if d.id == deadline_id:
            return d.attachments
    return []

def lessons_between(date_from: str, date_to: str | None = None, discipline: str | None = None) -> list[Lesson]:
    return [
        Lesson(id=1, discipline="elektro", lesson_type="lab",
               start="2026-10-22T10:00:00+03:00", end="2026-10-22T11:30:00+03:00",
               teacher="Иванов", room="А-201")
    ]

def process_new(chat_id: str) -> Report:
    return Report(processed=10, added=1, moved=0, cancelled=0, pending=0, skipped_prefilter=5, failed=0)

def read_messages(chat: str, since: str | None = None) -> list[Message]:
    return [
        Message(id="elektro:1050", chat="elektro", ts="2026-10-22T12:00:00+03:00",
                author="STAROSTA", role="starosta", text="Завтра лаба отменяется",
                reply_to=None, forwarded=False, src="messages2.html#message1050", attachments=[])
    ]

def add_deadline(discipline: str, task: str, due_text: str, source_msg: str) -> Deadline | PendingItem:
    # Имитируем ситуацию, когда модель не уверена, и отправляем на подтверждение
    candidate = Deadline(
        discipline=discipline, kind="hw", task=task, due_text=due_text,
        source_msg=source_msg, confidence=0.4, status="pending"
    )
    return PendingItem(id=12, candidate=candidate, matched_id=None, reason="low_confidence",
                       source_text="Сдать лабу до пятницы", created_at=NOW)

def update_due(id: int, new_due_at: str | None, source_msg: str) -> Deadline:
    return Deadline(
        id=id, discipline="elektro", kind="lab", task="Лаб.2",
        due_at="2026-10-31T23:59:00+03:00", due_text="до 31.10",
        source_msg=source_msg, confidence=0.9, status="active"
    )

def load_schedule(path: str, dry_run: bool = False) -> ScheduleImport:
    return ScheduleImport(ok=True, lessons=[], errors=[], replaced=0)