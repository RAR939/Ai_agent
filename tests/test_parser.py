# tests/test_parser.py
"""Контрактные и граничные тесты HTML-парсера без реальных переписок."""

from __future__ import annotations

import importlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from types import ModuleType

import pytest
import yaml
from pydantic import ValidationError

try:
    from src.schemas import AttachedFile as ContractAttachedFile, Message as ContractMessage
except ModuleNotFoundError as exc:
    if exc.name not in {"src.schemas", "src"}:
        raise
    from schemas import AttachedFile as ContractAttachedFile, Message as ContractMessage


def _config_file() -> Path:
    """Найти присланную конфигурацию без изменения модулей другой роли."""
    candidates = (ROOT / "config" / "config.yaml", ROOT / "config.yaml")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("Для тестов нужен config/config.yaml")


@pytest.fixture
def parser(monkeypatch):
    # Реальные модели импортируются из schemas.py; подменяется лишь отсутствующий
    # в переданных материалах загрузчик конфигурации роли 1.
    config_module = ModuleType("src.config")

    def load_config() -> dict:
        with _config_file().open(encoding="utf-8") as stream:
            loaded = yaml.safe_load(stream)
        if not isinstance(loaded, dict):
            raise TypeError("Конфигурация должна быть словарём")
        return loaded

    config_module.load_config = load_config
    monkeypatch.setitem(sys.modules, "src.config", config_module)
    sys.modules.pop("src.ingest.parse_telegram_html", None)
    module = importlib.import_module("src.ingest.parse_telegram_html")
    yield module
    sys.modules.pop("src.ingest.parse_telegram_html", None)


def test_real_schema_and_config(parser):
    assert parser.Message is ContractMessage
    assert parser.AttachedFile is ContractAttachedFile
    config = parser._load_project_config()
    assert config["tracker"]["attach_exts"] == [
        "pdf", "docx", "doc", "xlsx", "pptx", "zip", "rar", "txt", "odt"
    ]
    assert parser._document_exts() == set(config["tracker"]["attach_exts"])
    with pytest.raises(ValidationError):
        ContractMessage(id="test:1", chat="test", ts="2026-10-21T14:03:00",
                        author="UNKNOWN", role="unknown", text="Тест", src="messages.html#message1")


