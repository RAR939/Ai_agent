# tests/test_corpus_stats.py
"""Синтетические тесты агрегированных статистик без персональных данных."""
from __future__ import annotations

import csv
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from schemas import AttachedFile, Message
from eval.corpus_stats import corpus_stats, write_reports, _load_messages, _html_files, _quality_settings


class SimpleParse:
    """Синтетическая подмена лемматизатора только для тестов."""
    def __init__(self, word: str):
        self.normal_form = word.casefold()


class SimpleMorph:
    def parse(self, word: str) -> list[SimpleParse]:
        return [SimpleParse(word)]


@pytest.fixture
def config(tmp_path):
    return {
        "paths": {"data": str(tmp_path / "data")},
        "tracker": {"attach_exts": ["pdf", "docx"], "prefilter_keywords": ["срок", "сдать"],
                    "prefilter_strong_keywords": ["перенести"]},
        "quality": {"dominant_author_share": 0.4, "english_min_letters": 20,
                    "english_latin_share": 0.8, "broadcast_min_repeats": 3, "broadcast_min_chars": 30,
                    "max_anomaly_dates": 3, "report_md": str(tmp_path / "docs" / "report.md"),
                    "report_csv": str(tmp_path / "docs" / "report.csv")},
    }


def msg(n: int, *, text: str = "Тестовое сообщение", author: str = "STUDENT_1",
        role: str = "student", date: str = "2026-10-21", attachment: AttachedFile | None = None,
        reply_to: str | None = None) -> Message:
    return Message(id=f"synthetic:{n}", chat="synthetic", ts=f"{date}T12:00:00+03:00",
                   author=author, role=role, text=text,
                   attachments=[attachment] if attachment else [], reply_to=reply_to,
                   src=f"messages.html#message{n}")


def write_raw(root: Path, filename: str, *blocks: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / filename).write_text('<html><body>' + ''.join(blocks) + '</body></html>', encoding='utf8')


def block(n: int, body: str, service: bool = False) -> str:
    klass = "message service" if service else "message default clearfix"
    return f'<div class="{klass}" id="message{n}">{body}</div>'


def test_empty_clean_corpus(config):
    stats = corpus_stats("synthetic", [], config, morph=SimpleMorph())
    assert stats["metrics"]["messages"] == 0
    assert stats["metrics"]["period_from"] is None
    assert stats["metrics"]["deadline_signals"] == 0
    assert stats["metrics"]["file_message_share"] is None


def test_raw_empty_and_service(config, tmp_path):
    folder = tmp_path / "raw"
    write_raw(folder, "messages.html",
              block(1, '<div class="body"><div class="text">Пример</div></div>'),
              block(2, '<div class="body"><div class="media_photo"></div></div>'),
              block(3, '<div class="body">Событие</div>', service=True))
    stats = corpus_stats("synthetic", None, config, folder)
    assert stats["raw"]["raw_messages"] == 3
    assert stats["raw"]["service_messages"] == 1
    assert stats["raw"]["raw_empty_text"] == 1
    assert stats["metrics"] == {}


def test_raw_document_missing_and_present(config, tmp_path):
    folder = tmp_path / "raw"
    (folder / "files").mkdir(parents=True)
    (folder / "files" / "example.pdf").write_bytes(b"abc")
    write_raw(folder, "messages.html", block(1, """
        <div class="body"><a class="media_file" href="files/example.pdf">Документ</a>
        <a class="media_file" href="files/absent.docx">Документ</a>
        <div class="media_file"><div class="title">material.pdf</div></div>
        <a class="media_file" href="files/image.jpg">Картинка</a></div>"""))
    stats = corpus_stats("synthetic", None, config, folder)
    assert stats["raw"]["raw_document_links"] == 2
    assert stats["raw"]["raw_document_without_link"] == 1
    assert stats["raw"]["raw_missing_documents"] == 2


def test_numeric_sort(config, tmp_path):
    write_raw(tmp_path, "messages10.html", "")
    write_raw(tmp_path, "messages2.html", "")
    write_raw(tmp_path, "messages.html", "")
    assert [p.name for p in _html_files(tmp_path)] == ["messages.html", "messages2.html", "messages10.html"]


