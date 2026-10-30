# src/ingest/prepare_roles.py
"""Обогащает только ЛОКАЛЬНЫЙ roles.local.yaml авторами HTML-экспортов.

Не выводит имена участников. Требует предварительно составленный файл с особыми ролями.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import re
import unicodedata

from bs4 import BeautifulSoup
import yaml


_HTML = re.compile(r"messages(\d*)\.html\Z")
_TOKENS = re.compile(r"[A-Za-zА-Яа-яЁё]{4,}")


def _key(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _participants(roles: dict) -> dict[str, dict]:
    names = {}
    for person in roles["people"]:
        for alias in person["names"]:
            names.setdefault(_key(alias), person)
    return names


def discover_authors(roles: dict, exports: dict[str, Path]) -> dict:
    """Находит авторов локальных HTML и сопоставляет индексы UNKNOWN_N парсера."""
    if not isinstance(roles.get("people"), list):
        raise ValueError("Ожидается people в локальном справочнике")
    lookup = _participants(roles)
    labels = {p["label"] for p in roles["people"]}
    max_student = max((int(p["label"].split("_")[-1]) for p in roles["people"]
                       if re.fullmatch(r"STUDENT_\d+", p["label"])), default=0)
    mappings: dict[str, dict[str, str]] = {}
    for chat, folder in exports.items():
        if not folder.is_dir():
            raise FileNotFoundError("Папка локального HTML-экспорта не существует")
        htmls = []
        for p in folder.iterdir():
            match = _HTML.fullmatch(p.name)
            if p.is_file() and match:
                htmls.append((int(match.group(1) or 1), p))
        htmls.sort(key=lambda item: item[0])
        indexes: dict[str, int] = {}
        mapping: dict[str, str] = {}
        for _, html in htmls:
            soup = BeautifulSoup(html.read_text(encoding="utf-8-sig"), "lxml")
            for block in soup.select("div.message"):
                if "service" in block.get("class", []):
                    continue
                body = block.find("div", class_="body", recursive=False)
                if body is None:
                    continue
                from_name = body.find("div", class_="from_name", recursive=False)
                if from_name is None:
                    continue
                display_name = from_name.get_text(" ", strip=True)
                if not display_name:
                    continue
                if display_name in indexes:
                    continue
                indexes[display_name] = len(indexes) + 1
                key = _key(display_name)
                person = lookup.get(key)
                if person is None:
                    max_student += 1
                    label = f"STUDENT_{max_student}"
                    if label in labels:
                        raise ValueError("Конфликт метки участника")
                    labels.add(label)
                    person = {"label": label, "role": "student", "category": "student", "names": [display_name]}
                    roles["people"].append(person)
                    lookup[key] = person
                elif display_name not in person["names"]:
                    person["names"].append(display_name)
                mapping[f"UNKNOWN_{indexes[display_name]}"] = person["label"]
        mappings[chat] = mapping
    roles["authors_by_chat"] = mappings
    # Добавляем только уникальные компоненты имён, без предположений об уменьшительных.
    token_owners = {}
    for person in roles["people"]:
        for name in person["names"]:
            for word in _TOKENS.findall(name):
                token_owners.setdefault(_key(word), set()).add(person["label"])
    for person in roles["people"]:
        add = []
        for name in person["names"]:
            words = _TOKENS.findall(name)
            if len(words) < 2:
                continue
            for word in words:
                if token_owners[_key(word)] == {person["label"]} and word not in person["names"]:
                    add.append(word)
        person["names"].extend(dict.fromkeys(add))
    return roles


def main() -> int:
    parser = argparse.ArgumentParser(description="Локально связать авторов HTML с постоянными метками")
    parser.add_argument("--roles", required=True, help="Локальный roles.local.yaml")
    parser.add_argument("--export", nargs=2, action="append", required=True,
                        metavar=("CHAT", "FOLDER"), help="Код чата и папка HTML")
    args = parser.parse_args()
    location = Path(args.roles)
    with location.open(encoding="utf-8") as stream:
        roles = yaml.safe_load(stream)
    if not isinstance(roles, dict):
        raise ValueError("Локальный справочник не является YAML-словарём")
    exports = {chat: Path(folder) for chat, folder in args.export}
    enriched = discover_authors(roles, exports)
    # Используем запись с ограниченными правами на POSIX; на Windows ограничивает NTFS пользователь.
    import os
    import tempfile
    fd, temporary = tempfile.mkstemp(dir=location.parent, prefix=".roles_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            yaml.safe_dump(enriched, stream, allow_unicode=True, sort_keys=False)
        os.replace(temporary, location)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(f"Обновлён локальный справочник: {len(enriched['people'])} записей, "
          f"{len(exports)} чатов. Имена в вывод не включены.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
