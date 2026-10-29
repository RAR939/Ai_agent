"""eval/gold.py: разметка эталона (таблицы, метки, согласованность) на синтетическом мини-чате."""
import csv
import json

import pytest

from eval import gold
from src import _fixture_data as fx
from src.schemas import LabelRecord

EXPECTED = {d["msg_id"]: d for d in json.loads(
    (fx.FIXTURES / "mini_chat_expected.json").read_text(encoding="utf-8"))["deadlines"]}
DISCIPLINES = {"elektro", "models", "algo"}
CHAT = [m for m in fx.messages() if m.chat == "elektro"]


def fill_row(row: dict) -> dict:
    """Заполняет строку таблицы так, как это сделал бы разметчик по эталону мини-чата."""
    entry = EXPECTED.get(row["msg_id"])
    if entry is None:
        return {**row, "has_deadline": "нет"}
    ex = entry["extract"]
    return {**row, "has_deadline": "да", "discipline": ex["discipline"], "kind": ex["kind"], "task": ex["task"],
            "due_text": ex["due_text"] or "", "due_at": entry["due_at_gold"] or "", "action": ex["action"],
            "fuzzy": "да" if ex["fuzzy"] else "нет", "files_gold": "; ".join(entry["files_expected"])}


def make_sheet(tmp_path, name="sheet.csv", ids=None, mutate=None) -> str:
    path = tmp_path / name
    gold.write_sheet(path, CHAT, ids or [m.id for m in CHAT])
    rows = [fill_row(r) for r in gold.read_sheet(path)]
    if mutate:
        rows = [mutate(r) for r in rows]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=gold.READ_COLUMNS + gold.LABEL_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return str(path)


# ---------- разбор значений ----------
@pytest.mark.parametrize("value,expected", [("да", True), ("Да", True), (" yes ", True), ("1", True),
                                            ("нет", False), ("НЕТ", False), ("no", False), ("0", False)])
def test_parse_bool(value, expected):
    assert gold.parse_bool(value, "x") is expected


@pytest.mark.parametrize("value", ["", "может быть", "2"])
def test_parse_bool_rejects(value):
    with pytest.raises(gold.LabelError, match="нужно «да» или «нет»"):
        gold.parse_bool(value, "fuzzy")


@pytest.mark.parametrize("value,expected", [
    ("2026-10-23", "2026-10-23T23:59:00+03:00"), ("23.10.2026", "2026-10-23T23:59:00+03:00"),
    ("2026-11-12 10:00", "2026-11-12T10:00:00+03:00"), ("12.11.2026 10:00", "2026-11-12T10:00:00+03:00"),
    ("2026-10-23T18:00:00+03:00", "2026-10-23T18:00:00+03:00"), ("", None), ("  ", None)])
def test_parse_due(value, expected):
    assert gold.parse_due(value) == expected


@pytest.mark.parametrize("value", ["пятница", "2026-13-40", "2026-10-23T18:00:00Z", "23.10"])
def test_parse_due_rejects(value):
    with pytest.raises(gold.LabelError):
        gold.parse_due(value)


def test_parse_files():
    assert gold.parse_files("elektro:1041:f1; elektro:1010:f1,elektro:1010:f1") == ["elektro:1010:f1", "elektro:1041:f1"]
    assert gold.parse_files("") == [] and gold.parse_files(None) == []


# ---------- строка таблицы в метку ----------
BASE = {"has_deadline": "да", "discipline": "elektro", "kind": "lab", "task": "Лаб.2", "due_text": "до пятницы",
        "due_at": "2026-10-23", "action": "new", "fuzzy": "нет", "files_gold": ""}


def test_row_to_label_ok():
    label = gold.row_to_label(BASE, DISCIPLINES)
    assert label["due_at_gold"] == "2026-10-23T23:59:00+03:00" and label["files_gold"] == [] and label["confidence"] == 1.0
    no = gold.row_to_label({"has_deadline": "нет"}, DISCIPLINES)
    assert no["has_deadline"] is False and no["task"] is None and no["due_at_gold"] is None


@pytest.mark.parametrize("change,message", [
    ({"action": ""}, "action"), ({"action": "перенос"}, "action"), ({"kind": "лаба"}, "kind"),
    ({"discipline": ""}, "discipline"), ({"discipline": "math"}, "discipline"), ({"task": ""}, "task"),
    ({"due_at": ""}, "не указана дата"), ({"due_at": "2026-10-23", "fuzzy": "да"}, "размытого"),
    ({"due_text": ""}, "due_text"), ({"action": "cancel"}, "отмены"), ({"due_at": "в пятницу"}, "due_at"),
])
def test_row_to_label_errors(change, message):
    with pytest.raises(gold.LabelError, match=message):
        gold.row_to_label({**BASE, **change}, DISCIPLINES)


