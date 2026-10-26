# Контракты данных

*ИИ-агент «Анализатор учебных чатов»: единый документ для всех ролей*

## Зачем этот документ

Это единый контракт данных проекта. Пять-шесть человек пишут модули параллельно, и они совместятся только если все используют одни и те же типы, идентификаторы, форматы файлов и сигнатуры функций. Этот документ читают **все роли** до начала работы. Код-источник правды: `src/schemas.py` (текст из раздела 3 копируется туда как есть). Если документ и код разошлись, прав код, а документ нужно сразу исправить.

> **Правило изменений.** Любое изменение контракта идёт отдельным pull request с пометкой `contract-change`, с описанием «что было, что стало, кого затрагивает» и с сообщением в общий чат. Принимает его роль 1 после одобрения каждой затронутой роли. Добавлять поля «для себя» без этого нельзя.

## 1. Общие соглашения

| Что | Как договорились |
|---|---|
| Идентификатор сообщения | `<chat_id>:<номер из экспорта>`, например `elektro:1042`. Номер берётся из `id="message1042"` в HTML |
| Идентификатор чанка | `<chat_id>:<первый_номер>-<последний_номер>`, например `elektro:1040-1051` |
| Идентификатор дедлайна, ожидающей записи, занятия | Целое число, назначает SQLite |
| Время | Строка ISO 8601 с поясом `+03:00` (Москва): `2026-10-21T14:03:00+03:00`. Внутри кода используется `datetime` с `zoneinfo.ZoneInfo("Europe/Moscow")`, наружу всегда строка. Время без пояса запрещено |
| Дата без времени | Если срок «до пятницы» без часа, ставьте `23:59:00` этого дня |
| Роли авторов | `starosta`, `teacher`, `student`, `unknown` (латиницей, в нижнем регистре) |
| Метки авторов | `STAROSTA`, `TEACHER_1`, `STUDENT_7`: постоянные, одинаковые во всех чатах и запусках |
| Дисциплины | Ключ из `config/disciplines.yaml` латиницей (`elektro`, `models`). Русские названия только в интерфейсе, берутся из того же файла |
| Типы заданий (`kind`) | `lab` (лабораторная), `hw` (домашнее задание), `midterm` (рубежный контроль), `exam` (экзамен, зачёт), `other` |
| Статусы дедлайна | `active` (действует), `moved` (был перенесён; текущей записи с этим статусом нет, используйте для истории), `done` (выполнен), `cancelled` (отменён), `pending` (ждёт подтверждения) |
| Типы занятий | `lecture`, `seminar`, `lab`, `other` |
| Вложения | Только документы (`pdf`, `docx`, `doc`, `xlsx`, `pptx`, `zip`, `txt` и т. п.). Идентификатор файла `<id сообщения>:f<номер>`, например `elektro:1042:f1`. Путь относительный от `data/raw/<chat_id>/`, имя для показа обезличено. Файлы остаются локальными, в репозиторий не попадают |
| Привязка файлов к дедлайну (`bind`) | `same_message` (файл в сообщении с дедлайном), `same_author_near` (файл того же автора в пределах `tracker.attach_window_min` минут), `reply_context` (файл в сообщении, на которое ответили, или в ответе на него) |
| Пустые значения | Нет значения: `None` в Python и `null` в JSON. Пустую строку вместо `None` не использовать |
| Кодировка и формат файлов | UTF-8, переводы строк `\n`. Наборы записей хранятся как JSON Lines (одна запись на строку), настройки как YAML |
| Язык кода | Имена функций и полей на английском; комментарии, сообщения об ошибках и тексты интерфейса на русском |

## 2. Потоки данных между ролями

Таблица показывает, кто что производит, где лежит результат и кто его читает. Если вы получаете или отдаёте данные не по этой таблице, остановитесь и согласуйте.

