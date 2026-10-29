"""Данные для функций-заглушек: всё строится из синтетического мини-чата tests/fixtures.

Только для заглушек (модули с IS_STUB = True). Реальные модули этот файл не используют.
"""
from functools import lru_cache
from pathlib import Path

from src.schemas import Message, SearchHit

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
FILES_DIR = FIXTURES / "mini_chat" / "files"


@lru_cache(maxsize=1)
def messages() -> tuple[Message, ...]:
    lines = (FIXTURES / "mini_chat.jsonl").read_text(encoding="utf-8").splitlines()
    return tuple(Message.model_validate_json(line) for line in lines if line.strip())


def message_by_id() -> dict[str, Message]:
    return {m.id: m for m in messages()}


def _hit(chat: str, numbers: list[int], score: float) -> SearchHit:
    by_msg = message_by_id()
    msgs = [by_msg[f"{chat}:{n}"] for n in numbers]
    text = "\n".join(f"[{m.ts[:16].replace('T', ' ')}] {m.role}: {m.text}" for m in msgs)
    return SearchHit(chunk_id=f"{chat}:{numbers[0]}-{numbers[-1]}", chat=chat, text=text[:1500],
                     ts_from=msgs[0].ts, ts_to=msgs[-1].ts, roles=list(dict.fromkeys(m.role for m in msgs)),
                     msg_ids=[m.id for m in msgs], discipline=chat, score=score)


@lru_cache(maxsize=1)
def hits() -> tuple[SearchHit, ...]:
    """Четыре фиксированных фрагмента, по убыванию оценки."""
    return (_hit("elektro", [1010, 1011], 0.91), _hit("elektro", [1040, 1041], 0.84),
            _hit("models", [2001, 2002, 2003], 0.77), _hit("algo", [3020, 3021, 3022], 0.7))
