"""Роль 4 (задача 4.5): извлечение дедлайна из сообщения локальной моделью.

Модель только достаёт факты в JSON (DeadlineExtract из src/schemas.py); даты считает
dates.py. Вызов модели изолирован в _chat(), тесты подменяют его.
"""
import json
import re
import time
from pathlib import Path
from typing import Sequence

from pydantic import ValidationError

from src import config
from src.schemas import DeadlineExtract, Message
from src.tracker import common, db

PROMPT_VERSION = "extract_v1"
PROMPT_PATH = common.ROOT / "config" / "prompts" / "extract_v1.txt"
RETRY_HINT = "Верни только JSON по схеме, без пояснений и без markdown."


class ModelUnavailable(Exception):
    """Ollama недоступна или модель не скачана: сообщение нельзя обработать сейчас."""


def _model_name() -> str:
    return common.cfg()["models"]["llm"]


def load_prompt() -> str:
    disciplines = "\n".join(
        f"- {key}: {info.get('name', key)}"
        for key, info in common.cfg()["disciplines"].items())
    return PROMPT_PATH.read_text(encoding="utf-8").replace("{disciplines}", disciplines or "-")


def _fmt(m: Message) -> str:
    return f"[{common.parse_dt(m.ts):%Y-%m-%d %H:%M}] {m.author} ({m.role}): {m.text}"


def build_messages(msg: Message, previous: Sequence[Message] = (),
                   parent: Message | None = None) -> list[dict]:
    """Сообщения для модели: системный промпт + контекст + разбираемое сообщение."""
    parts = []
    if previous:
        parts.append("Предыдущие сообщения чата:\n" + "\n".join(_fmt(m) for m in previous))
    if parent is not None:
        parts.append("Сообщение, на которое отвечает разбираемое:\n" + _fmt(parent))
    parts.append(f"Разбираемое сообщение [id={msg.id}]:\n{_fmt(msg)}")
    return [{"role": "system", "content": load_prompt()},
            {"role": "user", "content": "\n\n".join(parts)}]


def _chat(messages: list[dict]) -> str:
    """Один вызов Ollama. Структурированный вывод по схеме, рассуждения отключены."""
    import ollama
    try:
        resp = ollama.chat(
            model=_model_name(), messages=messages,
            format=DeadlineExtract.model_json_schema(), think=False,
            options={"temperature": 0})
    except Exception as e:                      # сервер не запущен, модели нет, таймаут
        raise ModelUnavailable(f"Ollama недоступна: {e}") from e
    return resp.message.content or ""


def parse_response(raw: str) -> DeadlineExtract:
    """Разбор ответа модели; терпит обёртку ```json и лишний текст вокруг объекта."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return DeadlineExtract.model_validate_json(text)
    except ValidationError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise
        return DeadlineExtract.model_validate_json(m.group(0))


def _log(name: str, record: dict) -> None:
    try:
        folder = Path(common.cfg()["paths"]["logs"])
        folder = folder if folder.is_absolute() else common.ROOT / folder
        folder.mkdir(parents=True, exist_ok=True)
        with open(folder / name, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass                                      # лог не должен ронять обработку


def extract_deadline(msg: Message, previous: Sequence[Message] = (),
                     parent: Message | None = None) -> DeadlineExtract | None:
    """DeadlineExtract для сообщения или None, если модель дважды вернула негодный JSON.

    ModelUnavailable пробрасывается: вызывающий решает, что делать без модели.
    Каждый вызов пишется в logs/extract_calls.jsonl и в таблицу labels (model_json).
    """
    messages = build_messages(msg, previous, parent)
    raw, error, result = "", None, None
    started = time.time()
    for attempt in (1, 2):
        raw = _chat(messages)
        try:
            result = parse_response(raw)
            break
        except (ValidationError, ValueError) as e:
            error = str(e)
            if attempt == 1:
                messages = messages + [{"role": "assistant", "content": raw},
                                       {"role": "user", "content": RETRY_HINT}]
    duration = round(time.time() - started, 2)
    if result is not None:
        model_json = result.model_dump_json()
        db.save_label(msg.id, model_json, PROMPT_VERSION, _model_name())
        _log("extract_calls.jsonl", {"ts": common.now_iso(), "msg_id": msg.id,
                                     "prompt_version": PROMPT_VERSION, "model": _model_name(),
                                     "response": model_json, "seconds": duration})
        return result
    _log("extract_failures.jsonl", {"ts": common.now_iso(), "msg_id": msg.id,
                                    "prompt_version": PROMPT_VERSION, "model": _model_name(),
                                    "response": raw, "error": error, "seconds": duration})
    return None


def resolve_discipline(extract: DeadlineExtract, msg: Message) -> str | None:
    """Ключ дисциплины: ответ модели, иначе алиасы в тексте, иначе чат с именем-ключом."""
    keys = common.cfg()["disciplines"]
    if extract.discipline in keys:
        return extract.discipline
    found = config.find_discipline(extract.discipline or "") or config.find_discipline(msg.text)
    if found:
        return found
    return msg.chat if msg.chat in keys else None