| Производит | Что и где | Тип | Потребляет |
|---|---|---|---|
| Роль 2 | `data/clean/<chat>.jsonl` (обезличенные сообщения) | `Message` | Роли 1, 3, 4 |
| Роль 2 | `data/raw/<chat>/` (исходный HTML и папка `files/`, только локально) | файлы | Роль 2; роль 6 открывает файлы по `path` |
| Роль 1 | `tests/fixtures/mini_chat/` и `tests/fixtures/mini_chat.jsonl` | HTML и `Message` | Все (тесты) |
| Роль 1 | `config/config.yaml`, `disciplines.yaml`, `roles.yaml` | YAML | Все (`load_config()`) |
| Роль 3 | `data/chroma/`, `data/bm25.pkl`, `data/index_state.json` | индекс | Только роль 3 |
| Роль 3 | `search()` и `answer()` | `SearchHit`, `Answer` | Роли 5, 6, 2 |
| Роль 4 | `data/helper.db` (SQLite) | таблицы раздела 5 | Роли 5, 6 |
| Роль 3 | `get_discussion()` (обсуждение вокруг задания) | `SearchHit` | Роли 5, 6 |
| Роль 4 | `db.*`, `schedule_query.*`, `pipeline.process_new()`, привязка файлов | Раздел 4 | Роли 5, 6 |
| Роль 5 | `run_agent()` и MCP-инструменты | `AgentResult` | Роль 6, оценка |
| Роль 5 | `logs/agent_trace.jsonl` | `ToolCall` | Роли 1, 2 (оценка) |
| Роль 6 | `ui/provider.py` | интерфейс `Provider` | Только роль 6 |
| Роли 1, 2 | `data/labels/gold.jsonl` | `LabelRecord` | Роли 2, 4, 5 |

## 3. Схемы данных (`src/schemas.py`)

Скопируйте код целиком в `src/schemas.py`. Комментарии менять можно, имена и типы полей нельзя без `contract-change`.

