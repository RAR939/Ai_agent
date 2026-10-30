# tests/test_anonymize.py
"""Только синтетические участники и сообщения. Реальных данных здесь нет."""
from __future__ import annotations

from pathlib import Path
import re
import sys
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from src.schemas import Message, AttachedFile
except ModuleNotFoundError as exc:
    if exc.name not in {"src", "src.schemas"}:
        raise
    from schemas import Message, AttachedFile

from src.ingest import anonymize as anon
from src.ingest.prepare_roles import discover_authors


class DummyMorph:
    """Тестовый лемматизатор; реальный pymorphy3 тестируется в среде проекта."""
    endings = {"зайцева": "зайцев", "зайцеву": "зайцев", "зайцевой": "зайцев", "зайцевым": "зайцев",
               "орлову": "орлов", "орлова": "орлов", "орловым": "орлов",
               "артёму": "артём", "артёма": "артём", "галине": "галина"}

    def parse(self, word: str):
        return [SimpleNamespace(normal_form=self.endings.get(word.casefold(), word.casefold()))]


@pytest.fixture(autouse=True)
def fake_morph(monkeypatch):
    monkeypatch.setattr(anon, "_morph", DummyMorph)


@pytest.fixture
def roles():
    return {"people": [
        {"label": "STAROSTA", "role": "starosta", "category": "starosta", "names": ["Галина Зайцева", "Зайцева", "Галина"]},
        {"label": "COORDINATOR_1", "role": "unknown", "category": "coordinator", "names": ["РоботБот"]},
        {"label": "STUDENT_1", "role": "student", "category": "student", "names": ["Артём Орлов", "Орлов", "Артём"]},
        {"label": "TEACHER_1", "role": "teacher", "category": "teacher", "names": ["Профессор Тестов"]},
    ], "authors_by_chat": {"test": {"UNKNOWN_1": "STAROSTA", "UNKNOWN_2": "STUDENT_1", "UNKNOWN_3": "COORDINATOR_1"},
                           "other": {"UNKNOWN_1": "STUDENT_1"}}}


def record(text: str, author: str = "UNKNOWN_1", chat: str = "test", attachments=None) -> Message:
    return Message(id=f"{chat}:1", chat=chat, ts="2026-10-21T14:03:00+03:00",
                   author=author, role="unknown", text=text,
                   reply_to=None, forwarded=False, src="messages.html#message1",
                   attachments=attachments or [])


def test_empty_and_unknown(roles):
    assert anon.anonymize([], roles) == []
    unknown, = anon.anonymize([record("Учебный текст", "UNKNOWN_500")], roles)
    assert unknown.author == "UNKNOWN"
    assert unknown.role == "unknown"
    assert unknown.text == "Учебный текст"


def test_author_and_id_are_contract_compliant(roles):
    original = record("Деканат", "UNKNOWN_1")
    original.reply_to = "test:9"
    original.forwarded = True
    cleaned, = anon.anonymize([original], roles)
    assert (cleaned.id, cleaned.chat, cleaned.ts, cleaned.src, cleaned.reply_to, cleaned.forwarded) == (
        "test:1", "test", "2026-10-21T14:03:00+03:00", "messages.html#message1", "test:9", True)
    assert cleaned.author == "STAROSTA"
    assert cleaned.role == "starosta"
    assert original.author == "UNKNOWN_1"  # Не изменяет входные данные.


def test_aliases_in_cases_and_file_name(roles):
    doc = AttachedFile(id="test:1:f1", msg_id="test:1", name="Зайцева_ЛР2.docx",
                       ext="docx", size_bytes=80, path="files/Зайцева_ЛР2.docx")
    msg = record("Передай Орлову и Зайцевой. Орлова уже знает.", attachments=[doc])
    cleaned, = anon.anonymize([msg], roles)
    assert "STUDENT_1" in cleaned.text
    assert "Зайцев" not in cleaned.text
    # DummyMorph не выполняет полную морфологию, здесь добавлена явная форма.
    assert cleaned.attachments[0].name == "STAROSTA_ЛР2.docx"
    assert cleaned.attachments[0].path == "files/Зайцева_ЛР2.docx"
    assert msg.attachments[0].name == "Зайцева_ЛР2.docx"


def test_full_names_and_diminutive_explicit_alias(roles):
    roles["people"][2]["names"].append("Тёма")
    msg = record("Галина Зайцева и Тёма готовят материалы")
    cleaned, = anon.anonymize([msg], roles)
    assert cleaned.text == "STAROSTA и STUDENT_1 готовят материалы"


def test_coordinator_has_only_valid_contract_role(roles):
    cleaned, = anon.anonymize([record("Материалы", "UNKNOWN_3")], roles)
    assert cleaned.author == "COORDINATOR_1"
    assert cleaned.role == "unknown"


