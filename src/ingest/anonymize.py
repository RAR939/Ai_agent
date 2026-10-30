# src/ingest/anonymize.py
"""Локальная анонимизация сообщений Telegram без изменения контракта Message.

Файл roles.local.yaml хранит конфиденциальные соответствия авторов и меток.
Сырые имена и содержимое сообщений не выводятся в лог.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

import yaml

try:
    from src.schemas import Message
except ModuleNotFoundError as exc:
    if exc.name not in {"src.schemas", "src"}:
        raise
    from schemas import Message

# Исключаются совпадения внутри буквенно-цифровых последовательностей, но
# подчёркивание разделяет слова в именах файлов.
_WORD_EDGE_LEFT = r"(?<![^\W_])"
_WORD_EDGE_RIGHT = r"(?![^\W_])"
_WORD = re.compile(r"[^\W\d_][^\W_]*(?:['’\-][^\W_]+)*", re.UNICODE)
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.UNICODE)
_URL = re.compile(r"https?://[^\s<>\[\]]+", re.IGNORECASE)
_MENTION = re.compile(r"(?<![\w@])@[\w]{2,}", re.UNICODE)
_PHONE = re.compile(r"(?<![\w])\+?\d[\d\-\s()]{9,}\d(?![\w])")
_LONG_NUMBER = re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)")
_ROLE_VALUES = {"starosta", "teacher", "student", "unknown"}


def _morph():
    """Загрузить лемматизатор по требованию, без запасной эвристики."""
    try:
        import pymorphy3
    except ImportError as exc:
        raise RuntimeError("Не установлен pymorphy3: без него обработка падежей невозможна") from exc
    return pymorphy3.MorphAnalyzer()


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _role_index(roles: dict, morph: Any) -> tuple[dict[str, dict], list[tuple[re.Pattern[str], str]], dict[str, str], set[str]]:
    people = roles.get("people")
    if not isinstance(people, list):
        raise ValueError("roles.local.yaml должен содержать список people")
    by_label: dict[str, dict] = {}
    aliases: dict[str, set[str]] = defaultdict(set)
    lemmas: dict[str, set[str]] = defaultdict(set)
    for person in people:
        if not isinstance(person, dict):
            raise ValueError("Каждый участник должен быть словарём")
        label, role, names = person.get("label"), person.get("role"), person.get("names")
        if not isinstance(label, str) or not label or label in by_label:
            raise ValueError("Метка участника пуста или повторяется")
        if role not in _ROLE_VALUES:
            raise ValueError("Недопустимая роль участника")
        if not isinstance(names, list) or not all(isinstance(n, str) and n.strip() for n in names):
            raise ValueError("У каждого участника должен быть список names")
        by_label[label] = person
        for name in names:
            key = _normalize_name(name)
            aliases[key].add(label)
            # Токены отдельной формы; при конфликте разных людей замена исключается.
            if len(_WORD.findall(name)) == 1 and len(key) >= 3:
                try:
                    lemma = morph.parse(key)[0].normal_form.casefold()
                except (ValueError, IndexError) as exc:
                    raise ValueError("Лемматизатор не смог обработать имя из локального справочника") from exc
                lemmas[lemma].add(label)
    exact: list[tuple[re.Pattern[str], str]] = []
    for alias, labels in sorted(aliases.items(), key=lambda p: -len(p[0])):
        if len(labels) != 1:
            continue
        label = next(iter(labels))
        # Для полных имён разделители включают пробел, _, дефис.
        pieces = re.split(r"[\s_]+", alias)
        pattern_text = r"[\s_]+".join(re.escape(p) for p in pieces)
        pattern = re.compile(_WORD_EDGE_LEFT + pattern_text + _WORD_EDGE_RIGHT, re.IGNORECASE)
        exact.append((pattern, label))
    unique_lemmas = {k: next(iter(v)) for k, v in lemmas.items() if len(v) == 1}
    ambiguous = set(k for k,v in aliases.items() if len(v) > 1) | set(k for k,v in lemmas.items() if len(v) > 1)
    return by_label, exact, unique_lemmas, ambiguous


def _replace_pii(text: str, morph: Any, exact: list[tuple[re.Pattern[str], str]],
                 lemmas: dict[str, str], stats: Counter, *, filename: bool = False) -> str:
    if not text:
        return text
    # Прежде всего удаляются структурированные идентификаторы; иначе часть адреса
    # электронной почты или ника может совпасть с именем.
    for pattern, replacement, counter in (
        (_URL, "[ССЫЛКА]", "links"),
        (_EMAIL, "[ПОЧТА]", "emails"),
        (_MENTION, "[НИК]", "nicks"),
        (_LONG_NUMBER, "[НОМЕР]", "numbers"),
    ):
        text, count = pattern.subn(replacement, text)
        stats[counter] += count

    def mask_phone(match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group())
        if 10 <= len(digits) <= 15:
            stats["phones"] += 1
            return "[ТЕЛЕФОН]"
        return match.group()

    text = _PHONE.sub(mask_phone, text)
    # Не меняем уже созданные [ССЫЛКА], [НОМЕР] и остальные маски.
    protected = re.compile(r"\[(?:ССЫЛКА|ПОЧТА|НИК|НОМЕР|ТЕЛЕФОН)\]")
    segments = protected.split(text)
    masks = protected.findall(text)
    replaced_segments: list[str] = []
    for segment in segments:
        # Сначала длинные/составные имена, затем одиночные слова в падежах.
        # Промежуточные плейсхолдеры предотвращают повторную подстановку меток.
        placeholders: dict[str, str] = {}
        for pattern, label in exact:
            def change(match: re.Match[str], label: str = label) -> str:
                key = f"\uE000{len(placeholders)}\uE001"
                placeholders[key] = label
                stats["names"] += 1
                return key
            segment = pattern.sub(change, segment)

        def by_lemma(match: re.Match[str]) -> str:
            word = match.group()
            try:
                lemma = morph.parse(word)[0].normal_form.casefold()
            except (ValueError, IndexError):
                return word
            label = lemmas.get(lemma)
            if label is None:
                return word
            stats["names"] += 1
            return label

        # Части плейсхолдеров не должны быть разобраны как имена.
        tokenized = re.split(r"(\uE000\d+\uE001)", segment)
        for i, token in enumerate(tokenized):
            if not token.startswith("\uE000"):
                tokenized[i] = _WORD.sub(by_lemma, token)
        segment = "".join(tokenized)
        for token, label in placeholders.items():
            segment = segment.replace(token, label)
        replaced_segments.append(segment)
    text = "".join(part + (masks[i] if i < len(masks) else "") for i, part in enumerate(replaced_segments))
    return text


def _anonymize_with_stats(messages: list[Message], roles: dict) -> tuple[list[Message], dict[str, int]]:
    """Возвращает копии сообщений и обезличенную количественную статистику."""
    morph = _morph()
    by_label, exact, lemmas, ambiguous = _role_index(roles, morph)
    mapping = roles.get("authors_by_chat")
    if not isinstance(mapping, dict):
        raise ValueError("roles.local.yaml должен содержать authors_by_chat")
    stats: Counter = Counter({name: 0 for name in ("names", "phones", "emails", "links", "nicks", "numbers", "authors", "unknown_authors", "messages")})
    stats["ambiguous_aliases"] = len(ambiguous)
    result: list[Message] = []
    for original in messages:
        message = original.model_copy(deep=True)
        chat_map = mapping.get(message.chat, {})
        if not isinstance(chat_map, dict):
            raise ValueError("authors_by_chat должен содержать словари соответствий")
        # После этапа 2.3 author хранит UNKNOWN_N; по одному индексу нельзя
        # распознать человека из другого чата, поэтому ключ включает chat.
        label = chat_map.get(message.author)
        if label is None and message.author in by_label:
            label = message.author
        if label not in by_label:
            stats["unknown_authors"] += 1
            message.author = "UNKNOWN"
            message.role = "unknown"
        else:
            message.author = label
            message.role = by_label[label]["role"]
            stats["authors"] += 1
        message.text = _replace_pii(message.text, morph, exact, lemmas, stats)
        for attachment in message.attachments:
            attachment.name = _replace_pii(attachment.name, morph, exact, lemmas, stats, filename=True)
            # path НЕ изменяется: он указывает на локальный файл в data/raw.
        if not message.text.strip():
            raise ValueError("После обезличивания текст не должен быть пустым")
        result.append(message)
    stats["messages"] = len(result)
    return result, dict(stats)


def anonymize(messages: list[Message], roles: dict) -> list[Message]:
    """Обезличить Message без изменения входных объектов и структуры контракта."""
    result, _ = _anonymize_with_stats(messages, roles)
    return result


def _save_private_text(path: Path, content: str) -> None:
    """Атомарная запись без промежуточного раскрытия данных в лог."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".anon_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Локальное обезличивание Telegram JSONL")
    parser.add_argument("--chat", required=True, help="Идентификатор чата")
    parser.add_argument("--roles", required=True, help="Локальный путь к roles.local.yaml")
    args = parser.parse_args()

    from src.ingest.parse_telegram_html import _load_project_config
    config = _load_project_config()
    data_root = Path(config["paths"]["data"])
    source = data_root / "parsed" / f"{args.chat}.jsonl"
    destination = data_root / "clean" / f"{args.chat}.jsonl"
    if not source.is_file():
        raise FileNotFoundError("Файл разобранных сообщений отсутствует")
    roles_path = Path(args.roles)
    with roles_path.open(encoding="utf-8") as handle:
        roles = yaml.safe_load(handle)
    if not isinstance(roles, dict):
        raise ValueError("Локальный справочник участников имеет неверный формат")
    messages = [Message.model_validate_json(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    if any(msg.chat != args.chat for msg in messages):
        raise ValueError("В исходном JSONL обнаружено сообщение другого чата")
    clean, report = _anonymize_with_stats(messages, roles)
    _save_private_text(destination, "".join(msg.model_dump_json() + "\n" for msg in clean))
    _save_private_text(destination.with_suffix(".report.json"), json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    # Никаких имен, ссылок, фрагментов сообщений или путей с реальными именами в выводе.
    print(f"Обезличено сообщений: {report['messages']}; замен имён: {report.get('names', 0)}; "
          f"телефонов: {report.get('phones', 0)}; ссылок: {report.get('links', 0)}; "
          f"ников: {report.get('nicks', 0)}; неопознанных авторов: {report.get('unknown_authors', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
