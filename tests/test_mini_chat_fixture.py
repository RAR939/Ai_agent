"""Целостность синтетического мини-чата (tests/fixtures): сообщения, файлы и эталон согласованы."""
import json
import pathlib
import re

import pytest

from src.config import load_config
from src.schemas import DeadlineExtract, Message, check_iso_msk

FIX = pathlib.Path(__file__).resolve().parent / "fixtures"
FILES = FIX / "mini_chat" / "files"
MSGS = [Message.model_validate_json(line)
        for line in (FIX / "mini_chat.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
EXPECTED = json.loads((FIX / "mini_chat_expected.json").read_text(encoding="utf-8"))
BY_ID = {m.id: m for m in MSGS}
CFG = load_config()


# ---------- сообщения ----------
def test_size_and_variety():
    assert 50 <= len(MSGS) <= 80
    assert 2 <= len({m.chat for m in MSGS}) <= 3
    assert {"starosta", "teacher", "student"} <= {m.role for m in MSGS}
    assert any(m.forwarded for m in MSGS)
    assert any(m.reply_to for m in MSGS)


def test_ids_unique_and_well_formed():
    assert len(BY_ID) == len(MSGS)
    for m in MSGS:
        assert re.fullmatch(rf"{m.chat}:\d+", m.id)
        assert m.src == f"messages.html#message{m.id.split(':')[1]}"
        assert m.text.strip()                       # текст не пустой (контракт)


def test_authors_consistent_with_roles():
    roles = {}
    for m in MSGS:
        assert roles.setdefault(m.author, m.role) == m.role, m.author
        prefix = {"starosta": "STAROSTA", "teacher": "TEACHER_", "student": "STUDENT_"}[m.role]
        assert m.author.startswith(prefix)


def test_replies_point_to_earlier_message_of_same_chat():
    for m in MSGS:
        if m.reply_to:
            target = BY_ID[m.reply_to]
            assert target.chat == m.chat and target.ts <= m.ts, m.id


def test_time_order_within_chat():
    for chat in {m.chat for m in MSGS}:
        ts = [m.ts for m in MSGS if m.chat == chat]
        assert ts == sorted(ts), chat
    for m in MSGS:
        assert check_iso_msk(m.ts)


def test_no_personal_data():
    for m in MSGS:
        assert not re.search(r"https?://|www\.|@\w|\+?\d[\d\s()-]{8,}\d", m.text), m.id


# ---------- вложения ----------
ATTACHED = [m for m in MSGS if m.attachments]


def test_number_of_messages_with_files():
    assert 8 <= len(ATTACHED) <= 10


@pytest.mark.parametrize("msg", ATTACHED, ids=lambda m: m.id)
def test_attachment_matches_file_on_disk(msg):
    for n, a in enumerate(msg.attachments, 1):
        assert a.id == f"{msg.id}:f{n}" and a.msg_id == msg.id
        assert a.bind is None                       # привязку делает трекер
        assert a.path == f"files/{a.name}" and a.ext == a.name.rsplit(".", 1)[1]
        assert a.ext in CFG["tracker"]["attach_exts"]
        assert (FILES / a.name).stat().st_size == a.size_bytes


def test_no_orphan_files():
    on_disk = {p.name for p in FILES.iterdir() if p.name != "README.md"}
    assert on_disk == {a.name for m in MSGS for a in m.attachments}


def test_files_are_small_and_valid():
    for p in FILES.iterdir():
        if p.suffix == ".pdf":
            assert p.read_bytes().startswith(b"%PDF-") and p.read_bytes().rstrip().endswith(b"%%EOF")
        if p.suffix == ".docx":
            import zipfile
            assert zipfile.ZipFile(p).testzip() is None
        assert p.stat().st_size < 4096


def test_file_scenarios_are_present():
    """По одному примеру на каждый случай привязки из задачи 0.3."""
    by = lambda i: BY_ID[i]
    same_msg = by("elektro:1010")                                   # файл в сообщении с дедлайном
    assert same_msg.attachments
    near = by("elektro:1021")                                       # тот же автор через 5 минут
    assert near.author == by("elektro:1020").author and near.attachments
    reply = by("elektro:1032")                                      # файл в ответе на «когда сдавать?»
    assert reply.reply_to == "elektro:1031" and reply.attachments
    other = by("elektro:1022")                                      # чужой файл в то же время
    assert other.author != by("elektro:1020").author and other.ts == by("elektro:1021").ts
    late = by("elektro:1023")                                       # файл через час
    assert late.author == by("elektro:1020").author and late.ts > by("elektro:1020").ts
    assert by("elektro:1041").attachments                           # перенос с новым файлом
    assert by("algo:3040").attachments                              # то же, в одном сообщении
    assert by("algo:3011").text == "[файл]"                         # файл без подписи
    assert by("algo:3080").attachments == []                        # файл не выгружен
    assert by("algo:3021").reply_to == "algo:3020" and by("algo:3020").attachments   # ответ на файл


# ---------- эталон ----------
ENTRIES = EXPECTED["deadlines"]


def test_expected_not_empty_and_unique():
    assert len(ENTRIES) >= 20
    ids = [d["msg_id"] for d in ENTRIES]
    assert len(ids) == len(set(ids)) and all(i in BY_ID for i in ids)


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda d: d["msg_id"])
def test_expected_entry(entry):
    ex = DeadlineExtract(**entry["extract"])
    assert ex.has_deadline and ex.discipline in CFG["disciplines"]
    assert ex.action in ("new", "move", "cancel") and ex.task
    assert check_iso_msk(entry["due_at_gold"]) == entry["due_at_gold"]   # с поясом или None
    if ex.action == "cancel" or ex.fuzzy:
        assert entry["due_at_gold"] is None
    else:
        assert entry["due_at_gold"] is not None and ex.due_text
    if ex.fuzzy:
        assert ex.action == "new"
    chat = entry["msg_id"].split(":")[0]
    all_files = {a.id for m in MSGS if m.chat == chat for a in m.attachments}
    assert set(entry["files_expected"]) <= all_files
    assert len(set(entry["files_expected"])) == len(entry["files_expected"])


def test_note_about_unloaded_file_is_consistent():
    for d in ENTRIES:
        if "не выгружен" in d.get("note", ""):
            assert BY_ID[d["msg_id"]].attachments == [] and d["files_expected"] == []


def test_all_kinds_of_deadlines_covered():
    actions = {d["extract"]["action"] for d in ENTRIES}
    assert actions == {"new", "move", "cancel"}
    assert any(d["extract"]["fuzzy"] for d in ENTRIES)
    assert any(d["extract"]["confidence"] < CFG["tracker"]["confidence_threshold"] for d in ENTRIES)
    assert {d["extract"]["discipline"] for d in ENTRIES} == {"elektro", "models", "algo"}
    assert any("следующей паре" in (d["extract"]["due_text"] or "") for d in ENTRIES)
    assert any(BY_ID[d["msg_id"]].forwarded for d in ENTRIES)
