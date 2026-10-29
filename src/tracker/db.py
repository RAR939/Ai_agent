"""Роль 4: SQLite (data/helper.db): дедлайны, история, очередь подтверждений, файлы, занятия.

Весь SQL проекта живёт только здесь. Функции принимают и возвращают объекты из
src/schemas.py. Контрактные функции (docs/contracts.md, раздел 4) описаны первыми,
вспомогательные для остальных модулей трекера (отмечены «доп.») ниже.
"""
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from src.schemas import (
    AttachedFile, Deadline, DeadlineCard, DeadlineEvent, Lesson, PendingItem,
    check_iso_msk,
)
from src.tracker import common

_SCHEMA = (Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8")
_STATUSES = {"active", "moved", "done", "cancelled", "pending"}
_REASONS = {"low_confidence", "ambiguous_match", "no_match_for_move"}
_BINDS = {"same_message", "same_author_near", "reply_context"}

_path_override: str | None = None
_memory_conns: dict[str, sqlite3.Connection] = {}
_ready: set[str] = set()
_lock = threading.RLock()


# ---------- подключение ----------
def set_db_path(path: str | None) -> None:
    """Задаёт путь к базе (":memory:" для тестов); None возвращает путь из конфига."""
    global _path_override
    with _lock:
        if path == ":memory:":
            _memory_conns.pop(path, None)     # каждая настройка :memory: даёт чистую базу
        _path_override = path


def _db_path() -> str:
    if _path_override is not None:
        return _path_override
    rel = common.cfg()["paths"]["db"]
    p = Path(rel)
    return str(p if p.is_absolute() else common.ROOT / p)


def _open(path: str) -> sqlite3.Connection:
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    if path not in _ready:
        conn.executescript(_SCHEMA)
        conn.commit()
        if path != ":memory:":
            _ready.add(path)
    return conn


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """Соединение с транзакцией: commit при успехе, rollback при ошибке."""
    path = _db_path()
    with _lock:
        if path == ":memory:":
            conn = _memory_conns.get(path)
            if conn is None:
                conn = _memory_conns[path] = _open(path)
            keep_open = True
        else:
            conn = _open(path)
            keep_open = False
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            if not keep_open:
                conn.close()


def init_db() -> None:
    """Создаёт таблицы и индексы, если их ещё нет (безопасно вызывать повторно)."""
    with _connect():
        pass


# ---------- преобразования ----------
def _to_deadline(conn: sqlite3.Connection, row: sqlite3.Row) -> Deadline:
    return Deadline(
        id=row["id"], discipline=row["discipline"], kind=row["kind"], task=row["task"],
        due_at=row["due_at"], due_text=row["due_text"], fuzzy=bool(row["fuzzy"]),
        status=row["status"], source_msg=row["source_msg"],
        confidence=row["confidence"] if row["confidence"] is not None else 0.0,
        updated_at=row["updated_at"], attachments=_files_of(conn, row["id"]))


def _files_of(conn: sqlite3.Connection, deadline_id: int) -> list[AttachedFile]:
    rows = conn.execute(
        "SELECT f.id, f.msg_id, f.name, f.ext, f.size_bytes, f.path, df.bind "
        "FROM deadline_files df JOIN files f ON f.id = df.file_id "
        "WHERE df.deadline_id = ? ORDER BY df.rowid", (deadline_id,)).fetchall()
    return [AttachedFile(id=r["id"], msg_id=r["msg_id"], name=r["name"], ext=r["ext"] or "",
                         size_bytes=r["size_bytes"] or 0, path=r["path"], bind=r["bind"])
            for r in rows]


def _link_files(conn: sqlite3.Connection, deadline_id: int,
                files: list[AttachedFile], bind: str) -> None:
    now = common.now_iso()
    for f in files:
        conn.execute(
            "INSERT OR IGNORE INTO files(id, msg_id, name, ext, size_bytes, path) "
            "VALUES (?,?,?,?,?,?)", (f.id, f.msg_id, f.name, f.ext, f.size_bytes, f.path))
        conn.execute(
            "INSERT OR IGNORE INTO deadline_files(deadline_id, file_id, bind, linked_at) "
            "VALUES (?,?,?,?)", (deadline_id, f.id, bind, now))


def _require(conn: sqlite3.Connection, deadline_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM deadlines WHERE id = ?", (deadline_id,)).fetchone()
    if row is None:
        raise LookupError(f"Дедлайн {deadline_id} не найден")
    return row


def _insert_deadline(conn: sqlite3.Connection, d: Deadline) -> int:
    cur = conn.execute(
        "INSERT INTO deadlines(discipline, kind, task, due_at, due_text, fuzzy, status, "
        "source_msg, confidence, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (d.discipline, d.kind, d.task, d.due_at, d.due_text, int(d.fuzzy), d.status,
         d.source_msg, d.confidence, d.updated_at or common.now_iso()))
    new_id = cur.lastrowid
    for f in d.attachments:
        _link_files(conn, new_id, [f], f.bind or "same_message")
    return new_id


def _change_due(conn: sqlite3.Connection, deadline_id: int, new_due_at: str | None,
                source_msg: str) -> bool:
    """Меняет срок и пишет историю. False, если срок не изменился."""
    check_iso_msk(new_due_at)
    row = _require(conn, deadline_id)
    if row["due_at"] == new_due_at:
        return False
    now = common.now_iso()
    conn.execute(
        "INSERT INTO deadline_history(deadline_id, old_due, new_due, source_msg, changed_at) "
        "VALUES (?,?,?,?,?)", (deadline_id, row["due_at"], new_due_at, source_msg, now))
    conn.execute("UPDATE deadlines SET due_at = ?, fuzzy = ?, updated_at = ? WHERE id = ?",
                 (new_due_at, int(new_due_at is None), now, deadline_id))
    return True


# ---------- контракт: дедлайны ----------
def add_deadline(d: Deadline) -> int:
    """Вставляет дедлайн (вместе с d.attachments) и возвращает его id."""
    with _connect() as conn:
        return _insert_deadline(conn, d)


def get_deadline(id: int) -> Deadline | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM deadlines WHERE id = ?", (id,)).fetchone()
        return _to_deadline(conn, row) if row else None


def _bound(value: str, end: bool) -> str:
    """Дата без времени -> начало или конец суток; полный ISO остаётся как есть."""
    return value + ("T23:59:59+03:00" if end else "T00:00:00+03:00") if len(value) == 10 else value


def list_deadlines(date_from: str | None = None, date_to: str | None = None,
                   discipline: str | None = None,
                   status: str | None = "active") -> list[Deadline]:
    """Дедлайны по сроку (границы включены), дисциплине и статусу (None = любой).

    Дедлайны без даты (размытые) попадают в выдачу только если границы не заданы.
    Порядок: по сроку, размытые в конце.
    """
    where, args = [], []
    if date_from:
        where.append("due_at >= ?")
        args.append(_bound(date_from, False))
    if date_to:
        where.append("due_at <= ?")
        args.append(_bound(date_to, True))
    if discipline:
        where.append("discipline = ?")
        args.append(discipline)
    if status:
        where.append("status = ?")
        args.append(status)
    sql = "SELECT * FROM deadlines" + (" WHERE " + " AND ".join(where) if where else "")
    sql += " ORDER BY due_at IS NULL, due_at, id"
    with _connect() as conn:
        return [_to_deadline(conn, r) for r in conn.execute(sql, args).fetchall()]


def update_due(id: int, new_due_at: str | None, source_msg: str) -> None:
    """Меняет срок и пишет строку в историю. Тот же срок: ничего не делает.

    new_due_at=None делает срок размытым (fuzzy=True).
    """
    with _connect() as conn:
        _change_due(conn, id, new_due_at, source_msg)


def set_status(id: int, status: str) -> None:
    if status not in _STATUSES:
        raise ValueError(f"Неизвестный статус: {status!r}")
    with _connect() as conn:
        _require(conn, id)
        conn.execute("UPDATE deadlines SET status = ?, updated_at = ? WHERE id = ?",
                     (status, common.now_iso(), id))


def get_history(id: int) -> list[DeadlineEvent]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM deadline_history WHERE deadline_id = ? ORDER BY id",
                            (id,)).fetchall()
        return [DeadlineEvent(id=r["id"], deadline_id=r["deadline_id"], old_due=r["old_due"],
                              new_due=r["new_due"], source_msg=r["source_msg"] or "",
                              changed_at=r["changed_at"]) for r in rows]