```
from pydantic import BaseModel, Field
from typing import Literal, Optional

# ---------- общие типы ----------
Role = Literal["starosta", "teacher", "student", "unknown"]
Kind = Literal["lab", "hw", "midterm", "exam", "other"]
Status = Literal["active", "moved", "done", "cancelled", "pending"]
LessonType = Literal["lecture", "seminar", "lab", "other"]
ISO = str   # "2026-10-21T14:03:00+03:00", всегда с поясом +03:00

# ---------- роль 2 -> все ----------
class AttachedFile(BaseModel):
    id: str                   # "elektro:1042:f1"
    msg_id: str               # сообщение, к которому приложен файл
    name: str                 # имя для показа, обезличенное: "lab2_elektro.pdf"
    ext: str                  # "pdf", "docx" (нижний регистр, без точки)
    size_bytes: int
    path: str                 # относительно data/raw/<chat>/ : "files/lab2.pdf"
    bind: Optional[Literal["same_message", "same_author_near",
                           "reply_context"]] = None   # как привязан к дедлайну

class Message(BaseModel):
    id: str                   # "elektro:1042"
    chat: str                 # "elektro"
    ts: ISO
    author: str               # метка: "STAROSTA", "STUDENT_7", "TEACHER_2"
    role: Role
    text: str                 # обезличенный текст, не пустой
    reply_to: Optional[str] = None   # id исходного сообщения
    forwarded: bool = False
    src: str                  # "messages2.html#message1042"
    attachments: list[AttachedFile] = []   # только документы

# ---------- роль 3 ----------
class Chunk(BaseModel):
    id: str                   # "elektro:1040-1051"
    chat: str
    msg_ids: list[str]        # по порядку
    ts_from: ISO
    ts_to: ISO
    roles: list[Role]         # уникальные роли авторов
    discipline: Optional[str] = None   # ключ из disciplines.yaml
    text: str                 # "[2026-10-21 14:03] starosta: ..."

class SearchHit(BaseModel):
    chunk_id: str
    chat: str
    text: str                 # не длиннее 1500 символов
    ts_from: ISO
    ts_to: ISO
    roles: list[Role]
    msg_ids: list[str]
    discipline: Optional[str] = None
    score: float              # после реранка, больше = лучше

class Answer(BaseModel):
    text: str
    sources: list[SearchHit]
    refused: bool = False     # True: "В материалах этого нет"
    prompt_version: str       # "answer_v1"

# ---------- роль 4 ----------
class DeadlineExtract(BaseModel):   # ответ LLM, только внутри tracker
    has_deadline: bool
    discipline: Optional[str] = None
    kind: Optional[Kind] = None
    task: Optional[str] = None
    due_text: Optional[str] = None
    action: Optional[Literal["new", "move", "cancel"]] = None
    fuzzy: bool = False
    confidence: float = Field(ge=0, le=1)

class Deadline(BaseModel):
    id: Optional[int] = None  # присваивает SQLite
    discipline: str
    kind: Kind
    task: str                 # "Лаб.2"
    due_at: Optional[ISO] = None     # None, если срок размытый
    due_text: str             # как написано: "до пятницы"
    fuzzy: bool = False
    status: Status = "active"
    source_msg: str           # id сообщения-источника
    confidence: float
    updated_at: Optional[ISO] = None
    attachments: list[AttachedFile] = []   # db заполняет при чтении

class DeadlineEvent(BaseModel):     # строка истории
    id: int
    deadline_id: int
    old_due: Optional[ISO]
    new_due: Optional[ISO]
    source_msg: str
    changed_at: ISO

class PendingItem(BaseModel):       # ждёт подтверждения человека
    id: int
    candidate: Deadline
    matched_id: Optional[int]        # на что похоже
    reason: Literal["low_confidence", "ambiguous_match", "no_match_for_move"]
    source_text: str                 # текст сообщения для показа
    created_at: ISO

class Report(BaseModel):            # результат process_new
    processed: int
    added: int
    moved: int
    cancelled: int
    pending: int
    skipped_prefilter: int
    failed: int

class Lesson(BaseModel):
    id: Optional[int] = None
    discipline: str
    lesson_type: LessonType
    start: ISO                # конкретное занятие, не шаблон
    end: ISO
    teacher: Optional[str] = None
    room: Optional[str] = None

class ScheduleImport(BaseModel):
    ok: bool
    lessons: list[Lesson]     # предпросмотр
    errors: list[str]         # "Строка 7: не найдена дисциплина ..."
    replaced: int             # сколько старых занятий заменено

# ---------- роль 5 ----------
class ToolCall(BaseModel):
    tool: str
    args: dict
    result_preview: str       # первые 300 символов
    duration: float           # секунды
    error: Optional[str] = None

class AgentResult(BaseModel):
    text: str
    sources: list[SearchHit] = []
    trace: list[ToolCall] = []
    pending_ids: list[int] = []      # что ждёт подтверждения из этого ответа

# ---------- роль 6 / все ----------
class DeadlineCard(BaseModel):      # всё для карточки задания
    deadline: Deadline        # внутри deadline.attachments
    history: list[DeadlineEvent]
    discussion: list[SearchHit]   # что говорили вокруг задания

class MessageContext(BaseModel):
    target: Message
    before: list[Message]
    after: list[Message]

class IndexStatus(BaseModel):
    chat: str
    messages: int
    period_from: ISO
    period_to: ISO
    last_processed: Optional[ISO]
    chunks: int
    deadlines: int

# ---------- для статьи (роли 1, 2) ----------
class LabelRecord(BaseModel):
    msg_id: str
    model_json: Optional[str] = None
    human_json: Optional[str] = None
    prompt_version: str
    model_name: str
```

### Примеры записей

#### Строка `data/clean/elektro.jsonl` (Message)