def test_role_counts_and_author_dominance(config):
    data = [msg(1), msg(2), msg(3, author="STAROSTA", role="starosta"),
            msg(4, author="STUDENT_2"), msg(5, author="STUDENT_2")]
    s = corpus_stats("synthetic", data, config, morph=SimpleMorph())
    assert s["role_messages"]["student"] == 4
    assert s["role_authors"]["student"] == 2
    assert s["role_authors"]["starosta"] == 1
    assert s["anomalies"]["dominant_authors"] == 2
    assert s["metrics"]["authors"] == 3


def test_duplicate_ids_repeats_and_broadcasts(config):
    text = "Синтетическое объявление с одинаковым длинным текстом"
    data = [msg(1, text=text), msg(1, text=text + " "),
            msg(3, text=text.upper()), msg(4, text="Другое")]
    s = corpus_stats("synthetic", data, config, morph=SimpleMorph())
    assert s["metrics"]["duplicate_ids"] == 1
    assert s["metrics"]["duplicate_texts"] == 2
    assert s["anomalies"]["repeated_broadcast_groups"] == 1
    assert s["anomalies"]["repeated_broadcast_messages"] == 3


def test_replies_deadline_signals_and_english(config):
    data = [msg(1, text="Срок сдачи завтра"), msg(2, text="Please submit the laboratory assignment tomorrow", reply_to="synthetic:1"),
            msg(3, text="😊")]
    s = corpus_stats("synthetic", data, config, morph=SimpleMorph())
    assert s["metrics"]["replies"] == 1
    assert s["metrics"]["deadline_signals"] == 1
    assert s["anomalies"]["english_messages"] == 1


def test_dry_days_inside_period(config):
    data = [msg(1, date="2026-10-20"), msg(2, date="2026-10-23")]
    s = corpus_stats("synthetic", data, config, morph=SimpleMorph())
    assert s["anomalies"]["silent_days"] == 2
    assert s["anomalies"]["silent_day_examples"] == ["2026-10-21", "2026-10-22"]


def test_attachment_totals_and_missing(config, tmp_path):
    folder = tmp_path / "raw"
    (folder / "files").mkdir(parents=True)
    (folder / "files" / "example.pdf").write_bytes(b"abcde")
    a = AttachedFile(id="synthetic:1:f1", msg_id="synthetic:1", name="material.pdf", ext="pdf", size_bytes=5, path="files/example.pdf")
    s = corpus_stats("synthetic", [msg(1, attachment=a), msg(2)], config, folder, morph=SimpleMorph())
    assert s["metrics"]["files"] == 1
    assert s["metrics"]["with_files"] == 1
    assert s["metrics"]["file_message_share"] == 0.5
    assert s["metrics"]["total_size_bytes"] == 5
    assert s["extensions"] == {"pdf": 1}
    assert s["metrics"]["missing_files_on_disk"] == 0


def test_no_raw_means_unverifiable_missing(config):
    a = AttachedFile(id="synthetic:1:f1", msg_id="synthetic:1", name="material.pdf", ext="pdf", size_bytes=5, path="files/example.pdf")
    s = corpus_stats("synthetic", [msg(1, attachment=a)], config, morph=SimpleMorph())
    assert s["metrics"]["missing_files_on_disk"] is None


def test_long_text_emojis_and_links(config):
    messages = [msg(1, text="😊" + "Пример " * 3000),
                msg(2, text="https://example.org"), msg(3, text="[ССЫЛКА]")]
    s = corpus_stats("synthetic", messages, config, morph=SimpleMorph())
    assert s["metrics"]["messages"] == 3
    assert s["anomalies"]["english_messages"] == 0


