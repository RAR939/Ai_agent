# src/ingest/sample_review.py
"""Три независимые случайные выборки ID для ручной проверки приватности.

Тексты сообщений не выводятся и не копируются в отчёт о выборке.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import random

try:
    from src.schemas import Message
except ModuleNotFoundError as exc:
    if exc.name not in {"src.schemas", "src"}:
        raise
    from schemas import Message

from src.ingest.anonymize import _save_private_text


def select_review_samples(messages: list[Message], sample_size: int = 100,
                          rounds: int = 3) -> list[list[str]]:
    """Каждая выборка независима; повторения между выборками допустимы."""
    if sample_size < 1 or rounds < 1:
        raise ValueError("Количество сообщений и выборок должно быть положительным")
    ids = [msg.id for msg in messages]
    if len(ids) != len(set(ids)):
        raise ValueError("Обнаружены повторяющиеся id сообщений")
    if len(ids) < sample_size:
        raise ValueError("В чате недостаточно сообщений для указанной выборки")
    rng = random.SystemRandom()
    return [rng.sample(ids, sample_size) for _ in range(rounds)]


def main() -> int:
    cli = argparse.ArgumentParser(description="Выборка ID для локального ручного аудита")
    cli.add_argument("--chat", required=True)
    cli.add_argument("--count", type=int, default=100)
    cli.add_argument("--rounds", type=int, default=3)
    args = cli.parse_args()
    from src.ingest.parse_telegram_html import _load_project_config
    data_root = Path(_load_project_config()["paths"]["data"])
    root = data_root / "clean"
    path = root / f"{args.chat}.jsonl"
    messages = [Message.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if any(m.chat != args.chat for m in messages):
        raise ValueError("В очищенном JSONL обнаружен другой chat_id")
    samples = select_review_samples(messages, args.count, args.rounds)
    result = root / f"{args.chat}.review_ids.json"
    _save_private_text(result, json.dumps({"samples": samples, "checked": [False] * args.rounds},
                                          ensure_ascii=False, indent=2) + "\n")
    print(f"Сформировано {len(samples)} выборок по {args.count} ID; ручная проверка не выполнена")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