def test_stable_cross_chat_label(roles):
    a, = anon.anonymize([record("Один", "UNKNOWN_2")], roles)
    b, = anon.anonymize([record("Два", "UNKNOWN_1", "other")], roles)
    assert a.author == b.author == "STUDENT_1"


@pytest.mark.parametrize("phone", ["+7 (999) 123-45-67", "8 999 123 45 67", "+79991234567", "89991234567"])
def test_phone_formats(roles, phone):
    cleaned, = anon.anonymize([record("Звонить: " + phone)], roles)
    assert cleaned.text == "Звонить: [ТЕЛЕФОН]"


def test_email_url_nick_and_long_number(roles):
    text = "Пиши demo.user@example.org, @example_bot, https://example.org/page и 1234 5678 9012 3456"
    cleaned, = anon.anonymize([record(text)], roles)
    assert "[ПОЧТА]" in cleaned.text
    assert "[НИК]" in cleaned.text
    assert "[ССЫЛКА]" in cleaned.text
    assert "[НОМЕР]" in cleaned.text
    assert "example.org" not in cleaned.text


def test_long_text_emojis_empty_content_no_match(roles):
    large = ("Пример 😊 без имён\n" * 800)
    cleaned, = anon.anonymize([record(large)], roles)
    assert cleaned.text == large
    assert "😊" in cleaned.text
    plain, = anon.anonymize([record("Никакой персональной информации")], roles)
    assert plain.text == "Никакой персональной информации"


def test_ambiguous_short_name_not_mapped(roles):
    roles["people"][2]["names"].append("Галина")
    cleaned, report = anon._anonymize_with_stats([record("Галина пришла, Орлову напишем")], roles)
    assert "Галина" in cleaned[0].text
    assert "STUDENT_1" in cleaned[0].text
    assert report["ambiguous_aliases"] >= 1


def test_stats_are_only_aggregated_numbers(roles):
    _, stats = anon._anonymize_with_stats([record("Зайцева @visitor https://example.org")], roles)
    assert stats["names"] == 1
    assert stats["nicks"] == 1
    assert stats["links"] == 1
    assert stats["messages"] == 1
    assert all(isinstance(value, int) for value in stats.values())


def test_invalid_roles_rejected(roles):
    roles["people"][0]["role"] = "coordinator"  # Нельзя добавлять значение Role.
    with pytest.raises(ValueError, match="Недопустимая роль"):
        anon.anonymize([record("Текст")], roles)


def test_morph_dependency_missing_fails_closed(roles, monkeypatch):
    def unavailable():
        raise RuntimeError("Не установлен pymorphy3")
    monkeypatch.setattr(anon, "_morph", unavailable)
    with pytest.raises(RuntimeError, match="pymorphy3"):
        anon.anonymize([record("Текст")], roles)


def test_atomic_private_jsonl_write(tmp_path):
    path = tmp_path / "clean" / "test.jsonl"
    anon._save_private_text(path, "{}\n")
    assert path.read_text(encoding="utf-8") == "{}\n"
    anon._save_private_text(path, "{\"ok\": true}\n")
    assert path.read_text(encoding="utf-8") == '{"ok": true}\n'


def test_discover_authors_handles_cross_chat_and_joined(tmp_path):
    content = lambda body: f"<html><body>{body}</body></html>"
    message = lambda n, author=None, joined=False: (
        f'<div class="message default clearfix {"joined" if joined else ""}" id="message{n}">'
        '<div class="body">' + (f'<div class="from_name">{author}</div>' if author else "") +
        '<div class="text">Текст</div></div></div>')
    one, two = tmp_path / "chat1", tmp_path / "chat2"
    one.mkdir(); two.mkdir()
    (one / "messages.html").write_text(content(message(1, "Ольга Примерова") + message(2, joined=True)),encoding="utf-8")
    (two / "messages.html").write_text(content(message(1, "Ольга Примерова") + message(2, "Новый Участник")),encoding="utf-8")
    local = {"people": [{"label": "STAROSTA", "role": "starosta", "category": "starosta", "names": ["Ольга Примерова"]}],
             "authors_by_chat": {}}
    updated = discover_authors(local, {"demo": one, "demo2": two})
    assert updated["authors_by_chat"]["demo"]["UNKNOWN_1"] == "STAROSTA"
    assert updated["authors_by_chat"]["demo2"]["UNKNOWN_1"] == "STAROSTA"
    assert updated["authors_by_chat"]["demo2"]["UNKNOWN_2"] == "STUDENT_1"
    assert len(updated["people"]) == 2


def test_discover_empty_export(tmp_path):
    local = {"people": [], "authors_by_chat": {}}
    updated = discover_authors(local, {"demo": tmp_path})
    assert updated == {"people": [], "authors_by_chat": {"demo": {}}}


