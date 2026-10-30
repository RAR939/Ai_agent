# eval/corpus_stats.py
"""Агрегированная статистика локального корпуса Telegram без публикации текстов и ФИО."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup, Tag

try:
    from src.schemas import Message
except ModuleNotFoundError as exc:
    if exc.name not in {"src.schemas", "src"}:
        raise
    from schemas import Message


_HTML_RE = re.compile(r"messages(\d*)\.html\Z")
_WORDS = re.compile(r"[^\W\d_]+", re.UNICODE)
_FILE_EXT = re.compile(r"\.([a-zA-Z0-9]{1,8})(?=\s|$|[)\]])")
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_MASK = re.compile(r"\[[А-ЯЁA-Z_]+\]")
_SPACE = re.compile(r"\s+")
_ROLES = ("starosta", "teacher", "student", "unknown")


def _quality_settings(config: dict) -> dict:
    """Все регулируемые пороги и пути отчётов задаются в config/config.yaml."""
    keys = ("dominant_author_share", "english_min_letters", "english_latin_share",
            "broadcast_min_repeats", "broadcast_min_chars", "max_anomaly_dates", "report_md", "report_csv")
    settings = config.get("quality")
    if not isinstance(settings, dict) or any(k not in settings for k in keys):
        raise ValueError("В config/config.yaml отсутствуют параметры quality для задачи 2.5")
    if not 0 < settings["dominant_author_share"] <= 1:
        raise ValueError("quality.dominant_author_share должен быть в (0, 1]")
    if not 0 < settings["english_latin_share"] <= 1:
        raise ValueError("quality.english_latin_share должен быть в (0, 1]")
    for key in ("english_min_letters", "broadcast_min_repeats", "broadcast_min_chars", "max_anomaly_dates"):
        if not isinstance(settings[key], int) or settings[key] < 1:
            raise ValueError(f"Неверный параметр quality.{key}")
    return settings


def _load_messages(path: Path, chat_id: str) -> list[Message]:
    """Загрузить чистые сообщения через исходную Pydantic-схему."""
    if not path.is_file():
        raise FileNotFoundError("Не найден очищенный JSONL; сначала завершите задачу 2.4")
    result: list[Message] = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                message = Message.model_validate_json(line)
                if message.chat != chat_id:
                    raise ValueError("В JSONL обнаружен чужой идентификатор чата")
                result.append(message)
    return result


def _html_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    result: list[tuple[int, Path]] = []
    for path in folder.iterdir():
        match = _HTML_RE.fullmatch(path.name)
        if path.is_file() and match:
            result.append((int(match.group(1) or 1), path))
    return [path for _, path in sorted(result, key=lambda item: (item[0], item[1].name))]


def _html_text(block: Tag) -> str:
    body = block.select_one("div.body")
    if body is None:
        return ""
    texts = body.select("div.text")
    return " ".join(node.get_text(" ", strip=True) for node in texts).strip()


def _raw_metrics(folder: Path, extensions: set[str], quality: dict) -> dict[str, Any] | None:
    """Агрегаты HTML до очистки; личные данные не возвращаются."""
    files = _html_files(folder)
    if not files:
        return None
    counts: Counter[str] = Counter()
    missing_keys: set[tuple[str, str]] = set()
    unique_files: set[str] = set()
    ext_counter: Counter[str] = Counter()
    seen_message_ids: set[str] = set()
    timestamps: list[datetime] = []
    raw_bodies: Counter[str] = Counter()
    for html in files:
        soup = BeautifulSoup(html.read_text(encoding="utf-8-sig"), "lxml")
        for message in soup.select("div.message"):
            counts["raw_messages"] += 1
            msg_id = message.get("id", "")
            if msg_id in seen_message_ids:
                counts["raw_duplicate_ids"] += 1
            seen_message_ids.add(msg_id)
            if "service" in message.get("class", []):
                counts["service_messages"] += 1
                continue
            counts["raw_regular"] += 1
            visible_text = _html_text(message)
            if not visible_text:
                counts["raw_empty_text"] += 1
            else:
                raw_bodies[_normalize(visible_text)] += 1
                if _english_message(visible_text, quality):
                    counts["raw_english_messages"] += 1
            if message.select_one('div.reply_to.details a[href*="go_to_message"]'):
                counts["raw_replies"] += 1
            date_node = message.select_one("div.date.details[title]")
            if date_node is not None:
                title = date_node.get("title", "")
                for fmt, date_only in (("%d.%m.%Y %H:%M:%S GMT%z", False),
                                       ("%d.%m.%Y %H:%M:%S %z", False),
                                       ("%d.%m.%Y GMT%z", True), ("%d.%m.%Y %z", True)):
                    try:
                        parsed = datetime.strptime(title.strip(), fmt)
                    except ValueError:
                        continue
                    if date_only:
                        parsed = parsed.replace(hour=23, minute=59, second=0)
                    timestamps.append(parsed.astimezone(ZoneInfo("Europe/Moscow")))
                    break
            has_document = False
            # Важны как ссылки с классом media_file, так и любые href=files/*.
            for link in message.select('a[href]'):
                relative = unquote(urlsplit(link.get("href", "")).path)
                if not relative.startswith("files/"):
                    continue
                p = PurePosixPath(relative)
                ext = p.suffix.lower().lstrip(".")
                if ext not in extensions:
                    continue
                has_document = True
                counts["raw_document_links"] += 1
                ext_counter[ext] += 1
                local_file = folder.joinpath(*p.parts)
                if (".." in p.parts or "\\" in relative or
                        not local_file.resolve().is_relative_to(folder.resolve()) or
                        not local_file.is_file()):
                    missing_keys.add((msg_id, relative))
                else:
                    unique_files.add(relative)
                    counts["raw_available_document_links"] += 1
            for media in message.select("div.media_file"):
                if media.select_one('a[href]'):
                    continue
                labels = " ".join(n.get_text(" ", strip=True) for n in media.select(".title, .name"))
                match = _FILE_EXT.search(labels.casefold())
                if match is not None and match.group(1) in extensions:
                    has_document = True
                    counts["raw_document_without_link"] += 1
                    ext_counter[match.group(1)] += 1
                    missing_keys.add((msg_id, f"no_href:{len(missing_keys)}"))
            counts["raw_file_messages"] += has_document
    counts["raw_missing_documents"] = len(missing_keys)
    counts["raw_duplicate_texts"] = sum(n - 1 for n in raw_bodies.values() if n > 1)
    repeated = [n for text, n in raw_bodies.items() if n >= quality["broadcast_min_repeats"]
                and len(text) >= quality["broadcast_min_chars"]]
    counts["raw_repeated_broadcast_groups"] = len(repeated)
    counts["raw_repeated_broadcast_messages"] = sum(repeated)
    unique_days = {ts.date() for ts in timestamps}
    if unique_days:
        day = min(unique_days) + timedelta(days=1)
        until = max(unique_days)
        while day < until:
            counts["raw_silent_days"] += day not in unique_days
            day += timedelta(days=1)
    counts["raw_distinct_downloaded_files"] = len(unique_files)
    counts["raw_unique_file_bytes"] = sum((folder / p).stat().st_size for p in unique_files)
    result: dict[str, Any] = {**{k: 0 for k in ("raw_messages", "service_messages", "raw_regular",
        "raw_empty_text", "raw_replies", "raw_duplicate_ids", "raw_duplicate_texts", "raw_file_messages",
        "raw_silent_days", "raw_english_messages", "raw_repeated_broadcast_groups", "raw_repeated_broadcast_messages",
        "raw_document_links", "raw_document_without_link", "raw_missing_documents",
        "raw_available_document_links", "raw_distinct_downloaded_files", "raw_unique_file_bytes")},
        **dict(counts)}
    result["raw_period_from"] = min(timestamps).isoformat(timespec="seconds") if timestamps else None
    result["raw_period_to"] = max(timestamps).isoformat(timespec="seconds") if timestamps else None
    result["raw_extensions"] = dict(sorted(ext_counter.items()))
    return result


def _normalize(text: str) -> str:
    return _SPACE.sub(" ", text).strip().casefold()


def _english_message(text: str, settings: dict) -> bool:
    without_links = _MASK.sub(" ", _URL.sub(" ", text))
    latin = sum(ch.isascii() and ch.isalpha() for ch in without_links)
    cyrillic = sum("а" <= ch.lower() <= "я" or ch.lower() == "ё" for ch in without_links)
    return latin >= settings["english_min_letters"] and latin / max(latin + cyrillic, 1) >= settings["english_latin_share"]


def _deadline_lemmas(config: dict, morph: Any) -> set[str]:
    tracker = config.get("tracker", {})
    words = tracker.get("prefilter_keywords")
    strong = tracker.get("prefilter_strong_keywords", [])
    if not isinstance(words, list) or not isinstance(strong, list):
        raise ValueError("В config/config.yaml отсутствуют tracker.prefilter_keywords")
    return {morph.parse(word)[0].normal_form for word in words + strong if isinstance(word, str)}


def _has_deadline_signal(text: str, lemmas: set[str], morph: Any) -> bool:
    # Признак срока, а не утверждение, что найден истинный дедлайн.
    return any(morph.parse(word)[0].normal_form in lemmas for word in _WORDS.findall(text))


def corpus_stats(
    chat_id: str,
    messages: list[Message] | None,
    config: dict,
    raw_folder: Path | None = None,
    morph: Any | None = None,
) -> dict[str, Any]:
    """Вернуть только безопасные агрегаты; None означает «не рассчитано»."""
    quality = _quality_settings(config)
    raw = _raw_metrics(raw_folder, set(config["tracker"]["attach_exts"]), quality) if raw_folder else None
    stats: dict[str, Any] = {"chat": chat_id, "raw": raw, "clean_available": messages is not None,
                             "metrics": {}, "role_messages": {}, "role_authors": {},
                             "extensions": {}, "anomalies": {}, "warnings": []}
    if messages is None:
        stats["warnings"].append("Нет проверенного обезличенного JSONL: показатели после очистки не рассчитаны")
        return stats
    if any(m.chat != chat_id for m in messages):
        raise ValueError("В списке обнаружены сообщения другого чата")
    counts: Counter[str] = Counter()
    authors_by_role: dict[str, set[str]] = {role: set() for role in _ROLES}
    by_author: Counter[str] = Counter()
    by_day: Counter[date] = Counter()
    body_counts: Counter[str] = Counter()
    extensions: Counter[str] = Counter()
    attachment_missing: set[tuple[str, str]] = set()
    timestamps: list[datetime] = []
    for message in messages:
        counts["messages"] += 1
        counts[f"role_{message.role}"] += 1
        authors_by_role[message.role].add(message.author)
        by_author[message.author] += 1
        counts["replies"] += message.reply_to is not None
        counts["with_files"] += bool(message.attachments)
        counts["files"] += len(message.attachments)
        dt = datetime.fromisoformat(message.ts)
        timestamps.append(dt)
        by_day[dt.date()] += 1
        norm = _normalize(message.text)
        if norm:
            body_counts[norm] += 1
        if _english_message(message.text, quality):
            counts["english_messages"] += 1
        for attachment in message.attachments:
            extensions[attachment.ext.lower()] += 1
            counts["total_size_bytes"] += attachment.size_bytes
            if raw_folder is not None:
                p = PurePosixPath(attachment.path)
                actual = raw_folder.joinpath(*p.parts)
                if (not p.parts or ".." in p.parts or "\\" in attachment.path or
                        not actual.resolve().is_relative_to(raw_folder.resolve()) or
                        not actual.is_file()):
                    attachment_missing.add((message.id, attachment.path))
    metrics: dict[str, Any] = {
        "messages": counts["messages"], "authors": len(by_author),
        "period_from": min(timestamps).isoformat(timespec="seconds") if timestamps else None,
        "period_to": max(timestamps).isoformat(timespec="seconds") if timestamps else None,
        "replies": counts["replies"], "duplicate_ids": counts["messages"] - len({m.id for m in messages}),
        "duplicate_texts": sum(max(n - 1, 0) for n in body_counts.values()),
        "with_files": counts["with_files"], "files": counts["files"],
        "file_message_share": counts["with_files"] / len(messages) if messages else None,
        "total_size_bytes": counts["total_size_bytes"],
        "missing_files_on_disk": (
            raw.get("raw_missing_documents", 0) if raw is not None else
            len(attachment_missing) if raw_folder is not None else None),
        "deadline_signals": None,
    }
    if messages:
        if morph is None:
            try:
                import pymorphy3
            except ImportError:
                stats["warnings"].append("pymorphy3 недоступен: признаки сроков по леммам не рассчитаны")
            else:
                morph = pymorphy3.MorphAnalyzer()
        if morph is not None:
            lemmas = _deadline_lemmas(config, morph)
            metrics["deadline_signals"] = sum(_has_deadline_signal(m.text, lemmas, morph) for m in messages)
    else:
        metrics["deadline_signals"] = 0
    stats["metrics"] = metrics
    stats["role_messages"] = {role: counts[f"role_{role}"] for role in _ROLES}
    stats["role_authors"] = {role: len(authors_by_role[role]) for role in _ROLES}
    stats["extensions"] = dict(sorted(extensions.items()))
    start, end = (min(by_day), max(by_day)) if by_day else (None, None)
    missed: list[str] = []
    missing_days = 0
    if start is not None and end is not None:
        day = start + timedelta(days=1)
        while day < end:
            if day not in by_day:
                missing_days += 1
                if len(missed) < quality["max_anomaly_dates"]:
                    missed.append(day.isoformat())
            day += timedelta(days=1)
    dominant = sum(1 for n in by_author.values() if messages and n / len(messages) >= quality["dominant_author_share"])
    broadcasts = [n for text, n in body_counts.items() if n >= quality["broadcast_min_repeats"]
                  and len(text) >= quality["broadcast_min_chars"]]
    stats["anomalies"] = {
        "dominant_authors": dominant,
        "maximum_author_share": max(by_author.values(), default=0) / len(messages) if messages else None,
        "silent_days": missing_days,
        "silent_day_examples": missed,
        "english_messages": counts["english_messages"],
        "repeated_broadcast_groups": len(broadcasts),
        "repeated_broadcast_messages": sum(broadcasts),
    }
    return stats


_METRIC_NAMES = [
    ("raw.raw_messages", "Сообщений в HTML до очистки"),
    ("raw.raw_period_from", "Начало периода в HTML, ISO +03:00"),
    ("raw.raw_period_to", "Конец периода в HTML, ISO +03:00"),
    ("raw.raw_regular", "Обычных блоков HTML"),
    ("raw.service_messages", "Служебных блоков HTML"),
    ("raw.service_share", "Доля служебных блоков до очистки"),
    ("raw.raw_empty_text", "Без текста до очистки (без service)"),
    ("raw.raw_replies", "Ответов в HTML до очистки"),
    ("raw.raw_duplicate_ids", "Повторных ID в HTML"),
    ("raw.raw_duplicate_texts", "Повторов текста в HTML"),
    ("raw.raw_silent_days", "Дней без сообщений внутри сырого периода"),
    ("raw.raw_english_messages", "Преимущественно английских сообщений в HTML"),
    ("raw.raw_repeated_broadcast_groups", "Групп повторяющихся рассылок в HTML"),
    ("raw.raw_repeated_broadcast_messages", "Сообщений в рассылках в HTML"),
    ("raw.empty_share", "Доля блоков без текста до очистки"),
    ("metrics.messages", "Сообщений после очистки"),
    ("metrics.authors", "Уникальных авторов"),
    ("metrics.period_from", "Начало периода ISO +03:00"),
    ("metrics.period_to", "Конец периода ISO +03:00"),
    ("metrics.replies", "Сообщений-ответов"),
    ("metrics.deadline_signals", "Сообщений с признаками срока"),
    ("metrics.duplicate_ids", "Дублирующихся ID (сверх первого)"),
    ("metrics.duplicate_texts", "Повторов текста (сверх первого)"),
    ("metrics.files", "Вложений в Message"),
    ("metrics.with_files", "Сообщений с вложениями"),
    ("metrics.file_message_share", "Доля сообщений с вложениями"),
    ("metrics.missing_files_on_disk", "Отсутствующих документов на диске"),
    ("raw.raw_document_links", "Ссылок на документы в HTML"),
    ("raw.raw_available_document_links", "Доступных ссылок на документы в HTML"),
    ("raw.raw_file_messages", "Обычных HTML-сообщений с документами"),
    ("raw.raw_file_message_share", "Доля обычных HTML-сообщений с документами"),
    ("raw.raw_distinct_downloaded_files", "Различных скачанных документов"),
    ("raw.raw_unique_file_bytes", "Размер различных скачанных документов, байт"),
    ("raw.raw_missing_documents", "Отсутствующих документов в HTML"),
    ("raw.raw_document_without_link", "Документов без ссылки в HTML"),
    ("metrics.total_size_bytes", "Общий размер вложений, байт"),
    ("anomalies.dominant_authors", "Авторов с долей сообщений ≥ порога"),
    ("anomalies.maximum_author_share", "Максимальная доля одного автора"),
    ("anomalies.silent_days", "Дней без сообщений внутри периода"),
    ("anomalies.english_messages", "Сообщений преимущественно на английском"),
    ("anomalies.repeated_broadcast_groups", "Групп повторяющихся рассылок"),
    ("anomalies.repeated_broadcast_messages", "Сообщений в повторяющихся рассылках"),
]


def _get(report: dict, key: str) -> Any:
    if key == "raw.raw_file_message_share":
        raw = report.get("raw")
        return raw.get("raw_file_messages", 0) / raw["raw_regular"] if raw and raw["raw_regular"] else None
    if key == "raw.service_share":
        raw = report.get("raw")
        return raw.get("service_messages", 0) / raw["raw_messages"] if raw and raw["raw_messages"] else None
    if key == "raw.empty_share":
        raw = report.get("raw")
        return raw.get("raw_empty_text", 0) / raw["raw_messages"] if raw and raw["raw_messages"] else None
    if key.startswith("raw.raw_extensions."):
        raw = report.get("raw")
        return raw.get("raw_extensions", {}).get(key.rsplit(".", 1)[-1], 0) if raw is not None else None
    section, item = key.split(".")
    obj = report.get(section)
    return obj.get(item, 0) if isinstance(obj, dict) else None


def _format(value: Any) -> str:
    if value is None:
        return "не рассчитано"
    if isinstance(value, float):
        return f"{value * 100:.2f}%"
    return str(value)


def _total(reports: list[dict], key: str) -> Any:
    values = [_get(report, key) if report["clean_available"] or key.startswith("raw.") else None for report in reports]
    if not values or any(v is None for v in values):
        return None
    if key.endswith(("period_from", "period_to")):
        return min(values) if key.endswith("period_from") else max(values)
    if key in {"metrics.file_message_share", "raw.service_share", "raw.empty_share",
               "anomalies.maximum_author_share", "raw.raw_file_message_share"}:
        if key == "metrics.file_message_share":
            total_messages = sum(_get(r, "metrics.messages") for r in reports)
            return sum(_get(r, "metrics.with_files") for r in reports) / total_messages if total_messages else None
        if key == "raw.raw_file_message_share":
            denominator = sum(r["raw"]["raw_regular"] for r in reports)
            return sum(r["raw"]["raw_file_messages"] for r in reports) / denominator if denominator else None
        if key in {"raw.service_share", "raw.empty_share"}:
            numerator = "service_messages" if key == "raw.service_share" else "raw_empty_text"
            denominator = sum(r["raw"]["raw_messages"] for r in reports)
            return sum(r["raw"].get(numerator, 0) for r in reports) / denominator if denominator else None
        return max(values)
    # Повторы текста и число уникальных авторов между чатами нельзя суммировать
    # как единый корпус без разрешения межчатовых коллизий.
    if key in {"metrics.authors", "metrics.duplicate_texts", "anomalies.repeated_broadcast_groups", "raw.raw_silent_days"}:
        return None
    return sum(values) if all(isinstance(v, (float, int)) for v in values) else None


def write_reports(reports: list[dict], md_path: Path, csv_path: Path, config: dict) -> None:
    """Записать сводку без имён, исходных сообщений и ссылок на локальные файлы."""
    quality = _quality_settings(config)
    chats = [r["chat"] for r in reports]
    # Метрики авторов по ролям/типам вложений формируются динамически.
    extra = [(f"role_messages.{role}", f"Сообщений: {role}") for role in _ROLES]
    extra += [(f"role_authors.{role}", f"Уникальных авторов: {role}") for role in _ROLES]
    ext_keys = sorted({ext for r in reports for ext in r.get("extensions", {})})
    raw_ext_keys = sorted({ext for r in reports if r.get("raw") for ext in r["raw"]["raw_extensions"]})
    extra += [(f"extensions.{ext}", f"Вложений с расширением .{ext}") for ext in ext_keys]
    extra += [(f"raw.raw_extensions.{ext}", f"Вложений в HTML с расширением .{ext}") for ext in raw_ext_keys]
    rows: list[list[str]] = []
    for key, title in [*_METRIC_NAMES, *extra]:
        values = [_get(report, key) if report["clean_available"] or key.startswith("raw.") else None for report in reports]
        total = (_total(reports, key) if key in dict(_METRIC_NAMES)
                 else None if key.startswith("role_authors.")
                 else sum(values) if all(v is not None for v in values) else None)
        rows.append([title, *(_format(v) for v in values), _format(total)])
    md_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Показатель", *chats, "Итого"])
        writer.writerows(rows)
    preclean_only = any(not r["clean_available"] for r in reports)
    lines = ["# Описание корпуса учебных чатов", "",
             "## Статус данных", "",
             "**Предварительный отчёт:** отсутствующие показатели отмечены «не рассчитано»." if preclean_only
             else "**Сводка по обезличенным сообщениям:** необходим независимый ручной аудит приватности.",
             "", "Тексты сообщений, имена людей, названия документов и пути к ним в этот отчёт не включены.",
             ""]
    if reports and all(r.get("raw") is not None for r in reports):
        raw_total = sum(r["raw"]["raw_messages"] for r in reports)
        service = sum(r["raw"]["service_messages"] for r in reports)
        empty = sum(r["raw"]["raw_empty_text"] for r in reports)
        files = sum(r["raw"]["raw_distinct_downloaded_files"] for r in reports)
        bytes_total = sum(r["raw"]["raw_unique_file_bytes"] for r in reports)
        missing = sum(r["raw"]["raw_missing_documents"] for r in reports)
        begins = [r["raw"]["raw_period_from"] for r in reports if r["raw"]["raw_period_from"]]
        ends = [r["raw"]["raw_period_to"] for r in reports if r["raw"]["raw_period_to"]]
        start = min(begins) if begins else "не рассчитано"
        end = max(ends) if ends else "не рассчитано"
        service_share = f"{service / raw_total:.2%}" if raw_total else "не рассчитано"
        empty_share = f"{empty / raw_total:.2%}" if raw_total else "не рассчитано"
        lines += ["## Краткая характеристика корпуса (до очистки)", "",
                  f"В {len(reports)} экспортированных чатах за период с {start} по {end} обнаружено "
                  f"{raw_total} блоков сообщений, включая {service} служебных ({service_share}). "
                  f"Без видимого текста обнаружено {empty} обычных сообщений ({empty_share} всех блоков). "
                  f"Среди разрешённых форматов найдено {files} различных выгруженных файлов "
                  f"общим объёмом {bytes_total / 1_000_000:.2f} МБ; недоступных документов — {missing}. "
                  "Статистика авторов, ролей и признаков сроков требует очищенных сообщений.", ""]
    lines += ["## Сводная таблица", "",
             "| " + " | ".join(["Показатель", *chats, "Итого"]) + " |",
             "| " + " | ".join(["---", *["---:" for _ in range(len(chats) + 1)]]) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    lines.extend(["", "## Методика", "",
                  "- До очистки: `div.message` из `messages*.html` в числовом порядке; `service` учитываются отдельно.",
                  "- Пустое до очистки: обычное сообщение без видимого `div.text`; сообщение только с документом считается без текста до подстановки подписи.",
                  "- Дубли ID — повторения идентификаторов; дубли текста — повторения нормализованной строки в пределах одного чата.",
                  "- Признаки срока: леммы слов сообщения, совпадающие с `tracker.prefilter_keywords` и `tracker.prefilter_strong_keywords`; это НЕ точность извлечения дедлайнов.",
                  "- Отсутствующие документы: ссылки на разрешённые расширения с отсутствующим локальным файлом и распознанные `media_file` без ссылки в исходном HTML.",
                  "- `raw_file_messages` учитывает в том числе документы без ссылки; знаменатель сырой доли — обычные сообщения HTML, без служебных.",
                  "- Размер в HTML — сумма размеров разных скачанных документов; размер в Message — сумма `AttachedFile.size_bytes` (один файл может учитываться в нескольких сообщениях).",
                  "- Расширения берутся только из `tracker.attach_exts`; например, неподдерживаемые форматы не учитываются как документы.",
                  "- Доли сообщений: знаменатель — число очищенных Message. Доли до очистки: знаменатель — все `div.message`, включая служебные.",
                  "- Уникальные авторы по чатам и по ролям не складываются: один человек может участвовать в обоих чатах.",
                  "- `reply_to` в Telegram может отражать ответ на сообщение-основу темы; количество HTML-ответов не обязательно равно числу содержательных дискуссионных реплик.",
                  "- Повторы между чатами в колонке «Итого» не агрегируются без безопасного межчатового сопоставления.",
                  "- Английский язык определяется эвристикой по доле латинских букв, без вывода примеров в отчёт.",
                  f"- Порог доли доминирующего автора: {quality['dominant_author_share']:.0%}; потенциальная рассылка — не менее {quality['broadcast_min_repeats']} одинаковых сообщений длиной от {quality['broadcast_min_chars']} символов.",
                  "- Обнаружение повторяющихся рассылок — эвристика: идентичные тексты могут быть обычными сообщениями, а изменённые рассылки могут не обнаружиться.",
                  "", "## Обнаруженные аномалии", ""])
    for report in reports:
        anon = report.get("anomalies", {})
        if not anon:
            raw = report.get("raw")
            if raw:
                lines.append(f"- **{report['chat']}**, до очистки: дней без сообщений — {raw['raw_silent_days']}; "
                             f"преимущественно английских сообщений — {raw['raw_english_messages']}; "
                             f"групп повторяющихся рассылок — {raw['raw_repeated_broadcast_groups']}. "
                             "Доминирование автора по ролям не проверено.")
            else:
                lines.append(f"- **{report['chat']}**: аномалии после очистки не проверены.")
            continue
        sample_dates = anon.get("silent_day_examples", [])
        dates = ", ".join(sample_dates) if sample_dates else "нет"
        lines.append(f"- **{report['chat']}**: доминирующих авторов — {anon['dominant_authors']}; "
                     f"дней без сообщений — {anon['silent_days']} (примеры дат: {dates}); "
                     f"сообщений на английском — {anon['english_messages']}; "
                     f"групп повторяющихся рассылок — {anon['repeated_broadcast_groups']}.")
    warnings = sorted({w for r in reports for w in r["warnings"]})
    if warnings:
        lines.extend(["", "## Ограничения и недостающие проверки", ""])
        lines += [f"- {warning}" for warning in warnings]
    lines.extend(["- Утверждать отсутствие персональных данных можно только после трёх независимых ручных выборок по 100 сообщений.",
                  "- `attachments[].path` может содержать личные сведения; исходные файлы и очищенные JSONL не включаются в отчёт и PR.",
                  ""])
    md_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    cli = argparse.ArgumentParser(description="Локальная статистика корпуса без вывода персональных данных")
    cli.add_argument("--chat", action="append", required=True, help="ID чата, допускается несколько раз")
    cli.add_argument("--allow-missing-clean", action="store_true", help="Предварительная статистика HTML без очищенного JSONL")
    args = cli.parse_args()
    try:
        from src.ingest.parse_telegram_html import _load_project_config
        config = _load_project_config()
        settings = _quality_settings(config)
        root = Path(config["paths"]["data"])
        reports = []
        for chat in args.chat:
            # Нельзя выходить за пределы data/ через идентификатор чата.
            if not chat or not re.fullmatch(r"[A-Za-z0-9_-]+", chat):
                raise ValueError("Некорректный идентификатор чата")
            clean_path = root / "clean" / f"{chat}.jsonl"
            messages = (_load_messages(clean_path, chat) if clean_path.is_file() else
                        None if args.allow_missing_clean else _load_messages(clean_path, chat))
            raw_path = root / "raw" / chat
            reports.append(corpus_stats(chat, messages, config, raw_path if raw_path.is_dir() else None))
        write_reports(reports, Path(settings["report_md"]), Path(settings["report_csv"]), config)
        print(f"Проанализировано чатов: {len(reports)}; предварительных: {sum(not r['clean_available'] for r in reports)}")
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        # Ошибки не печатают имена файлов и фрагменты переписки.
        print(json.dumps({"error": f"Не удалось сформировать отчёт: {type(exc).__name__}. Проверьте конфигурацию и локальные данные"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
