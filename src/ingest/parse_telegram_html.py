# src/ingest/parse_telegram_html.py
"""Парсер HTML-экспорта Telegram Desktop в Message (Python 3.11)."""

from __future__ import annotations

import argparse
from datetime import datetime
import importlib
import json
import logging
from pathlib import Path, PurePosixPath
import re
import sys
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

try:
    from src.schemas import AttachedFile, Message
except ModuleNotFoundError as exc:
    if exc.name not in {"src.schemas", "src"}:
        raise
    from schemas import AttachedFile, Message


logger = logging.getLogger(__name__)
_HTML_PATTERN = re.compile(r"^messages(\d*)\.html$")
_MESSAGE_PATTERN = re.compile(r"^message(\d+)$")
_REPLY_PATTERN = re.compile(r"#go_to_message(\d+)$")
_MOSCOW = ZoneInfo("Europe/Moscow")


def _load_project_config() -> dict:
    """Вызывает проектный load_config(); путь импорта зависит от сборки роли 1."""
    for module_name in ("src.config", "config.loader", "config"):
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name not in {module_name, module_name.split(".")[0]}:
                raise
            continue
        loader = getattr(module, "load_config", None)
        if callable(loader):
            config = loader()
            if not isinstance(config, dict):
                raise TypeError("load_config() должен возвращать словарь настроек")
            return config
    raise RuntimeError("Не найдена функция load_config() проекта; уточните модуль роли 1")


def _document_exts() -> set[str]:
    config = _load_project_config()
    tracker = config.get("tracker")
    if not isinstance(tracker, dict) or not isinstance(tracker.get("attach_exts"), (list, tuple, set)):
        raise ValueError("В config/config.yaml отсутствует список tracker.attach_exts")
    return {str(ext).lower().lstrip(".") for ext in tracker["attach_exts"] if str(ext).strip()}


def _html_files(folder: Path) -> list[Path]:
    numbered: list[tuple[int, Path]] = []
    for file in folder.iterdir():
        match = _HTML_PATTERN.fullmatch(file.name)
        if file.is_file() and match:
            numbered.append((int(match.group(1)) if match.group(1) else 1, file))
    return [file for _, file in sorted(numbered, key=lambda x: (x[0], x[1].name))]


def _direct_child(block: Tag | None, *classes: str) -> Tag | None:
    if block is None:
        return None
    for child in block.find_all("div", recursive=False):
        if set(classes).issubset(set(child.get("class", []))):
            return child
    return None


def _parse_ts(title: str) -> str:
    """Преобразовать время экспорта в ISO 8601 с московским поясом."""
    formats = (
        ("%d.%m.%Y %H:%M:%S GMT%z", False),
        ("%d.%m.%Y %H:%M:%S %z", False),
        ("%d.%m.%Y GMT%z", True),
        ("%d.%m.%Y %z", True),
    )
    for pattern, date_only in formats:
        try:
            parsed = datetime.strptime(title.strip(), pattern)
        except ValueError:
            continue
        if date_only:
            parsed = parsed.replace(hour=23, minute=59, second=0)
        return parsed.astimezone(_MOSCOW).isoformat(timespec="seconds")
    raise ValueError("В HTML обнаружено время без поддерживаемого часового пояса")


def _clean_text(node: Tag | None) -> str:
    if node is None:
        return ""
    # Копия блока: исходный HTML остаётся пригодным для разбора вложений.
    copy = BeautifulSoup(str(node), "lxml").find(class_="text")
    if copy is None:
        return ""
    for link in list(copy.find_all("a", href=True)):
        label = link.get_text(" ", strip=True)
        href = link["href"].strip()
        visible = label if label == href or not href else f"{label} ({href})" if label else href
        link.replace_with(visible)
    for br in list(copy.find_all("br")):
        br.replace_with("\n")
    for element in list(copy.find_all(True)):
        if element.name in {"b", "strong", "em", "i", "u", "s", "span", "code", "pre", "a"}:
            element.unwrap()
    copy.smooth()
    raw = copy.get_text("\n")
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in raw.splitlines()]
    return "\n".join(lines).strip()