def test_row_to_label_fuzzy_and_cancel_and_no_deadline_rules():
    fuzzy = gold.row_to_label({**BASE, "due_at": "", "fuzzy": "да", "due_text": "на днях"}, DISCIPLINES)
    assert fuzzy["fuzzy"] and fuzzy["due_at_gold"] is None
    cancel = gold.row_to_label({**BASE, "action": "cancel", "due_at": "", "due_text": ""}, DISCIPLINES)
    assert cancel["action"] == "cancel" and cancel["due_text"] is None
    with pytest.raises(gold.LabelError, match="срока нет"):
        gold.row_to_label({"has_deadline": "нет", "task": "Лаб.2"})
    with pytest.raises(gold.LabelError, match="срока нет"):
        gold.row_to_label({"has_deadline": "нет", "fuzzy": "да"})


# ---------- файлы меток ----------
def test_records_roundtrip_and_format(tmp_path):
    labels = {"elektro:1010": gold.row_to_label(BASE, DISCIPLINES), "elektro:1001": gold.row_to_label({"has_deadline": "нет"})}
    path = tmp_path / "gold.jsonl"
    gold.write_labels(path, labels)
    first = LabelRecord.model_validate_json(path.read_text(encoding="utf-8").splitlines()[0])
    assert first.msg_id == "elektro:1001" and first.model_json is None
    assert (first.prompt_version, first.model_name) == (gold.GUIDE_VERSION, "human")
    assert gold.read_labels(path) == labels


def test_read_labels_rejects_duplicates_and_missing_human(tmp_path):
    rec = LabelRecord(msg_id="a:1", human_json="{}", prompt_version="v", model_name="human").model_dump_json()
    (tmp_path / "d.jsonl").write_text(rec + "\n" + rec + "\n", encoding="utf-8")
    with pytest.raises(gold.LabelError, match="повторяется"):
        gold.read_labels(tmp_path / "d.jsonl")
    nohuman = LabelRecord(msg_id="a:1", prompt_version="v", model_name="m").model_dump_json()
    (tmp_path / "n.jsonl").write_text(nohuman + "\n", encoding="utf-8")
    with pytest.raises(gold.LabelError, match="нет human_json"):
        gold.read_labels(tmp_path / "n.jsonl")


# ---------- таблица разметчика ----------
def test_sheet_has_no_model_output_and_shows_context(tmp_path):
    path = tmp_path / "s.csv"
    gold.write_sheet(path, CHAT, ["elektro:1031", "elektro:1010"])
    rows = gold.read_sheet(path)
    assert list(rows[0]) == gold.READ_COLUMNS + gold.LABEL_COLUMNS and not any("model" in c for c in rows[0])
    assert rows[0]["reply_to_text"] == "когда сдавать ДЗ 1 по электротехнике?" and rows[0]["has_deadline"] == ""
    assert rows[1]["files"] == "elektro:1010:f1 (lab2_elektro.pdf)"


def test_build_matches_expected_from_mini_chat(tmp_path):
    labels, errors = gold.build_labels([make_sheet(tmp_path)], DISCIPLINES, {"elektro": {a.id for m in CHAT for a in m.attachments}})
    assert errors == [] and len(labels) == len(CHAT)
    for msg_id, entry in EXPECTED.items():
        if not msg_id.startswith("elektro:"):
            continue
        got, ex = labels[msg_id], entry["extract"]
        assert got["due_at_gold"] == entry["due_at_gold"] and got["files_gold"] == sorted(entry["files_expected"])
        assert all(got[k] == ex[k] for k in ("discipline", "kind", "task", "due_text", "action", "fuzzy")), msg_id
    assert sum(v["has_deadline"] for v in labels.values()) == sum(i.startswith("elektro:") for i in EXPECTED)
    gold.write_labels(tmp_path / "g.jsonl", labels)
    assert gold.read_labels(tmp_path / "g.jsonl") == labels


