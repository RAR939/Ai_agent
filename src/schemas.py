"""Единый контракт данных (docs/contracts.md, раздел 3).

Имена и типы полей менять нельзя без pull request с пометкой contract-change.
Время везде строка ISO 8601 с поясом +03:00; проверяется валидатором при создании объекта.
"""
import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator
from typing import Literal, Optional

# ---------- общие типы ----------
Role = Literal["starosta", "teacher", "student", "unknown"]
Kind = Literal["lab", "hw", "midterm", "exam", "other"]
Status = Literal["active", "moved", "done", "cancelled", "pending"]
LessonType = Literal["lecture", "seminar", "lab", "other"]
ISO = str   # "2026-10-21T14:03:00+03:00", всегда с поясом +03:00

# дата, время (секунды обязательны), необязательные доли секунды и ровно пояс +03:00
_ISO_MSK = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?\+03:00$")


def check_iso_msk(value: Optional[str]) -> Optional[str]:
    """Пропускает None и строку ISO 8601 с поясом +03:00, иначе ValueError."""
    if value is None:
        return value
    if not isinstance(value, str) or not _ISO_MSK.match(value):
        raise ValueError(
            f"время должно быть строкой ISO 8601 с поясом +03:00, например "
            f"2026-10-21T14:03:00+03:00, получено: {value!r}")
    try:
        datetime.fromisoformat(value)
    except ValueError as e:   # например, 2026-13-45T25:00:00+03:00
        raise ValueError(f"некорректное время {value!r}: {e}") from e
    return value


# ---------- роль 2 -> все ----------
class AttachedFile(BaseModel):
    id: str                   # "elektro:1042:f1"; не пустое
    msg_id: str               # сообщение, к которому приложен файл: "elektro:1042"
    name: str                 # имя для показа, обезличенное: "lab2_elektro.pdf"
    ext: str                  # "pdf", "docx" (нижний регистр, без точки)
    size_bytes: int           # размер в байтах: 184320
    path: str                 # относительно data/raw/<chat>/ : "files/lab2.pdf"
    bind: Optional[Literal["same_message", "same_author_near",
                           "reply_context"]] = None   # как привязан к дедлайну; None, пока не привязан

class Message(BaseModel):
    id: str                   # "elektro:1042"
    chat: str                 # "elektro"
    ts: ISO                   # время отправки: "2026-10-21T14:03:00+03:00"
    author: str               # метка: "STAROSTA", "STUDENT_7", "TEACHER_2"
    role: Role                # роль автора: "starosta"
    text: str                 # обезличенный текст, не пустой
    reply_to: Optional[str] = None   # id исходного сообщения: "elektro:1040"; None, если не ответ
    forwarded: bool = False   # True, если сообщение переслано
    src: str                  # откуда взято в экспорте: "messages2.html#message1042"
    attachments: list[AttachedFile] = []   # только документы; пусто, если файлов нет

    _check_time = field_validator("ts")(check_iso_msk)

# ---------- роль 3 ----------
class Chunk(BaseModel):
    id: str                   # "elektro:1040-1051"
    chat: str                 # "elektro"
    msg_ids: list[str]        # по порядку: ["elektro:1040", "elektro:1041"]
    ts_from: ISO              # время первого сообщения чанка
    ts_to: ISO                # время последнего сообщения чанка
    roles: list[Role]         # уникальные роли авторов: ["starosta", "student"]
    discipline: Optional[str] = None   # ключ из disciplines.yaml: "elektro"; None, если не определена
    text: str                 # "[2026-10-21 14:03] starosta: ..."

    _check_time = field_validator("ts_from", "ts_to")(check_iso_msk)

class SearchHit(BaseModel):
    chunk_id: str             # "elektro:1040-1051"
    chat: str                 # "elektro"
    text: str                 # не длиннее 1500 символов
    ts_from: ISO              # начало фрагмента
    ts_to: ISO                # конец фрагмента
    roles: list[Role]         # ["starosta", "student"]
    msg_ids: list[str]        # сообщения фрагмента: ["elektro:1040", "elektro:1041"]
    discipline: Optional[str] = None   # "elektro"; None, если не определена
    score: float              # после реранка, больше = лучше: 0.83

    _check_time = field_validator("ts_from", "ts_to")(check_iso_msk)

class Answer(BaseModel):
    text: str                 # текст ответа
    sources: list[SearchHit]  # на чём основан ответ; пусто при отказе
    refused: bool = False     # True: "В материалах этого нет"
    prompt_version: str       # "answer_v1"

# ---------- роль 4 ----------
class DeadlineExtract(BaseModel):   # ответ LLM, только внутри tracker
    has_deadline: bool        # есть ли в сообщении срок
    discipline: Optional[str] = None   # ключ дисциплины: "elektro"
    kind: Optional[Kind] = None        # "lab"
    task: Optional[str] = None         # "Лаб.2"
    due_text: Optional[str] = None     # срок как написан: "до пятницы"
    action: Optional[Literal["new", "move", "cancel"]] = None   # что сделано со сроком
    fuzzy: bool = False       # True для размытого срока ("на днях")
    confidence: float = Field(ge=0, le=1)   # уверенность модели: 0.93