# ---------- контракт: очередь подтверждений ----------
def add_pending(candidate: Deadline, matched_id: int | None,
                reason: str, source_text: str) -> int:
    if reason not in _REASONS:
        raise ValueError(f"Неизвестная причина очереди: {reason!r}")
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO pending(candidate_json, matched_id, reason, source_text, created_at) "
            "VALUES (?,?,?,?,?)",
            (candidate.model_dump_json(), matched_id, reason, source_text, common.now_iso()))
        return cur.lastrowid


def _to_pending(row: sqlite3.Row) -> PendingItem:
    return PendingItem(id=row["id"], candidate=Deadline.model_validate_json(row["candidate_json"]),
                       matched_id=row["matched_id"], reason=row["reason"],
                       source_text=row["source_text"] or "", created_at=row["created_at"])


def list_pending() -> list[PendingItem]:
    with _connect() as conn:
        return [_to_pending(r) for r in conn.execute("SELECT * FROM pending ORDER BY id")]


def resolve_pending(id: int, accept: bool) -> Deadline | None:
    """Подтверждает (accept=True) или отклоняет запись очереди; запись из очереди удаляется.

    Подтверждение: есть matched_id -> обновляется совпавший дедлайн (новый срок идёт в
    историю, файлы кандидата добавляются); кандидат со статусом cancelled отменяет
    совпавший; нет matched_id -> кандидат вставляется как новый active.
    Возвращает итоговый Deadline или None (отклонено, не найдено, нечего отменять).
    """
    with _connect() as conn:
        row = conn.execute("SELECT * FROM pending WHERE id = ?", (id,)).fetchone()
        if row is None:
            return None
        conn.execute("DELETE FROM pending WHERE id = ?", (id,))
        if not accept:
            return None
        cand = Deadline.model_validate_json(row["candidate_json"])
        target = row["matched_id"]
        exists = target is not None and conn.execute(
            "SELECT 1 FROM deadlines WHERE id = ?", (target,)).fetchone()
        if cand.status == "cancelled":
            if not exists:
                return None
            conn.execute("UPDATE deadlines SET status = 'cancelled', updated_at = ? WHERE id = ?",
                         (common.now_iso(), target))
            result_id = target
        elif exists:
            _change_due(conn, target, cand.due_at, cand.source_msg)
            conn.execute("UPDATE deadlines SET due_text = ?, fuzzy = ?, confidence = ? "
                         "WHERE id = ?", (cand.due_text, int(cand.fuzzy), cand.confidence, target))
            result_id = target
        else:
            result_id = _insert_deadline(
                conn, cand.model_copy(update={"id": None, "status": "active", "updated_at": None}))
        if exists and cand.attachments:
            for f in cand.attachments:
                _link_files(conn, result_id, [f], f.bind or "same_message")
        return _to_deadline(conn, _require(conn, result_id))