```
{"id": "elektro:1042", "chat": "elektro", "ts": "2026-10-21T14:03:00+03:00", "author": "STAROSTA", "role": "starosta", "text": "Лаб.2 по электротехнике сдаём до пятницы, 24.10", "reply_to": null, "forwarded": false, "src": "messages2.html#message1042"}
```

#### Результат поиска (SearchHit)

```
{"chunk_id": "elektro:1040-1051", "chat": "elektro", "text": "[2026-10-21 14:03] starosta: Лаб.2 ...", "ts_from": "2026-10-21T14:01:00+03:00", "ts_to": "2026-10-21T14:20:00+03:00", "roles": ["starosta", "student"], "msg_ids": ["elektro:1040", "elektro:1041"], "discipline": "elektro", "score": 0.83}
```

#### Сообщение с вложением (Message)

```
{"id": "elektro:1042", "chat": "elektro", "ts": "2026-10-21T14:03:00+03:00", "author": "STAROSTA", "role": "starosta", "text": "Лаб.2 по электротехнике сдаём до пятницы, 24.10", "reply_to": null, "forwarded": false, "src": "messages2.html#message1042", "attachments": [{"id": "elektro:1042:f1", "msg_id": "elektro:1042", "name": "lab2_elektro.pdf", "ext": "pdf", "size_bytes": 184320, "path": "files/lab2_elektro.pdf", "bind": null}]}
```

#### Дедлайн (Deadline) и строка истории

```
{"id": 5, "discipline": "elektro", "kind": "lab", "task": "Лаб.2", "due_at": "2026-10-24T23:59:00+03:00", "due_text": "до пятницы, 24.10", "fuzzy": false, "status": "active", "source_msg": "elektro:1042", "confidence": 0.93, "updated_at": "2026-10-21T14:10:00+03:00", "attachments": [{"id": "elektro:1042:f1", "msg_id": "elektro:1042", "name": "lab2_elektro.pdf", "ext": "pdf", "size_bytes": 184320, "path": "files/lab2_elektro.pdf", "bind": "same_message"}]}
{"id": 1, "deadline_id": 5, "old_due": "2026-10-24T23:59:00+03:00", "new_due": "2026-10-31T23:59:00+03:00", "source_msg": "elektro:1100", "changed_at": "2026-10-25T09:00:00+03:00"}
```

#### Ответ агента (AgentResult) с трассой

```
{"text": "Лаб.2 нужно сдать до 31.10 (перенесено с 24.10). Источники: [25.10, староста]", "sources": [], "trace": [{"tool": "list_deadlines", "args": {"days_ahead": 14, "discipline": "elektro"}, "result_preview": "[{\"id\": 5, ...}]", "duration": 0.4, "error": null}], "pending_ids": []}
```

## 4. Интерфейсы модулей (сигнатуры функций)

Это то, что один модуль может вызывать у другого. Реализация внутри модуля ваша, сигнатура общая. Пока модуль не готов, его владелец отдаёт функцию-заглушку с этой же сигнатурой, возвращающую фиксированные данные.

### Конфигурация (роль 1)

```
# src/config.py
def load_config() -> dict           # config.yaml + disciplines.yaml + roles.yaml
def discipline_name(key: str) -> str   # "elektro" -> "Электротехника"
def discipline_color(key: str) -> str  # "#4c78a8"
def find_discipline(text: str) -> str | None  # по алиасам
```

### Данные (роль 2)

```
# src/ingest/parse_telegram_html.py
def parse_export(folder: str, chat_id: str) -> list[Message]

# src/ingest/anonymize.py
def anonymize(messages: list[Message], roles: dict) -> list[Message]

# src/ingest/store.py
def save_messages(chat_id: str, msgs: list[Message]) -> None   # data/clean/<chat>.jsonl
def load_messages(chat_id: str) -> list[Message]
def list_chats() -> list[str]
def get_message(msg_id: str) -> Message
def get_context(msg_id: str, before: int = 3, after: int = 3) -> MessageContext
def get_attachments(msg_id: str) -> list[AttachedFile]
def file_abs_path(f: AttachedFile) -> str   # абсолютный путь для открытия

# eval/evaluate.py (CLI)
# python -m eval.evaluate --task tracker|search|agent --gold data/labels/gold.jsonl
```

