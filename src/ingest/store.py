"""Роль 2: хранилище сообщений data/clean/<chat>.jsonl. ЗАГЛУШКА (docs/contracts.md, раздел 4).

Если data/clean/<chat>.jsonl есть, читает его, иначе отдаёт сообщения синтетического мини-чата.
Реальную версию пишет роль 2; после замены модуль перестаёт быть заглушкой (нет IS_STUB).
"""
from pathlib import Path

from src import _fixture_data as fx
from src.schemas import AttachedFile, Message, MessageContext

IS_STUB = True


def _clean_path(chat_id: str) -> Path:
    return fx.ROOT / "data" / "clean" / f"{chat_id}.jsonl"


def save_messages(chat_id: str, msgs: list[Message]) -> None:
    path = _clean_path(chat_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(m.model_dump_json() + "\n" for m in msgs), encoding="utf-8")


def load_messages(chat_id: str) -> list[Message]:
    path = _clean_path(chat_id)
    if path.exists():
        return [Message.model_validate_json(line)
                for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [m for m in fx.messages() if m.chat == chat_id]


def list_chats() -> list[str]:
    return sorted({m.chat for m in fx.messages()})


def get_message(msg_id: str) -> Message:
    try:
        return fx.message_by_id()[msg_id]
    except KeyError:
        raise KeyError(f"Сообщение не найдено: {msg_id}") from None


def get_context(msg_id: str, before: int = 3, after: int = 3) -> MessageContext:
    target = get_message(msg_id)
    chat = load_messages(target.chat)
    i = next(k for k, m in enumerate(chat) if m.id == msg_id)
    return MessageContext(target=target, before=chat[max(0, i - before):i], after=chat[i + 1:i + 1 + after])


def get_attachments(msg_id: str) -> list[AttachedFile]:
    return get_message(msg_id).attachments


def file_abs_path(f: AttachedFile) -> str:
    """Файл чата: data/raw/<чат>/<path> (контракт); нет такого, берётся файл синтетического мини-чата."""
    real = fx.ROOT / "data" / "raw" / f.msg_id.split(":")[0] / f.path
    return str(real if real.is_file() else fx.FILES_DIR / Path(f.path).name)