# ---------- контракт: обработанные сообщения ----------
def processed_ids(chat: str) -> set[str]:
    """Идентификаторы уже обработанных сообщений чата."""
    prefix = f"{chat}:"
    with _connect() as conn:
        rows = conn.execute("SELECT msg_id FROM processed_msgs WHERE substr(msg_id, 1, ?) = ?",
                            (len(prefix), prefix)).fetchall()
        return {r["msg_id"] for r in rows}


# ---------- контракт: файлы ----------
def attach_files(deadline_id: int, files: list[AttachedFile], bind: str) -> None:
    """Привязывает файлы к дедлайну способом bind. Идемпотентна: повтор ничего не меняет."""
    if bind not in _BINDS:
        raise ValueError(f"Неизвестный способ привязки: {bind!r}")
    with _connect() as conn:
        _require(conn, deadline_id)
        _link_files(conn, deadline_id, files, bind)


def list_files(deadline_id: int) -> list[AttachedFile]:
    with _connect() as conn:
        return _files_of(conn, deadline_id)


def get_card(deadline_id: int) -> DeadlineCard:
    """Карточка задания: дедлайн с файлами, история переносов, обсуждение (роль 3)."""
    deadline = get_deadline(deadline_id)
    if deadline is None:
        raise LookupError(f"Дедлайн {deadline_id} не найден")
    try:                                   # поиск роли 3 может быть ещё не готов
        from src.index.discussion import get_discussion
        discussion = get_discussion(deadline)
    except Exception:
        discussion = []
    return DeadlineCard(deadline=deadline, history=get_history(deadline_id),
                        discussion=discussion)


# ---------- доп.: функции для модулей трекера (SQL только здесь) ----------
def mark_processed(msg_id: str, had_deadline: bool) -> None:
    with _connect() as conn:
        conn.execute("INSERT OR REPLACE INTO processed_msgs(msg_id, processed_at, had_deadline) "
                     "VALUES (?,?,?)", (msg_id, common.now_iso(), int(had_deadline)))


