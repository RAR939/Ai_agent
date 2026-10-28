"""Роль 4 (задача 4.7): новый это дедлайн или изменение известного. Без дублей.

find_match(candidate): то же задание среди активных дедлайнов той же дисциплины.
apply_candidate(...): решение по таблице:
  new, совпадения нет            -> вставить
  new, совпадение есть           -> дубль (тот же срок) или перенос (другой срок)
  move, совпадение есть          -> update_due + история
  cancel, совпадение есть        -> статус cancelled
  move без совпадения, несколько равных совпадений, уверенность ниже порога -> очередь pending
  cancel без совпадения          -> ничего (отменять нечего)
Свежее побеждает: сообщение старше уже учтённого изменения ничего не затирает.
"""
import re
from datetime import datetime
from typing import Callable, Literal, NamedTuple

from rapidfuzz import fuzz, utils

from src.schemas import AttachedFile, Deadline
from src.tracker import common, db

_TYPE_PATTERNS = [
    ("lab", r"лабораторн[а-я]*|лаб[а-я]*|лр"),
    ("hw", r"дз|домашн[а-я]*|домашк[а-я]*"),
    ("midterm", r"рк|рубеж[а-я]*|контрольн[а-я]*|кр"),
    ("exam", r"экзамен[а-я]*|зачет[а-я]*"),
    ("course", r"курсов[а-я]*|курсач[а-я]*"),
]
_TYPE_RE = [(t, re.compile(rf"(?<![а-я])(?:{p})(?![а-я])")) for t, p in _TYPE_PATTERNS]
_KIND_TO_TYPE = {"lab": "lab", "hw": "hw", "midterm": "midterm", "exam": "exam"}

Key = tuple[str | None, int | None]


def _fold(text: str) -> str:
    return text.lower().replace("ё", "е")


def task_key(task: str, kind: str | None = None) -> Key:
    """«Лаб. 2», «лабораторная 2», «ЛР2» -> ('lab', 2). Нет номера или типа: None на их месте."""
    text = _fold(task)
    for t, rx in _TYPE_RE:
        m = rx.search(text)
        if m:
            digits = re.search(r"\d+", text[m.end():]) or re.search(r"\d+", text)
            return t, int(digits.group()) if digits else None
    digits = re.search(r"\d+", text)
    return _KIND_TO_TYPE.get(kind or ""), int(digits.group()) if digits else None


def mentioned_tasks(text: str) -> set[tuple[str, int]]:
    """Все пары (тип, номер), упомянутые в тексте: «Лаб.2 и ЛР3» -> {('lab',2),('lab',3)}."""
    text = _fold(text)
    found = set()
    for t, rx in _TYPE_RE:
        for m in rx.finditer(text):
            n = re.match(r"[\s.№#:-]*(\d+)", text[m.end():])
            if n:
                found.add((t, int(n.group(1))))
    return found


def _score(a: str, b: str) -> float:
    return fuzz.token_set_ratio(a, b, processor=utils.default_process)


def _threshold() -> float:
    return float(common.tracker_cfg()["similarity_threshold"])


def find_candidates(candidate: Deadline) -> list[Deadline]:
    """Все активные дедлайны той же дисциплины, подходящие под кандидата (лучшие равные)."""
    pool = db.list_deadlines(discipline=candidate.discipline, status="active")
    pool = [d for d in pool if d.id is not None and d.id != candidate.id]
    ctype, cnum = task_key(candidate.task, candidate.kind)
    if cnum is not None:
        return [d for d in pool
                if (k := task_key(d.task, d.kind))[1] == cnum
                and (ctype is None or k[0] is None or k[0] == ctype)]
    if ctype is not None:
        pool = [d for d in pool if task_key(d.task, d.kind)[0] == ctype]
    scored = [(_score(candidate.task, d.task), d) for d in pool]
    scored = [(s, d) for s, d in scored if s >= _threshold()]
    if not scored:
        return []
    best = max(s for s, _ in scored)
    return [d for s, d in scored if s == best]


def find_match(candidate: Deadline) -> Deadline | None:
    """Единственное подходящее задание или None (нет совпадения или их несколько)."""
    found = find_candidates(candidate)
    return found[0] if len(found) == 1 else None


class Outcome(NamedTuple):
    kind: Literal["added", "moved", "cancelled", "pending", "noop", "stale"]
    deadline_id: int | None = None
    pending_id: int | None = None


def _attach(deadline_id: int, files: list[AttachedFile]) -> None:
    for bind in dict.fromkeys(f.bind or "same_message" for f in files):
        db.attach_files(deadline_id, [f for f in files if (f.bind or "same_message") == bind], bind)


def _latest_change_ts(d: Deadline, ts_of: Callable[[str], str | None]) -> datetime | None:
    """Время самого свежего сообщения, повлиявшего на дедлайн (создание или перенос)."""
    ids = [d.source_msg] + [e.source_msg for e in db.get_history(d.id)]
    stamps = [ts for i in ids if (ts := ts_of(i))]
    return max(common.parse_dt(s) for s in stamps) if stamps else None


def apply_candidate(candidate: Deadline, action: str | None, msg_ts: str, source_text: str,
                    ts_of: Callable[[str], str | None] = lambda _id: None) -> Outcome:
    """Применяет кандидата (из сообщения msg_ts) к базе и сообщает, что произошло.

    candidate.attachments это файлы от collect_files (с bind); ts_of(id) даёт время
    сообщения по его id (нужно для правила «свежее побеждает»).
    """
    action = action or "new"
    threshold = float(common.tracker_cfg()["confidence_threshold"])
    matches = find_candidates(candidate)
    one = matches[0] if len(matches) == 1 else None
    pending_copy = candidate.model_copy(update={
        "status": "cancelled" if action == "cancel" else "pending"})

    def queue(reason: str, matched: Deadline | None) -> Outcome:
        pid = db.add_pending(pending_copy, matched.id if matched else None, reason, source_text)
        return Outcome("pending", matched.id if matched else None, pid)

    if candidate.confidence < threshold:
        return queue("low_confidence", one)
    if len(matches) > 1:
        return queue("ambiguous_match", matches[0])

    if action == "cancel":
        if one is None:
            return Outcome("noop")
        if _is_stale(one, msg_ts, ts_of):
            return Outcome("stale", one.id)
        db.set_status(one.id, "cancelled")
        return Outcome("cancelled", one.id)

    if one is None:
        if action == "move":
            return queue("no_match_for_move", None)
        new_id = db.add_deadline(candidate.model_copy(update={"status": "active"}))
        return Outcome("added", new_id)

    # совпадение есть: new с другим сроком трактуем как перенос
    if _is_stale(one, msg_ts, ts_of):
        return Outcome("stale", one.id)
    _attach(one.id, candidate.attachments)
    if one.due_at == candidate.due_at:
        return Outcome("noop", one.id)
    db.update_due(one.id, candidate.due_at, candidate.source_msg)
    db.update_deadline_text(one.id, candidate.due_text, candidate.fuzzy, candidate.confidence)
    return Outcome("moved", one.id)


def _is_stale(existing: Deadline, msg_ts: str, ts_of: Callable[[str], str | None]) -> bool:
    latest = _latest_change_ts(existing, ts_of)
    return latest is not None and common.parse_dt(msg_ts) < latest