### Индексация и поиск (роль 3)

```
# src/index/build.py
def reindex(chat_id: str) -> dict        # {"added": int, "updated": int, "total": int}

# src/index/search.py
def search(query: str, chat: str | None = None,
           discipline: str | None = None,
           date_from: str | None = None, date_to: str | None = None,
           role: str | None = None, top_k: int = 5) -> list[SearchHit]

# src/index/answer.py
def answer(question: str, **filters) -> Answer

# src/index/discussion.py
def get_discussion(deadline: Deadline, top_k: int = 5) -> list[SearchHit]
```

Фильтры `date_from` и `date_to` включают границы и принимают ISO-строку или просто дату `2026-10-21`. Пустой результат поиска это пустой список, а не ошибка. `top_k` не больше 8.

### Трекер и расписание (роль 4)

```
# src/tracker/db.py
def init_db() -> None
def add_deadline(d: Deadline) -> int
def get_deadline(id: int) -> Deadline | None
def list_deadlines(date_from: str | None = None, date_to: str | None = None,
                   discipline: str | None = None,
                   status: str | None = "active") -> list[Deadline]
def update_due(id: int, new_due_at: str | None, source_msg: str) -> None  # пишет историю
def set_status(id: int, status: Status) -> None
def get_history(id: int) -> list[DeadlineEvent]
def add_pending(candidate: Deadline, matched_id: int | None,
                reason: str, source_text: str) -> int
def list_pending() -> list[PendingItem]
def resolve_pending(id: int, accept: bool) -> Deadline | None
def processed_ids(chat: str) -> set[str]
def attach_files(deadline_id: int, files: list[AttachedFile], bind: str) -> None
def list_files(deadline_id: int) -> list[AttachedFile]
def get_card(deadline_id: int) -> DeadlineCard

# src/tracker/attach.py
def collect_files(msg: Message, chat_msgs: list[Message]) -> list[AttachedFile]  # bind заполнен

# src/tracker/pipeline.py
def process_new(chat_id: str) -> Report

# src/tracker/schedule_import.py
def load_schedule(path: str, dry_run: bool = False) -> ScheduleImport

# src/tracker/schedule_query.py
def lessons_on(date: str) -> list[Lesson]
def lessons_between(date_from: str, date_to: str,
                    discipline: str | None = None) -> list[Lesson]
def next_lesson(discipline: str, after: str,
                lesson_type: str | None = None) -> Lesson | None
def lessons_tomorrow(now: str) -> list[Lesson]
```

`get_deadline` и `list_deadlines` возвращают дедлайны с заполненным `attachments`. `attach_files` идемпотентна (повторная привязка того же файла ничего не меняет). `get_card` собирает `Deadline`, историю и обсуждение (через `get_discussion` роли 3).

`load_schedule(path, dry_run=True)` ничего не записывает и возвращает предпросмотр с ошибками (для интерфейса). Если `errors` не пусто, запись не выполняется. `resolve_pending(id, accept=True)` вставляет кандидата в `deadlines` (или обновляет совпавший) и удаляет запись из очереди, `accept=False` просто удаляет.

### MCP-инструменты и агент (роль 5)

```
# src/agent.py
async def run_agent(question: str, history: list[dict]) -> AgentResult
# history: [{"role": "user" | "assistant", "content": str}, ...]
```