def test_reports_no_message_text(config, tmp_path):
    reports = [corpus_stats("synthetic", [msg(1, text="Синтетический секрет")], config, morph=SimpleMorph())]
    md = tmp_path / "docs" / "report.md"
    csvfile = tmp_path / "docs" / "report.csv"
    write_reports(reports, md, csvfile, config)
    content = md.read_text(encoding="utf8")
    assert "Синтетический секрет" not in content
    assert "STUDENT_1" not in content
    assert "Сообщений после очистки" in content
    with csvfile.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["Показатель", "synthetic", "Итого"]
    assert any(row[0] == "Сообщений после очистки" and row[1] == "1" for row in rows)


def test_raw_only_report_has_noncomputed_fields(config, tmp_path):
    raw = tmp_path / "raw"
    write_raw(raw, "messages.html", block(1, '<div class="body"><div class="text">Текст</div></div>'))
    r = corpus_stats("synthetic", None, config, raw)
    md, csvfile = tmp_path / "description.md", tmp_path / "stats.csv"
    write_reports([r], md, csvfile, config)
    report = md.read_text(encoding="utf8")
    assert "Предварительный отчёт" in report
    assert "не рассчитано" in report
    assert "Сообщений в HTML до очистки | 1" in report


def test_contract_input_file(config, tmp_path):
    data = [msg(1)]
    path = tmp_path / "clean.jsonl"
    path.write_text(data[0].model_dump_json() + '\n', encoding='utf8')
    assert _load_messages(path, "synthetic") == data
    with pytest.raises(ValueError):
        _load_messages(path, "another")
    with pytest.raises(FileNotFoundError):
        _load_messages(tmp_path / "missing.jsonl", "synthetic")


def test_missing_quality_settings(config):
    del config["quality"]["broadcast_min_repeats"]
    with pytest.raises(ValueError, match="quality"):
        _quality_settings(config)


def test_raw_reply_and_period(config, tmp_path):
    root = tmp_path / "raw"
    message_body = ('<div class="body"><div class="date details" '
                    'title="01.09.2026 22:00:00 GMT+01:00"></div>'
                    '<div class="reply_to details"><a href="#go_to_message8">Ответ</a></div>'
                    '<div class="text">Текст</div></div>')
    write_raw(root, "messages.html", block(1, message_body))
    raw = corpus_stats("synthetic", None, config, root)["raw"]
    assert raw["raw_replies"] == 1
    assert raw["raw_period_from"] == "2026-09-02T00:00:00+03:00"
    assert raw["raw_period_to"] == "2026-09-02T00:00:00+03:00"


def test_no_raw_results(config, tmp_path):
    report = corpus_stats("synthetic", None, config, tmp_path / "missing")
    assert report["raw"] is None
    assert report["clean_available"] is False


def test_aggregate_role_authors_are_not_double_counted(config, tmp_path):
    a = corpus_stats("synthetic", [msg(1, author="STUDENT_1")], config, morph=SimpleMorph())
    b = corpus_stats("synthetic2", [Message.model_validate({**msg(1).model_dump(), "chat": "synthetic2", "id": "synthetic2:1"})], config, morph=SimpleMorph())
    md, csv_path = tmp_path / "r.md", tmp_path / "r.csv"
    write_reports([a, b], md, csv_path, config)
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    role_row = next(row for row in rows if row[0] == "Уникальных авторов: student")
    assert role_row[-1] == "не рассчитано"


def test_missing_lemma_dependency_marks_unknown(config, monkeypatch):
    # Рабочий режим требует pymorphy3, не заменяет его непроверенной эвристикой.
    import builtins
    import sys
    original = builtins.__import__
    def controlled(name, *args, **kwargs):
        if name == "pymorphy3":
            raise ImportError("Пакет недоступен")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", controlled)
    r = corpus_stats("synthetic", [msg(1)], config)
    assert r["metrics"]["deadline_signals"] is None
    assert any("pymorphy3" in w for w in r["warnings"])


def test_short_repetitions_are_not_broadcasts(config):
    data = [msg(1, text="Ок"), msg(2, text="Ок"), msg(3, text="Ок")]
    result = corpus_stats("synthetic", data, config, morph=SimpleMorph())
    assert result["metrics"]["duplicate_texts"] == 2
    assert result["anomalies"]["repeated_broadcast_groups"] == 0