def _attachments(
    body: Tag,
    folder: Path,
    msg_id: str,
    allowed_exts: set[str],
) -> list[AttachedFile]:
    result: list[AttachedFile] = []
    visited: set[str] = set()
    for link in body.find_all("a", href=True):
        href = link["href"]
        relative = unquote(urlsplit(href).path)
        # Ссылки наружу, на фото и попытки выйти из папки экспорта запрещены.
        if not relative.startswith("files/") or relative in visited:
            continue
        visited.add(relative)
        relative_posix = PurePosixPath(relative)
        if ".." in relative_posix.parts or "\\" in relative:
            logger.warning("Небезопасная ссылка на вложение у сообщения %s", msg_id)
            continue
        ext = relative_posix.suffix.lower().lstrip(".")
        if ext not in allowed_exts:
            continue
        local_file = folder.joinpath(*relative_posix.parts)
        if not local_file.resolve().is_relative_to(folder.resolve()) or not local_file.is_file():
            logger.warning("Файл вложения отсутствует на диске у сообщения %s", msg_id)
            continue
        number = len(result) + 1
        # Без публикации исходного названия: окончательная анонимизация в задаче 2.4.
        safe_name = f"document_{msg_id.rsplit(':', 1)[-1]}_{number}.{ext}"
        result.append(
            AttachedFile(
                id=f"{msg_id}:f{number}",
                msg_id=msg_id,
                name=safe_name,
                ext=ext,
                size_bytes=local_file.stat().st_size,
                path=relative_posix.as_posix(),
                bind=None,
            )
        )
    return result


def parse_export(folder: str, chat_id: str) -> list[Message]:
    """Разобрать HTML-экспорт. Исходные тексты хранить только локально."""
    root = Path(folder)
    if not root.is_dir():
        raise FileNotFoundError("Папка экспорта не найдена")
    if not chat_id or ":" in chat_id:
        raise ValueError("Некорректный идентификатор чата")

    allowed_exts = _document_exts()
    messages: list[Message] = []
    # Исходные имена используются только как временные ключи внутри процесса.
    authors: dict[str, str] = {}
    last_author = "UNKNOWN"
    for html_file in _html_files(root):
        soup = BeautifulSoup(html_file.read_text(encoding="utf-8-sig"), "lxml")
        for block in soup.select("div.message"):
            if "service" in block.get("class", []):
                continue
            match = _MESSAGE_PATTERN.fullmatch(block.get("id", ""))
            if match is None:
                continue
            msg_id = f"{chat_id}:{match.group(1)}"
            body = _direct_child(block, "body")
            if body is None:
                continue

            source_author = _direct_child(body, "from_name")
            if source_author is not None:
                author_name = source_author.get_text(" ", strip=True)
                if author_name:
                    if author_name not in authors:
                        authors[author_name] = f"UNKNOWN_{len(authors) + 1}"
                    last_author = authors[author_name]
            elif "joined" not in block.get("class", []):
                last_author = "UNKNOWN"

            date = _direct_child(body, "date", "details")
            if date is None or not date.get("title"):
                logger.warning("У сообщения %s не найдено время", msg_id)
                continue
            try:
                ts = _parse_ts(str(date["title"]))
            except ValueError:
                logger.warning("У сообщения %s неподдерживаемый формат времени", msg_id)
                continue

            forwarded_body = _direct_child(body, "forwarded", "body")
            text_parts = []
            outer_text = _direct_child(body, "text")
            if outer_text is not None:
                text_parts.append(_clean_text(outer_text))
            if forwarded_body is not None:
                forwarded_text = _direct_child(forwarded_body, "text")
                if forwarded_text is not None:
                    text_parts.append(_clean_text(forwarded_text))
            text_value = "\n".join(part for part in text_parts if part).strip()
            attachments = _attachments(body, root, msg_id, allowed_exts)
            if not text_value and attachments:
                text_value = f"[файл: {attachments[0].name}]"
            if not text_value:
                continue

            reply_to = None
            reply_box = _direct_child(body, "reply_to", "details")
            if reply_box is not None:
                reply_link = reply_box.find("a", href=True)
                if reply_link is not None:
                    reply_match = _REPLY_PATTERN.search(str(reply_link["href"]))
                    if reply_match:
                        reply_to = f"{chat_id}:{reply_match.group(1)}"
            messages.append(
                Message(
                    id=msg_id,
                    chat=chat_id,
                    ts=ts,
                    author=last_author,
                    role="unknown",
                    text=text_value,
                    reply_to=reply_to,
                    forwarded=forwarded_body is not None,
                    src=f"{html_file.name}#message{match.group(1)}",
                    attachments=attachments,
                )
            )
    return messages


def main() -> int:
    parser = argparse.ArgumentParser(description="Локальный разбор Telegram HTML в JSONL")
    parser.add_argument("folder", help="Папка HTML-экспорта")
    parser.add_argument("--chat", required=True, help="Код чата")
    parser.add_argument("--out", required=True, help="Путь к JSONL")
    args = parser.parse_args()
    try:
        messages = parse_export(args.folder, args.chat)
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8") as stream:
            for message in messages:
                stream.write(message.model_dump_json() + "\n")
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        # Не раскрываем в выводе исходные имена файлов и текст переписки.
        logger.debug("Ошибка %s", type(exc).__name__)
        print(json.dumps({"error": "Не удалось разобрать экспорт; проверьте путь и конфигурацию"}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(f"Сохранено сообщений: {len(messages)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