| Инструмент | Параметры | Возвращает (JSON) |
|---|---|---|
| `search_messages` | query, discipline?, period_days=30, role? | список `SearchHit` |
| `read_new_messages` | chat, since? | список `Message`, не более 30 |
| `list_deadlines` | days_ahead=14, discipline?, status="active" | список `Deadline` |
| `add_deadline` | discipline, task, due_text, source_msg | `Deadline` или `PendingItem` |
| `update_deadline` | id, new_due_text, source_msg | `Deadline` или `PendingItem` |
| `get_schedule` | date_from, date_to?, discipline? | список `Lesson` |
| `load_schedule` | path | `ScheduleImport` |
| `get_attachments` | deadline_id | список `AttachedFile` |
| `process_new_messages` | chat | `Report` |

Все инструменты возвращают JSON-строку. При ошибке: `{"error": "текст на русском"}`, исключение наружу не выходит. Названия и параметры должны совпадать с `docs/mcp_tools.md`.

### Интерфейс (роль 6, `ui/provider.py`)

```
class Provider:
    def ask(self, question: str, history: list[dict]) -> AgentResult
    def list_deadlines(self, discipline=None, status=None) -> list[Deadline]
    def get_deadline_history(self, id: int) -> list[DeadlineEvent]
    def list_pending(self) -> list[PendingItem]
    def resolve_pending(self, id: int, accept: bool) -> None
    def lessons_between(self, date_from: str, date_to: str,
                        discipline=None) -> list[Lesson]
    def load_schedule(self, path: str, dry_run=False) -> ScheduleImport
    def get_message_context(self, msg_id: str, before=3, after=3) -> MessageContext
    def get_card(self, deadline_id: int) -> DeadlineCard
    def file_abs_path(self, f: AttachedFile) -> str
    def index_status(self) -> list[IndexStatus]
    def reindex(self, chat: str) -> dict
    def process_new(self, chat: str) -> Report
    def corpus_stats(self) -> dict
```

## 5. База данных SQLite (`data/helper.db`)

Схему создаёт роль 4 в `init_db()`. Прямой доступ к базе из других модулей запрещён: только через функции `db.py`. Значения времени хранятся строками ISO.

```
CREATE TABLE deadlines(
  id INTEGER PRIMARY KEY,
  discipline TEXT NOT NULL,
  kind TEXT NOT NULL,
  task TEXT NOT NULL,
  due_at TEXT,
  due_text TEXT NOT NULL,
  fuzzy INTEGER DEFAULT 0,
  status TEXT DEFAULT 'active',
  source_msg TEXT NOT NULL,
  confidence REAL,
  updated_at TEXT);

CREATE TABLE deadline_history(
  id INTEGER PRIMARY KEY,
  deadline_id INTEGER REFERENCES deadlines(id),
  old_due TEXT, new_due TEXT,
  source_msg TEXT, changed_at TEXT);

CREATE TABLE pending(
  id INTEGER PRIMARY KEY,
  candidate_json TEXT NOT NULL,
  matched_id INTEGER,
  reason TEXT,
  source_text TEXT,
  created_at TEXT);

CREATE TABLE lessons(
  id INTEGER PRIMARY KEY,
  discipline TEXT, lesson_type TEXT,
  start TEXT, end TEXT, teacher TEXT, room TEXT);

CREATE TABLE processed_msgs(
  msg_id TEXT PRIMARY KEY,
  processed_at TEXT,
  had_deadline INTEGER);

CREATE TABLE files(
  id TEXT PRIMARY KEY,
  msg_id TEXT NOT NULL,
  name TEXT NOT NULL, ext TEXT, size_bytes INTEGER,
  path TEXT NOT NULL);

CREATE TABLE deadline_files(
  deadline_id INTEGER REFERENCES deadlines(id),
  file_id TEXT REFERENCES files(id),
  bind TEXT,
  linked_at TEXT,
  PRIMARY KEY(deadline_id, file_id));

CREATE TABLE labels(
  msg_id TEXT PRIMARY KEY,
  model_json TEXT, human_json TEXT,
  prompt_version TEXT, model_name TEXT);
```

## 6. Файлы и конфигурация

### Структура `config/config.yaml` (черновик)

