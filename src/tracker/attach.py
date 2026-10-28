"""Роль 4 (задача 4.9): какие файлы чата относятся к дедлайну. Только по связям сообщений.

Содержимое файлов не читается, названия не угадываются. Три правила:
  same_message      файлы самого сообщения с дедлайном;
  same_author_near  файлы того же автора в окне ±attach_window_min минут, если в том
                    сообщении нет собственного дедлайна для другого задания;
  reply_context     файлы сообщения, на которое отвечают, и сообщений-ответов на него.
Фильтры: расширения из attach_exts, не больше attach_max_per_msg файлов с сообщения,
дубли по id отбрасываются. Лучше пропустить файл, чем прикрепить чужой.
"""
from datetime import timedelta

from src.schemas import AttachedFile, Message
from src.tracker import common, match, prefilter


def _allowed(msg: Message) -> list[AttachedFile]:
    cfg = common.tracker_cfg()
    exts = {e.lower() for e in cfg["attach_exts"]}
    limit = int(cfg["attach_max_per_msg"])
    files = [f for f in msg.attachments if f.ext.lower() in exts]
    return files[:limit]


def _own_other_deadline(other: Message, source: Message) -> bool:
    """В other есть срок для другого задания (его файлы принадлежат ему)."""
    if not prefilter.looks_like_deadline(other):
        return False
    return not (match.mentioned_tasks(other.text) & match.mentioned_tasks(source.text))


def collect_files(msg: Message, chat_msgs: list[Message]) -> list[AttachedFile]:
    """Кандидаты в файлы для дедлайна из сообщения msg; у каждого проставлен bind."""
    window = timedelta(minutes=int(common.tracker_cfg()["attach_window_min"]))
    msg_time = common.parse_dt(msg.ts)
    result: dict[str, AttachedFile] = {}

    def add(files: list[AttachedFile], bind: str) -> None:
        for f in files:
            result.setdefault(f.id, f.model_copy(update={"bind": bind}))

    add(_allowed(msg), "same_message")

    nearby = sorted(
        (m for m in chat_msgs
         if m.id != msg.id and m.author == msg.author and m.attachments
         and abs(common.parse_dt(m.ts) - msg_time) <= window
         and not _own_other_deadline(m, msg)),
        key=lambda m: common.parse_dt(m.ts))
    for m in nearby:
        add(_allowed(m), "same_author_near")

    related_ids = {m.id for m in chat_msgs if m.reply_to == msg.id}
    if msg.reply_to:
        related_ids.add(msg.reply_to)
    for m in sorted((m for m in chat_msgs if m.id in related_ids and m.id != msg.id),
                    key=lambda m: common.parse_dt(m.ts)):
        add(_allowed(m), "reply_context")

    return list(result.values())