def test_build_reports_every_problem_with_line_number(tmp_path):
    def spoil(row):
        if row["msg_id"] == "elektro:1010":
            return {**row, "due_at": "в пятницу"}
        if row["msg_id"] == "elektro:1020":
            return {**row, "has_deadline": ""}
        if row["msg_id"] == "elektro:1040":
            return {**row, "files_gold": "elektro:9999:f1"}
        return row
    sheet = make_sheet(tmp_path, mutate=spoil)
    labels, errors = gold.build_labels([sheet], DISCIPLINES, {"elektro": {a.id for m in CHAT for a in m.attachments}})
    assert len(errors) == 3
    joined = "\n".join(errors)
    assert "sheet.csv:4 elektro:1010: поле due_at" in joined and "elektro:1020: не заполнено has_deadline" in joined
    assert "неизвестные файлы: elektro:9999:f1" in joined and "elektro:1010" not in labels


def test_build_rejects_duplicate_message_across_sheets(tmp_path):
    a, b = make_sheet(tmp_path, "a.csv", ["elektro:1010"]), make_sheet(tmp_path, "b.csv", ["elektro:1010"])
    labels, errors = gold.build_labels([a, b], DISCIPLINES)
    assert len(labels) == 1 and errors == ["b.csv:2 elektro:1010: сообщение уже размечено выше"]


# ---------- подбор и раздача ----------
def test_sample_classes_limits_and_seed():
    msgs = [m for m in fx.messages()]
    chosen = gold.sample_messages(msgs, per_class=(5, 3, 4), seed=7)
    groups = [chosen["likely_deadline"], chosen["move_or_cancel"], chosen["hard_negative"]]
    assert [len(g) for g in groups] == [5, 3, 4] and len({i for g in groups for i in g}) == 12   # без пересечений
    assert chosen == gold.sample_messages(msgs, per_class=(5, 3, 4), seed=7)
    assert chosen != gold.sample_messages(msgs, per_class=(5, 3, 4), seed=8)
    assert chosen["counts"]["move_or_cancel"] >= 3
    small = gold.sample_messages(msgs[:3], per_class=(20, 10, 10))
    assert sum(len(small[k]) for k in ("likely_deadline", "move_or_cancel", "hard_negative")) <= 3


def test_assign_covers_everything_with_overlap():
    ids = [f"c:{i}" for i in range(40)]
    result = gold.assign(ids, annotators=6)
    owners = {i: [a for a, lst in result.items() if i in lst] for i in ids}
    assert all(1 <= len(o) <= 2 for o in owners.values())
    assert sum(len(o) == 2 for o in owners.values()) == 8                       # 20% разметили двое
    assert all(len(set(lst)) == len(lst) for lst in result.values())            # одно сообщение не дважды одному
    assert max(map(len, result.values())) - min(map(len, result.values())) <= 4
    assert gold.assign(ids, 6) == result and gold.assign([], 3) == {0: [], 1: [], 2: []}


def test_assign_single_annotator():
    assert gold.assign(["c:1", "c:2"], annotators=1) == {0: ["c:1", "c:2"]}


# ---------- согласованность ----------
def test_cohen_kappa_known_values():
    assert gold.cohen_kappa([1, 1, 0, 0], [1, 1, 0, 0]) == 1.0
    assert gold.cohen_kappa([1, 1, 0, 0], [1, 0, 0, 0]) == pytest.approx(0.5)
    assert gold.cohen_kappa([1, 0, 1, 0], [0, 1, 0, 1]) == pytest.approx(-1.0)
    assert gold.cohen_kappa([], []) is None and gold.cohen_kappa([1, 1], [1, 1]) == 1.0


def _labels(tmp_path, name, mutate=None):
    labels, errors = gold.build_labels([make_sheet(tmp_path, name, mutate=mutate)], DISCIPLINES)
    assert not errors
    return labels


def test_agreement_full_and_partial(tmp_path):
    a = _labels(tmp_path, "a.csv")
    b = _labels(tmp_path, "b.csv")
    full = gold.agreement(a, b)
    assert full["messages"] == 20 and full["full_match"]["share"] == 1.0 and full["passed"]
    assert full["kappa"]["has_deadline"] == 1.0 and gold.disagreements(a, b) == []

    def spoil(row):                                             # второй разметчик ошибся в двух сообщениях
        if row["msg_id"] == "elektro:1010":
            return {**row, "due_at": "2026-10-24"}
        if row["msg_id"] == "elektro:1001":
            return {**row, "has_deadline": "да", "discipline": "elektro", "kind": "other", "task": "что-то",
                    "due_text": "завтра", "due_at": "2026-10-20", "action": "new", "fuzzy": "нет"}
        return row
    partial = gold.agreement(a, _labels(tmp_path, "c.csv", spoil))
    assert partial["full_match"] == {"agree": 18, "of": 20, "share": 0.9} and partial["passed"]
    assert partial["fields"]["has_deadline"]["agree"] == 19
    assert partial["fields"]["due_at_gold"] == {"agree": 10, "of": 11, "share": pytest.approx(10 / 11)}
    assert partial["kappa"]["has_deadline"] < 1.0