```
models:
  llm: "qwen3:8b"
  embed: "bge-m3"
  reranker: "BAAI/bge-reranker-v2-m3"
  temperature: 0.1
retrieval:
  chunk_strategy: "window"   # window | thread | day
  window_size: 10
  window_step: 5
  max_chunk_chars: 1800
  candidates: 20
  rerank_top: 15
  top_k: 5
  min_score: 0.3             # порог релевантности
  use_reranker: true
  bm25: {k1: 1.5, b: 0.75}
tracker:
  prefilter_keywords: ["сдать", "сдача", "срок", "дедлайн", "перенести"]
  confidence_threshold: 0.7
  similarity_threshold: 85   # rapidfuzz, 0-100
  attach_window_min: 10      # окно для файлов того же автора
  attach_exts: [pdf, docx, doc, xlsx, pptx, zip, rar, txt, odt]
  attach_max_per_msg: 5
schedule:
  semester_start: "2026-09-01"
  first_week_parity: "odd"   # odd | even
  holidays: []
agent:
  max_steps: 5
  timeout_sec: 120
ui:
  use_mock: true
paths:
  data: "data"
  db: "data/helper.db"
  logs: "logs"
```

### Структура `config/disciplines.yaml`

```
elektro:
  name: "Электротехника"
  color: "#4c78a8"
  aliases: ["электротех", "электра", "ЭТ"]
models:
  name: "Модели данных"
  color: "#f58518"
  aliases: ["модели", "МД", "бд"]
```

### Структура `config/roles.yaml` (шаблон в git, настоящий файл только локально)

```
starosta: ["Имя Фамилия как в экспорте"]
teachers:
  TEACHER_1: ["Имя Фамилия"]
students: []        # остальные получат STUDENT_N автоматически
```

### Файл эталонной разметки `data/labels/gold.jsonl`

Одна запись на строку, поля `LabelRecord`: `msg_id`, `human_json` (то, что решил человек, в формате `DeadlineExtract` и дополнительными полями `due_at_gold` и `files_gold`: список id файлов, которые должны быть прикреплены), `model_json` (заполняется позже), `prompt_version`, `model_name`. Разметка двойная для 20% сообщений: второй аннотатор пишется в `data/labels/gold_annotator2.jsonl` с теми же полями.

### Лог трассы `logs/agent_trace.jsonl`

```
{"ts": "2026-10-25T09:00:00+03:00", "question": "когда лаба 2?", "trace": [ToolCall, ...], "answer": "...", "total_sec": 18.4, "model": "qwen3:8b"}
```

## 7. Заглушки и порядок работы

- Роль 1 в первый же день делает `src/schemas.py`, `tests/fixtures/mini_chat.jsonl` (20–30 сообщений по контракту) и файлы `config/*`. Остальные начинают с них.
- Каждый владелец модуля сразу публикует функции-заглушки по сигнатурам из раздела 4 (возвращают фиксированные данные того же типа), а потом заменяет их настоящей реализацией. Так роль 6 и роль 5 не ждут остальных.
- Тесты на контракт: `tests/test_contracts.py` проверяет, что примеры из раздела 3 проходят `model_validate_json` и что все заглушки возвращают правильные типы. Пишет роль 1.
- Время и роли проверяет валидатор: в `Message` и `Deadline` добавьте проверку, что строка времени содержит пояс (`+03:00`). Некорректный формат должен падать сразу при создании объекта, а не в чужом модуле.

### Контрольный список перед заморозкой контракта

- Все роли прочитали документ и подтвердили в общем чате словом «согласен».
- Сигнатуры из раздела 4 совпадают с тем, как вы их будете вызывать (проверьте именно свои вызовы чужих функций).
- Формат времени, идентификаторов и ролей понятен всем и не вызывает вопросов.
- Нет полей, которые нужны вашему модулю, но отсутствуют в схемах. Если есть, добавляйте до заморозки.