def deadline_msg_ids(chat: str) -> set[str]:
    """Сообщения чата, в которых модель нашла срок (нужны предфильтру для ответов)."""
    prefix = f"{chat}:"
    with _connect() as conn:
        rows = conn.execute("SELECT msg_id FROM processed_msgs WHERE had_deadline = 1 "
                            "AND substr(msg_id, 1, ?) = ?", (len(prefix), prefix)).fetchall()
        return {r["msg_id"] for r in rows}


def count_deadlines(chat: str | None = None) -> int:
    """Число дедлайнов (для IndexStatus); chat фильтрует по префиксу source_msg."""
    with _connect() as conn:
        if chat:
            prefix = f"{chat}:"
            row = conn.execute("SELECT COUNT(*) FROM deadlines WHERE substr(source_msg,1,?) = ?",
                               (len(prefix), prefix)).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) FROM deadlines").fetchone()
        return row[0]


def update_deadline_text(id: int, due_text: str, fuzzy: bool, confidence: float) -> None:
    """Обновляет формулировку срока после переноса (история ведётся в update_due)."""
    with _connect() as conn:
        _require(conn, id)
        conn.execute("UPDATE deadlines SET due_text = ?, fuzzy = ?, confidence = ? WHERE id = ?",
                     (due_text, int(fuzzy), confidence, id))


def save_label(msg_id: str, model_json: str | None, prompt_version: str, model_name: str) -> None:
    """Пишет ответ модели в labels; human_json уже стоящей разметки не трогает."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO labels(msg_id, model_json, prompt_version, model_name) VALUES (?,?,?,?) "
            "ON CONFLICT(msg_id) DO UPDATE SET model_json = excluded.model_json, "
            "prompt_version = excluded.prompt_version, model_name = excluded.model_name",
            (msg_id, model_json, prompt_version, model_name))


def get_label(msg_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM labels WHERE msg_id = ?", (msg_id,)).fetchone()
        return dict(row) if row else None


def replace_lessons(lessons: list[Lesson]) -> int:
    """Заменяет всё расписание новым списком; возвращает, сколько старых занятий удалено."""
    with _connect() as conn:
        old = conn.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
        conn.execute("DELETE FROM lessons")
        conn.executemany(
            "INSERT INTO lessons(discipline, lesson_type, start, end, teacher, room) "
            "VALUES (?,?,?,?,?,?)",
            [(x.discipline, x.lesson_type, x.start, x.end, x.teacher, x.room) for x in lessons])
        return old


def count_lessons() -> int:
    with _connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]


def query_lessons(start_from: str | None = None, start_to: str | None = None,
                  discipline: str | None = None, after: str | None = None,
                  lesson_type: str | None = None, limit: int | None = None) -> list[Lesson]:
    """Занятия по началу: start_from <= start <= start_to, строго позже after.

    Все границы полные ISO со своим поясом +03:00. Порядок по началу.
    """
    where, args = [], []
    for col, op, val in (("start", ">=", start_from), ("start", "<=", start_to),
                         ("start", ">", after)):
        if val:
            where.append(f"{col} {op} ?")
            args.append(val)
    if discipline:
        where.append("discipline = ?")
        args.append(discipline)
    if lesson_type:
        where.append("lesson_type = ?")
        args.append(lesson_type)
    sql = "SELECT * FROM lessons" + (" WHERE " + " AND ".join(where) if where else "")
    sql += " ORDER BY start, id" + (f" LIMIT {int(limit)}" if limit else "")
    with _connect() as conn:
        return [Lesson(id=r["id"], discipline=r["discipline"], lesson_type=r["lesson_type"],
                       start=r["start"], end=r["end"], teacher=r["teacher"], room=r["room"])
                for r in conn.execute(sql, args).fetchall()]


def mark_reminded(deadline_id: int, due_at: str) -> None:
    with _connect() as conn:
        conn.execute("INSERT OR IGNORE INTO reminders(deadline_id, due_at, sent_at) VALUES (?,?,?)",
                     (deadline_id, due_at, common.now_iso()))


def is_reminded(deadline_id: int, due_at: str) -> bool:
    with _connect() as conn:
        return conn.execute("SELECT 1 FROM reminders WHERE deadline_id = ? AND due_at = ?",
                            (deadline_id, due_at)).fetchone() is not None