class Deadline(BaseModel):
    id: Optional[int] = None  # присваивает SQLite
    discipline: str           # ключ дисциплины: "elektro"
    kind: Kind                # "lab"
    task: str                 # "Лаб.2"
    due_at: Optional[ISO] = None     # None, если срок размытый: "2026-10-24T23:59:00+03:00"
    due_text: str             # как написано: "до пятницы"
    fuzzy: bool = False       # срок размытый
    status: Status = "active"
    source_msg: str           # id сообщения-источника: "elektro:1042"
    confidence: float         # уверенность извлечения: 0.93
    updated_at: Optional[ISO] = None   # время последнего изменения; None у нового
    attachments: list[AttachedFile] = []   # db заполняет при чтении

    _check_time = field_validator("due_at", "updated_at")(check_iso_msk)

class DeadlineEvent(BaseModel):     # строка истории
    id: int                   # номер записи истории
    deadline_id: int          # к какому дедлайну относится
    old_due: Optional[ISO]    # прежний срок; None, если не было
    new_due: Optional[ISO]    # новый срок; None, если срок убран
    source_msg: str           # сообщение-основание: "elektro:1100"
    changed_at: ISO           # когда изменено

    _check_time = field_validator("old_due", "new_due", "changed_at")(check_iso_msk)

class PendingItem(BaseModel):       # ждёт подтверждения человека
    id: int                   # номер в очереди
    candidate: Deadline       # что предлагается записать
    matched_id: Optional[int] # на что похоже; None, если ни на что
    reason: Literal["low_confidence", "ambiguous_match", "no_match_for_move"]
    source_text: str          # текст сообщения для показа
    created_at: ISO           # когда попало в очередь

    _check_time = field_validator("created_at")(check_iso_msk)

class Report(BaseModel):            # результат process_new
    processed: int            # обработано сообщений
    added: int                # новых дедлайнов
    moved: int                # переносов
    cancelled: int            # отмен
    pending: int              # ушло на подтверждение
    skipped_prefilter: int    # отсеяно предфильтром
    failed: int               # ошибок обработки

class Lesson(BaseModel):
    id: Optional[int] = None  # присваивает SQLite
    discipline: str           # "elektro"
    lesson_type: LessonType   # "lab"
    start: ISO                # конкретное занятие, не шаблон
    end: ISO                  # окончание занятия
    teacher: Optional[str] = None   # None, если не указан
    room: Optional[str] = None      # аудитория; None, если не указана

    _check_time = field_validator("start", "end")(check_iso_msk)

class ScheduleImport(BaseModel):
    ok: bool                  # True, если ошибок нет и запись выполнена
    lessons: list[Lesson]     # предпросмотр
    errors: list[str]         # "Строка 7: не найдена дисциплина ..."
    replaced: int             # сколько старых занятий заменено

# ---------- роль 5 ----------
class ToolCall(BaseModel):
    tool: str                 # имя инструмента: "list_deadlines"
    args: dict                # аргументы вызова
    result_preview: str       # первые 300 символов
    duration: float           # секунды
    error: Optional[str] = None   # текст ошибки; None, если успешно

class AgentResult(BaseModel):
    text: str                 # ответ пользователю
    sources: list[SearchHit] = []
    trace: list[ToolCall] = []
    pending_ids: list[int] = []      # что ждёт подтверждения из этого ответа

# ---------- роль 6 / все ----------
class DeadlineCard(BaseModel):      # всё для карточки задания
    deadline: Deadline        # внутри deadline.attachments
    history: list[DeadlineEvent]
    discussion: list[SearchHit]   # что говорили вокруг задания

class MessageContext(BaseModel):
    target: Message           # само сообщение
    before: list[Message]     # предыдущие сообщения по порядку
    after: list[Message]      # следующие сообщения по порядку

class IndexStatus(BaseModel):
    chat: str                 # "elektro"
    messages: int             # сообщений в чате
    period_from: ISO          # время первого сообщения
    period_to: ISO            # время последнего сообщения
    last_processed: Optional[ISO]   # когда трекер обработал чат; None, если ещё не обрабатывал
    chunks: int               # чанков в индексе
    deadlines: int            # дедлайнов в базе

    _check_time = field_validator("period_from", "period_to", "last_processed")(check_iso_msk)

# ---------- для статьи (роли 1, 2) ----------
class LabelRecord(BaseModel):
    msg_id: str               # "elektro:1042"
    model_json: Optional[str] = None   # ответ модели (JSON-строка); None, пока не заполнено
    human_json: Optional[str] = None   # решение человека (JSON-строка); None, пока не размечено
    prompt_version: str       # "extract_v1"
    model_name: str           # "qwen3:8b"