def test_agreement_below_threshold_and_empty(tmp_path):
    a = _labels(tmp_path, "a.csv")
    shifted = {k: {**v, "task": "Другое"} if v["has_deadline"] else v for k, v in a.items()}
    assert not gold.agreement(a, shifted)["passed"]
    assert gold.agreement(a, {}) == {"messages": 0, "only_first": 20, "only_second": 0, "fields": {}, "kappa": {}}


def test_task_names_are_compared_loosely():
    a = {"c:1": {**gold.row_to_label(BASE, DISCIPLINES), "task": "Лаб.2"}}
    b = {"c:1": {**gold.row_to_label(BASE, DISCIPLINES), "task": "лаб 2"}}
    assert gold.disagreements(a, b) == [] and gold.agreement(a, b)["full_match"]["share"] == 1.0


def test_diff_and_merge(tmp_path):
    a = _labels(tmp_path, "a.csv")
    b = {k: {**v, "due_at_gold": "2026-10-24T23:59:00+03:00"} if k == "elektro:1010" else v for k, v in a.items()}
    (diff,) = gold.disagreements(a, b)
    assert diff["msg_id"] == "elektro:1010" and set(diff["fields"]) == {"due_at_gold"}
    assert diff["fields"]["due_at_gold"] == ("2026-10-23T23:59:00+03:00", "2026-10-24T23:59:00+03:00")
    with pytest.raises(gold.LabelError, match="elektro:1010: расходятся due_at_gold"):
        gold.merge(a, b)
    merged = gold.merge(a, b, resolved={"elektro:1010": a["elektro:1010"]})
    assert merged == a and len(merged) == 20
    only = gold.merge({"x:1": a["elektro:1010"]}, {"x:2": a["elektro:1010"]})
    assert set(only) == {"x:1", "x:2"}                                          # сообщения только у одного берутся как есть


# ---------- командная строка ----------
def test_cli_full_workflow(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gold, "_load_chat_messages", lambda chat: [m for m in fx.messages() if m.chat == chat])
    out = tmp_path / "labels"
    assert gold.main(["sample", "--chat", "elektro", "--out", str(out / "selected.json")]) == 0
    selected = json.loads((out / "selected.json").read_text(encoding="utf-8"))
    assert selected["likely_deadline"] and set(selected["counts"]) == {"likely_deadline", "move_or_cancel", "hard_negative"}
    assert gold.main(["assign", "--selected", str(out / "selected.json"), "--annotators", "2", "--outdir", str(out)]) == 0
    sheets = sorted(out.glob("sheet_*.csv"))
    assert len(sheets) == 2
    for sheet in sheets:                                                         # «разметчики» заполняют таблицы
        rows = [fill_row(r) for r in gold.read_sheet(sheet)]
        with open(sheet, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=gold.READ_COLUMNS + gold.LABEL_COLUMNS)
            w.writeheader()
            w.writerows(rows)
    capsys.readouterr()
    assert gold.main(["validate", *map(str, sheets)]) == 0 and "Таблицы в порядке" in capsys.readouterr().out
    for i, sheet in enumerate(sheets, 1):
        assert gold.main(["build", str(sheet), "--out", str(out / f"gold_{i}.jsonl")]) == 0
    assert gold.main(["agreement", str(out / "gold_1.jsonl"), str(out / "gold_2.jsonl")]) in (0, 1)
    assert gold.main(["merge", str(out / "gold_1.jsonl"), str(out / "gold_2.jsonl"), "--out", str(out / "gold.jsonl")]) == 0
    assert gold.read_labels(out / "gold.jsonl")


def test_cli_reports_errors(tmp_path, capsys):
    bad = make_sheet(tmp_path, mutate=lambda r: {**r, "action": "ой"} if r["msg_id"] == "elektro:1010" else r)
    assert gold.main(["build", bad, "--out", str(tmp_path / "x.jsonl")]) == 1
    assert "ОШИБКА sheet.csv:" in capsys.readouterr().out and not (tmp_path / "x.jsonl").exists()
    assert gold.main(["agreement", str(tmp_path / "нет.jsonl"), str(tmp_path / "нет2.jsonl")]) == 1
