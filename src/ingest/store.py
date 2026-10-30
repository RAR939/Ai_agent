"""Работа с реальными сообщениями из data/clean и вложениями из data/raw."""

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from src.schemas import AttachedFile, Message, MessageContext


ROOT = Path(__file__).resolve().parents[2]


def _clean_dir() -> Path:
    return ROOT / "data" / "clean"


def _raw_dir(chat_id: str) -> Path:
    return ROOT / "data" / "raw" / chat_id


def _clean_path(chat_id: str) -> Path:
    if not chat_id or chat_id in {".", ".."} or "/" in chat_id or "\\" in chat_id:
        raise ValueError(f"Некорректный ID чата: {chat_id!r}")

    return _clean_dir() / f"{chat_id}.jsonl"


def _message_sort_key(message: Message):
    return datetime.fromisoformat(message.ts), message.id


@lru_cache(maxsize=32)
def _load_cached(
    path: str,
    modified_ns: int,
    file_size: int,
) -> tuple[Message, ...]:
    """Читает и валидирует JSONL. Кэш обновляется при изменении файла."""

    messages = []
    seen_ids = set()

    with Path(path).open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue

            try:
                message = Message.model_validate_json(line)
            except Exception as exc:
                raise ValueError(
                    f"Ошибка чтения {path}, строка {line_number}: {exc}"
                ) from exc

            if message.id in seen_ids:
                raise ValueError(
                    f"Повторяющийся ID сообщения {message.id!r} "
                    f"в файле {path}, строка {line_number}"
                )

            seen_ids.add(message.id)
            messages.append(message)

    messages.sort(key=_message_sort_key)

    return tuple(messages)


def save_messages(chat_id: str, msgs: list[Message]) -> None:
    """Атомарно сохраняет сообщения чата в data/clean/<chat_id>.jsonl."""

    path = _clean_path(chat_id)

    messages = list(msgs)

    seen_ids = set()

    for message in messages:
        if message.chat != chat_id:
            raise ValueError(
                f"Сообщение {message.id!r} относится к чату "
                f"{message.chat!r}, ожидался {chat_id!r}"
            )

        if message.id in seen_ids:
            raise ValueError(
                f"Повторяющийся ID сообщения: {message.id}"
            )

        seen_ids.add(message.id)

    messages.sort(key=_message_sort_key)

    path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = path.with_name(path.name + ".tmp")

    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as file:
            for message in messages:
                file.write(message.model_dump_json())
                file.write("\n")

        temp_path.replace(path)

    finally:
        if temp_path.exists():
            temp_path.unlink()

    _load_cached.cache_clear()


def load_messages(chat_id: str) -> list[Message]:
    """Загружает сообщения указанного чата из реального JSONL."""

    path = _clean_path(chat_id)

    if not path.is_file():
        return []

    stat = path.stat()

    messages = _load_cached(
        str(path),
        stat.st_mtime_ns,
        stat.st_size,
    )

    for message in messages:
        if message.chat != chat_id:
            raise ValueError(
                f"В файле {path} найдено сообщение другого чата: "
                f"{message.id!r}"
            )

    return list(messages)


def list_chats() -> list[str]:
    """Возвращает ID чатов, для которых существуют JSONL-файлы."""

    directory = _clean_dir()

    if not directory.is_dir():
        return []

    return sorted(
        path.stem
        for path in directory.glob("*.jsonl")
        if path.is_file()
    )


def get_message(msg_id: str) -> Message:
    """Находит сообщение по ID вида chat_id:message_id."""

    if not isinstance(msg_id, str) or ":" not in msg_id:
        raise KeyError(f"Некорректный ID сообщения: {msg_id!r}")

    chat_id = msg_id.split(":", 1)[0]

    if not chat_id:
        raise KeyError(f"Некорректный ID сообщения: {msg_id!r}")

    for message in load_messages(chat_id):
        if message.id == msg_id:
            return message

    raise KeyError(f"Сообщение не найдено: {msg_id}")


def get_context(
    msg_id: str,
    before: int = 3,
    after: int = 3,
) -> MessageContext:
    """Возвращает сообщение и соседние сообщения того же чата."""

    if before < 0 or after < 0:
        raise ValueError("before и after не могут быть отрицательными")

    target = get_message(msg_id)
    messages = load_messages(target.chat)

    index = next(
        (
            i
            for i, message in enumerate(messages)
            if message.id == msg_id
        ),
        None,
    )

    if index is None:
        raise KeyError(f"Сообщение не найдено: {msg_id}")

    return MessageContext(
        target=target,
        before=messages[max(0, index - before):index],
        after=messages[index + 1:index + 1 + after],
    )


def get_attachments(msg_id: str) -> list[AttachedFile]:
    """Возвращает вложения указанного сообщения."""

    return get_message(msg_id).attachments


def file_abs_path(file: AttachedFile) -> str:
    """Возвращает абсолютный путь к вложению из data/raw/<chat_id>/."""

    chat_id = file.msg_id.split(":", 1)[0]

    if not chat_id:
        raise ValueError(
            f"Некорректный ID сообщения вложения: {file.msg_id!r}"
        )

    raw_root = _raw_dir(chat_id).resolve()
    relative_path = Path(file.path)

    if relative_path.is_absolute():
        raise ValueError(
            f"Путь вложения должен быть относительным: {file.path!r}"
        )

    target = (raw_root / relative_path).resolve()

    try:
        target.relative_to(raw_root)
    except ValueError:
        raise ValueError(
            f"Путь вложения выходит за пределы каталога чата: {file.path!r}"
        ) from None

    if not target.is_file():
        raise FileNotFoundError(
            f"Файл вложения не найден: {target}"
        )

    return str(target)