def write_html(folder: Path, name: str, *blocks: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text("<html><body>" + "".join(blocks) + "</body></html>", encoding="utf-8")


def message(number: int, body: str, *, author: str | None = "Тестовый участник", joined: bool = False,
            date: str = "21.10.2026 14:03:00 GMT+03:00") -> str:
    author_html = f'<div class="from_name">{author}</div>' if author else ""
    joined_class = " joined" if joined else ""
    return (f'<div class="message default clearfix{joined_class}" id="message{number}">'
            f'<div class="body"><div class="pull_right date details" title="{date}">14:03</div>'
            f'{author_html}{body}</div></div>')


def test_empty_folder_and_missing_folder(parser, tmp_path):
    assert parser.parse_export(str(tmp_path), "test") == []
    with pytest.raises(FileNotFoundError):
        parser.parse_export(str(tmp_path / "not-found"), "test")


def test_numeric_order_and_joined_across_files(parser, tmp_path):
    write_html(tmp_path, "messages10.html", message(10, '<div class="text">Последнее</div>', author=None, joined=True))
    write_html(tmp_path, "messages2.html", message(2, '<div class="text">Второе</div>', author=None, joined=True))
    write_html(tmp_path, "messages.html", message(1, '<div class="text">Первое</div>'))
    results = parser.parse_export(str(tmp_path), "test")
    assert [m.id for m in results] == ["test:1", "test:2", "test:10"]
    assert results[0].author == results[1].author == results[2].author
    assert results[2].src == "messages10.html#message10"


def test_chat_id_independent_of_unfinished_disciplines(parser, tmp_path):
    # Идентификатор чата не обязан совпадать с ключом disciplines.yaml.
    write_html(tmp_path, "messages.html",
               message(1042, '<div class="text">Пример</div>'))
    record, = parser.parse_export(str(tmp_path), "IU5-31B")
    assert record.id == "IU5-31B:1042"
    assert record.chat == "IU5-31B"
    assert record.src == "messages.html#message1042"


def test_joined_at_export_start_is_unknown(parser, tmp_path):
    write_html(tmp_path, "messages.html", message(1, '<div class="text">Начало</div>', author=None, joined=True))
    record, = parser.parse_export(str(tmp_path), "test")
    assert record.author == "UNKNOWN"
    assert record.role == "unknown"


def test_reply_forward_and_author_not_taken_from_forward(parser, tmp_path):
    reply = '<div class="reply_to details"><a href="messages2.html#go_to_message999">Ответ</a></div>'
    forward = '<div class="forwarded body"><div class="from_name">Другой персонаж</div><div class="text">Пересланный текст</div></div>'
    write_html(tmp_path, "messages.html", message(1, reply + forward, author="Отправитель"))
    record, = parser.parse_export(str(tmp_path), "test")
    assert record.reply_to == "test:999"
    assert record.forwarded is True
    assert record.text == "Пересланный текст"
    assert record.author == "UNKNOWN_1"


def test_time_zone_converted_to_moscow(parser, tmp_path):
    write_html(tmp_path, "messages.html", message(1, '<div class="text">Урок</div>',
        date="21.10.2026 12:03:00 GMT+01:00"))
    record, = parser.parse_export(str(tmp_path), "test")
    assert record.ts == "2026-10-21T14:03:00+03:00"


def test_date_without_hour_becomes_2359(parser, tmp_path):
    write_html(tmp_path, "messages.html", message(
        1, '<div class="text">Тест</div>', date="21.10.2026 GMT+03:00"))
    record, = parser.parse_export(str(tmp_path), "test")
    assert record.ts == "2026-10-21T23:59:00+03:00"


def test_text_newlines_links_emojis_and_long_message(parser, tmp_path):
    long_text = "Пример" * 1200
    contents = (
        '<div class="text">Строка 1<br>Строка 2 <strong>важно</strong> '
        '<a href="https://example.org/materials">ссылка</a> 😊</div>'
    )
    link_only = '<div class="text"><a href="https://example.org/">https://example.org/</a></div>'
    write_html(tmp_path, "messages.html",
        message(1, contents),
        message(2, f'<div class="text">{long_text}</div>'),
        message(3, link_only),
    )
    first, second, third = parser.parse_export(str(tmp_path), "test")
    assert "Строка 1\nСтрока 2" in first.text
    assert "важно ссылка (https://example.org/materials) 😊" in first.text
    assert len(second.text) == len(long_text)
    assert third.text == "https://example.org/"


def test_empty_media_only_and_services_are_skipped(parser, tmp_path):
    write_html(tmp_path, "messages.html",
        '<div class="message service" id="message1"><div class="body details">Служебное событие</div></div>',
        message(2, '<div class="text"> </div>'),
        message(3, '<div class="media_photo"></div>'),
        message(4, '<div class="text">Нужное сообщение</div>'),
    )
    result = parser.parse_export(str(tmp_path), "test")
    assert [m.id for m in result] == ["test:4"]


def test_documents_with_and_without_caption_missing_and_ignored(parser, tmp_path, caplog):
    docs = tmp_path / "files"
    docs.mkdir()
    (docs / "example.pdf").write_bytes(b"PDF")
    (docs / "example.docx").write_bytes(b"DOCX")
    (docs / "picture.png").write_bytes(b"PNG")
    media = '<div class="media_wrap clearfix"><a class="media_file" href="files/example.pdf"><div class="title bold">Пример.pdf</div></a></div>'
    more = '<a class="media_file" href="files/example.docx">Документ</a>'
    missing = '<a class="media_file" href="files/missing.pdf">Отсутствует</a>'
    ignored = '<a class="media_file" href="files/picture.png">Картинка</a>'
    write_html(tmp_path, "messages.html",
        message(1, media),
        message(2, '<div class="text">Подпись</div>' + more + missing + ignored),
        message(3, missing),
    )
    first, second = parser.parse_export(str(tmp_path), "test")
    assert first.text == "[файл: document_1_1.pdf]"
    assert first.attachments[0].id == "test:1:f1"
    assert first.attachments[0].name == "document_1_1.pdf"
    assert first.attachments[0].size_bytes == 3
    assert first.attachments[0].path == "files/example.pdf"
    assert second.text == "Подпись"
    assert [(x.ext, x.size_bytes) for x in second.attachments] == [("docx", 4)]
    assert "Файл вложения отсутствует" in caplog.text
    assert "missing.pdf" not in caplog.text


def test_extensions_follow_config(parser, tmp_path):
    folder = tmp_path / "files"
    folder.mkdir()
    (folder / "archive.rar").write_bytes(b"RAR")
    (folder / "image.png").write_bytes(b"PNG")
    write_html(tmp_path, "messages.html",
        message(1, '<a class="media_file" href="files/archive.rar">Архив</a>'),
        message(2, '<a class="media_file" href="files/image.png">Картинка</a>'),
    )
    records = parser.parse_export(str(tmp_path), "test")
    assert len(records) == 1
    assert records[0].attachments[0].ext == "rar"
    assert records[0].attachments[0].size_bytes == 3
    assert records[0].text == "[файл: document_1_1.rar]"


def test_path_traversal_not_followed(parser, tmp_path):
    write_html(tmp_path, "messages.html",
        message(1, '<div class="text">Текст</div><a href="files/../secret.pdf">Ссылка</a>'))
    record, = parser.parse_export(str(tmp_path), "test")
    assert record.attachments == []


def test_missing_timezone_is_skipped(parser, tmp_path):
    write_html(tmp_path, "messages.html", message(1, '<div class="text">Текст</div>',
        date="21.10.2026 14:03:00"))
    assert parser.parse_export(str(tmp_path), "test") == []


def test_cli_jsonl(parser, tmp_path, monkeypatch, capsys):
    src_dir = tmp_path / "raw"
    write_html(src_dir, "messages.html", message(1, '<div class="text">Тест</div>'))
    destination = tmp_path / "parsed" / "test.jsonl"
    monkeypatch.setattr(sys, "argv", ["parse_telegram_html", str(src_dir), "--chat", "test", "--out", str(destination)])
    assert parser.main() == 0
    lines = destination.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert parser.Message.model_validate_json(lines[0]).ts.endswith("+03:00")
    assert "Сохранено сообщений: 1" in capsys.readouterr().out


def test_user_supplied_synthetic_fixture_if_available(parser):
    fixture_dir = Path(__file__).parent / "fixtures" / "mini_chat"
    if not (fixture_dir / "messages.html").exists():
        pytest.skip("Синтетический HTML-экспорт ещё не распакован")
    messages = parser.parse_export(str(fixture_dir), "mini_chat")
    # Ожидаемые типы — только сообщения, а не служебные блоки.
    assert len(messages) == 30  # 30 обычных сообщений, 3 служебных пропускаются
    assert len({m.id for m in messages}) == len(messages)
    assert all(m.text and m.ts.endswith("+03:00") for m in messages)
    assert all(m.chat == "mini_chat" for m in messages)