def test_preserves_linkless_message_and_no_attachments(roles):
    msg = record("Объявление без вложения")
    cleaned, = anon.anonymize([msg], roles)
    assert cleaned.attachments == []
    assert cleaned.text == msg.text


def test_filename_pii_and_size_metadata_preserved(roles):
    file = AttachedFile(id="test:1:f1", msg_id="test:1", name="Орлова_lecture.pdf", ext="pdf",
                        size_bytes=144, path="files/real_original.pdf", bind=None)
    msg = record("Файл отправлен", attachments=[file])
    cleaned, = anon.anonymize([msg], roles)
    assert cleaned.attachments[0].name == "STUDENT_1_lecture.pdf"
    assert cleaned.attachments[0].size_bytes == 144
    assert cleaned.attachments[0].bind is None
    assert cleaned.attachments[0].id == "test:1:f1"


def test_cyrillic_nick(roles):
    cleaned, = anon.anonymize([record("Проверь у @учебный_бот")], roles)
    assert cleaned.text == "Проверь у [НИК]"


def test_anonymize_is_idempotent(roles):
    original = record("Зайцева: demo@example.org, @visitor")
    first, = anon.anonymize([original], roles)
    second, = anon.anonymize([first], roles)
    assert first.model_dump() == second.model_dump()


def test_private_report_contains_zero_counts(roles):
    _, report = anon._anonymize_with_stats([], roles)
    for key in ("names", "phones", "emails", "links", "nicks", "numbers", "authors", "unknown_authors", "messages"):
        assert report[key] == 0


def test_integration_synthetic_fixture(roles):
    path = ROOT / "data" / "parsed" / "mini_chat.jsonl"
    if not path.is_file():
        pytest.skip("JSONL из предыдущей задачи не найден")
    records = [Message.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(records) > 0
    # Для чужого chat_id возвращается UNKNOWN без раскрытия исходного автора.
    cleaned = anon.anonymize(records, roles)
    assert len(cleaned) == len(records)
    assert all(row.ts.endswith("+03:00") and row.text for row in cleaned)


def test_cli_writes_clean_jsonl_and_aggregate_report(tmp_path, roles, monkeypatch, capsys):
    import json
    from types import ModuleType
    base = tmp_path / "data"
    source = base / "parsed" / "test.jsonl"
    source.parent.mkdir(parents=True)
    source.write_text(record("Зайцева: https://example.org").model_dump_json() + "\n", encoding="utf-8")
    roles_path = tmp_path / "roles.local.yaml"
    roles_path.write_text(yaml.safe_dump(roles, allow_unicode=True), encoding="utf-8")
    config_mod = ModuleType("src.config")
    config_mod.load_config = lambda: {"paths": {"data": str(base)}}
    monkeypatch.setitem(sys.modules, "src.config", config_mod)
    import src.ingest.parse_telegram_html as parser_module
    monkeypatch.setattr(parser_module, "_load_project_config", config_mod.load_config)
    monkeypatch.setattr(sys, "argv", ["anonymize", "--chat", "test", "--roles", str(roles_path)])
    assert anon.main() == 0
    output = base / "clean" / "test.jsonl"
    cleaned = [Message.model_validate_json(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert len(cleaned) == 1
    assert cleaned[0].author == "STAROSTA"
    assert "[ССЫЛКА]" in cleaned[0].text
    assert source.exists()  # Не удаляем parsed без ручной проверки.
    report = json.loads((base / "clean" / "test.report.json").read_text(encoding="utf-8"))
    assert report["links"] == 1
    assert "example.org" not in capsys.readouterr().out


def test_three_independent_review_samples_with_no_text():
    from src.ingest.sample_review import select_review_samples
    input_rows = [Message(id=f"test:{i}", chat="test", ts="2026-10-21T14:03:00+03:00",
                          author="STUDENT_1", role="student", text="Синтетическое сообщение",
                          src=f"messages.html#message{i}") for i in range(110)]
    samples = select_review_samples(input_rows, 100, 3)
    assert len(samples) == 3
    assert all(len(s) == 100 and len(set(s)) == 100 for s in samples)
    assert all(item.startswith("test:") for s in samples for item in s)


def test_review_samples_reject_undersized_and_duplicate_ids():
    from src.ingest.sample_review import select_review_samples
    with pytest.raises(ValueError, match="недостаточно"):
        select_review_samples([record("Текст")], 100, 3)
    with pytest.raises(ValueError, match="повторяющиеся"):
        select_review_samples([record("Текст"), record("Другой текст")], 1, 3)
    with pytest.raises(ValueError, match="положительным"):
        select_review_samples([], 0, 3)
