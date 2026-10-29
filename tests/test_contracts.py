"""Тесты контракта данных: примеры из docs/contracts.md и проверка времени с поясом +03:00."""
import json
import pathlib
import re

import pytest
from pydantic import ValidationError

from src import schemas
from src.schemas import (
    AgentResult, AttachedFile, Chunk, Deadline, DeadlineEvent, IndexStatus, Lesson,
    Message, PendingItem, SearchHit,
)

CONTRACTS = pathlib.Path(__file__).resolve().parent.parent / "docs" / "contracts.md"

OK_TS = "2026-10-21T14:03:00+03:00"


# ---------- примеры из раздела 3 документа ----------
def _examples() -> dict[str, list[str]]:
    """Строки JSON из блоков «#### Заголовок» раздела «Примеры записей»."""
    text = CONTRACTS.read_text(encoding="utf-8")
    start = text.index("### Примеры записей")
    end = text.index("## 4.", start)
    result = {}
    for part in re.split(r"^#### ", text[start:end], flags=re.M)[1:]:
        title = part.splitlines()[0]
        result[title] = [ln for ln in part.splitlines() if ln.startswith("{")]
    return result


EXAMPLES = _examples()


def test_examples_found():
    assert len(EXAMPLES) == 5
    assert all(EXAMPLES.values())


def test_example_message():
    (line,) = EXAMPLES["Строка `data/clean/elektro.jsonl` (Message)"]
    m = Message.model_validate_json(line)
    assert m.id == "elektro:1042" and m.role == "starosta" and m.attachments == []


def test_example_search_hit():
    (line,) = EXAMPLES["Результат поиска (SearchHit)"]
    assert SearchHit.model_validate_json(line).score == 0.83


def test_example_message_with_attachment():
    (line,) = EXAMPLES["Сообщение с вложением (Message)"]
    m = Message.model_validate_json(line)
    assert m.attachments[0].id == "elektro:1042:f1" and m.attachments[0].bind is None


def test_example_deadline_and_event():
    deadline_line, event_line = EXAMPLES["Дедлайн (Deadline) и строка истории"]
    d = Deadline.model_validate_json(deadline_line)
    assert d.attachments[0].bind == "same_message" and d.due_at.endswith("+03:00")
    assert DeadlineEvent.model_validate_json(event_line).deadline_id == 5


def test_example_agent_result():
    (line,) = EXAMPLES["Ответ агента (AgentResult) с трассой"]
    r = AgentResult.model_validate_json(line)
    assert r.trace[0].tool == "list_deadlines" and r.trace[0].error is None


# ---------- время ----------
def _file() -> dict:
    return dict(id="elektro:1:f1", msg_id="elektro:1", name="a.pdf", ext="pdf",
                size_bytes=1, path="files/a.pdf")


def _message() -> dict:
    return dict(id="elektro:1", chat="elektro", ts=OK_TS, author="STAROSTA", role="starosta",
                text="т", src="messages.html#message1")


def _deadline() -> dict:
    return dict(discipline="elektro", kind="lab", task="Лаб.2", due_text="до пятницы",
                source_msg="elektro:1", confidence=0.9)


# (модель, поля с временем, минимальные данные)
TIME_MODELS = [
    (Message, ["ts"], _message()),
    (Chunk, ["ts_from", "ts_to"],
     dict(id="elektro:1-2", chat="elektro", msg_ids=["elektro:1"], ts_from=OK_TS, ts_to=OK_TS,
          roles=["student"], text="т")),
    (SearchHit, ["ts_from", "ts_to"],
     dict(chunk_id="elektro:1-2", chat="elektro", text="т", ts_from=OK_TS, ts_to=OK_TS,
          roles=["student"], msg_ids=["elektro:1"], score=0.5)),
    (Deadline, ["due_at", "updated_at"], _deadline()),
    (DeadlineEvent, ["old_due", "new_due", "changed_at"],
     dict(id=1, deadline_id=1, old_due=OK_TS, new_due=OK_TS, source_msg="elektro:1",
          changed_at=OK_TS)),
    (PendingItem, ["created_at"],
     dict(id=1, candidate=_deadline(), matched_id=None, reason="low_confidence",
          source_text="т", created_at=OK_TS)),
    (Lesson, ["start", "end"],
     dict(discipline="elektro", lesson_type="lab", start=OK_TS, end=OK_TS)),
    (IndexStatus, ["period_from", "period_to", "last_processed"],
     dict(chat="elektro", messages=1, period_from=OK_TS, period_to=OK_TS, last_processed=OK_TS,
          chunks=1, deadlines=1)),
]
# поля, которые могут быть None
NULLABLE = {"due_at", "updated_at", "old_due", "new_due", "last_processed"}
CASES = [(m, f, data) for m, fields, data in TIME_MODELS for f in fields]

BAD_TIMES = [
    "2026-10-21T14:03:00",           # без пояса
    "2026-10-21T14:03:00Z",          # UTC
    "2026-10-21T14:03:00+00:00",     # другой пояс
    "2026-10-21T14:03:00+04:00",
    "2026-10-21T14:03:00+0300",      # пояс без двоеточия
    "2026-10-21T14:03+03:00",        # нет секунд
    "2026-10-21",                    # только дата
    "2026-10-21 14:03:00+03:00",     # пробел вместо T
    "2026-13-45T25:00:00+03:00",     # несуществующее время
    "вчера",
    "",
]


@pytest.mark.parametrize("model,field,data", CASES)
def test_valid_time_accepted(model, field, data):
    model(**data)


@pytest.mark.parametrize("model,field,data", CASES)
@pytest.mark.parametrize("bad", BAD_TIMES)
def test_bad_time_rejected(model, field, data, bad):
    with pytest.raises(ValidationError) as e:
        model(**{**data, field: bad})
    assert field in str(e.value)


@pytest.mark.parametrize("model,field,data", [c for c in CASES if c[1] in NULLABLE])
def test_none_allowed_for_optional_time(model, field, data):
    assert getattr(model(**{**data, field: None}), field) is None


@pytest.mark.parametrize("model,field,data", [c for c in CASES if c[1] not in NULLABLE])
def test_none_rejected_for_required_time(model, field, data):
    with pytest.raises(ValidationError):
        model(**{**data, field: None})


def test_fraction_of_second_allowed():
    assert Message(**{**_message(), "ts": "2026-10-21T14:03:00.123+03:00"}).ts.endswith("+03:00")


def test_all_time_fields_are_covered():
    """Новое поле времени в схемах не должно остаться без проверки."""
    time_names = {"ts", "ts_from", "ts_to", "due_at", "updated_at", "old_due", "new_due",
                  "changed_at", "created_at", "start", "end", "period_from", "period_to",
                  "last_processed"}
    in_schemas = {(name, f) for name, cls in vars(schemas).items()
                  if isinstance(cls, type) and issubclass(cls, schemas.BaseModel)
                  for f in cls.model_fields if f in time_names}
    covered = {(m.__name__, f) for m, f, _ in CASES}
    assert in_schemas == covered


# ---------- прочее ----------
def test_nested_time_is_validated():
    """Плохое время во вложенном Deadline ловится при создании PendingItem."""
    with pytest.raises(ValidationError):
        PendingItem(id=1, candidate={**_deadline(), "due_at": "2026-10-21T14:03:00"},
                    matched_id=None, reason="low_confidence", source_text="т", created_at=OK_TS)


def test_defaults_are_independent():
    a, b = Message(**_message()), Message(**_message())
    a.attachments.append(AttachedFile(**_file()))
    assert b.attachments == []


def test_roundtrip_json():
    m = Message(**{**_message(), "attachments": [_file()]})
    assert Message.model_validate_json(m.model_dump_json()) == m
    assert json.loads(m.model_dump_json())["attachments"][0]["bind"] is None


def test_unknown_role_and_bind_rejected():
    with pytest.raises(ValidationError):
        Message(**{**_message(), "role": "admin"})
    with pytest.raises(ValidationError):
        AttachedFile(**{**_file(), "bind": "somehow"})


def _norm(annotation) -> str:
    """Тип в виде строки без путей модулей: классы из разных пространств имён сравнимы."""
    return re.sub(r"<class '(?:[\w.]*\.)?(\w+)'>", r"\1", repr(annotation)).replace("src.schemas.", "")


def test_schemas_match_contract_doc():
    """Поля, типы и значения по умолчанию в schemas.py совпадают с кодом из раздела 3 документа."""
    text = CONTRACTS.read_text(encoding="utf-8")
    start = text.index("## 3. Схемы данных")
    block = re.search(r"```\n(.*?)\n```", text[start:], flags=re.S).group(1)
    ns: dict = {}
    exec(block, ns)   # код из нашего же документа
    models = [n for n, c in ns.items() if isinstance(c, type) and issubclass(c, ns["BaseModel"])
              and c is not ns["BaseModel"]]
    assert len(models) == 18
    for name in models:
        doc_fields = ns[name].model_fields
        code_fields = getattr(schemas, name).model_fields
        assert list(doc_fields) == list(code_fields), name
        for f, info in doc_fields.items():
            other = code_fields[f]
            assert (_norm(info.annotation), info.is_required(), info.default) == \
                   (_norm(other.annotation), other.is_required(), other.default), f"{name}.{f}"
    for alias in ("Role", "Kind", "Status", "LessonType", "ISO"):
        assert ns[alias] == getattr(schemas, alias), alias


# ---------- сигнатуры функций из раздела 4 документа ----------
import ast  # noqa: E402
import importlib  # noqa: E402
import inspect  # noqa: E402

from src.schemas import Answer, MessageContext  # noqa: E402

# параметры сверх контракта, о которых договорились (только необязательные)
KNOWN_EXTRA_PARAMS = {"src.agent.run_agent": {"deterministic"}}


def _contract_functions() -> list[tuple[str, str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """(модуль, имя вида «функция» или «Класс.метод», разобранное определение) из раздела 4."""
    text = CONTRACTS.read_text(encoding="utf-8")
    section = text[text.index("## 4. Интерфейсы модулей"):text.index("## 5.")]
    found, module, cls = [], None, None
    for block in re.findall(r"```\n(.*?)\n```", section, flags=re.S):
        lines, i = block.splitlines(), 0
        while i < len(lines):
            line = lines[i]
            m = re.match(r"# ((?:src|ui)/[\w/]+)\.py\s*$", line)
            if m:
                module, cls = m.group(1).replace("/", "."), None
            elif line.startswith("class "):
                cls = re.match(r"class (\w+)", line).group(1)
                if cls == "Provider":     # у блока интерфейса нет строки «# ui/provider.py»
                    module = "ui.provider"
            elif re.match(r"\s*(async )?def ", line):
                sig = line
                while sig.count("(") != sig.count(")"):   # сигнатура может идти на нескольких строках
                    i += 1
                    sig += "\n" + lines[i]
                sig = re.sub(r"\s+#.*$", "", sig, flags=re.M).rstrip()
                node = ast.parse(sig.strip() + ":\n    pass").body[0]
                found.append((module, f"{cls}.{node.name}" if cls else node.name, node))
            i += 1
    return found


CONTRACT_FUNCTIONS = _contract_functions()


def test_contract_functions_found():
    assert len(CONTRACT_FUNCTIONS) >= 50
    assert {"load_config", "search", "run_agent", "Provider.ask"} <= {n for _, n, _ in CONTRACT_FUNCTIONS}


def _params(node) -> list[tuple[str, object]]:
    """Параметры без self: (имя, значение по умолчанию или ... если его нет)."""
    args = node.args.args
    defaults = [...] * (len(args) - len(node.args.defaults)) + [ast.literal_eval(d) for d in node.args.defaults]
    return [(a.arg, d) for a, d in zip(args, defaults) if a.arg != "self"]


@pytest.mark.parametrize("module,name,node", CONTRACT_FUNCTIONS, ids=lambda v: v if isinstance(v, str) else "")
def test_function_signature_matches_contract(module, name, node):
    """Есть функция, значит её параметры совпадают с контрактом; нет функции, значит ещё не написана."""
    try:
        mod = importlib.import_module(module)
    except ImportError as e:
        pytest.skip(f"модуль не импортируется: {e}")
    obj = mod
    for part in name.split("."):
        obj = getattr(obj, part, None)
        if obj is None:
            pytest.skip("ещё не реализовано")
    assert inspect.iscoroutinefunction(obj) == isinstance(node, ast.AsyncFunctionDef), name
    real = [(p.name, ... if p.default is inspect.Parameter.empty else p.default)
            for p in inspect.signature(obj).parameters.values() if p.name != "self"
            and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)]
    want = _params(node)
    extra = KNOWN_EXTRA_PARAMS.get(f"{module}.{name}", set())
    core = [p for p in real if p[0] not in extra]
    assert [n for n, _ in core] == [n for n, _ in want], f"{module}.{name}: имена и порядок параметров"
    for (n, got), (_, wanted) in zip(core, want):
        # допустимо сделать обязательный параметр необязательным (совместимо), менять значение по умолчанию нельзя
        assert wanted is ... or got == wanted, f"{module}.{name}: значение по умолчанию {n}"
    assert all(d is not ... for n, d in real if n in extra)      # лишние параметры только необязательные


# ---------- заглушки возвращают нужные типы ----------
def _stub(module_name: str):
    mod = importlib.import_module(module_name)
    if not getattr(mod, "IS_STUB", False):
        pytest.skip("реальная реализация, не заглушка")
    return mod


def _list_of(value, cls) -> bool:
    return isinstance(value, list) and all(isinstance(v, cls) for v in value)


def test_stub_store_types():
    store = _stub("src.ingest.store")
    msgs = store.load_messages("elektro")
    assert msgs and _list_of(msgs, Message) and {m.chat for m in msgs} == {"elektro"}
    assert store.load_messages("нет-такого") == []
    assert store.list_chats() == ["algo", "elektro", "models"]
    assert isinstance(store.get_message("elektro:1010"), Message)
    with pytest.raises(KeyError, match="не найдено"):
        store.get_message("elektro:0")
    ctx = store.get_context("elektro:1031", before=2, after=1)
    assert isinstance(ctx, MessageContext) and ctx.target.id == "elektro:1031"
    assert [m.id for m in ctx.before] == ["elektro:1023", "elektro:1030"] and len(ctx.after) == 1
    assert store.get_context("elektro:1001").before == []
    files = store.get_attachments("elektro:1010")
    assert _list_of(files, AttachedFile) and len(files) == 1 and store.get_attachments("elektro:1001") == []
    assert pathlib.Path(store.file_abs_path(files[0])).is_file()
    assert store.save_messages is not None


def test_stub_search_types_and_filters():
    search = _stub("src.index.search").search
    hits = search("лаба")
    assert hits and _list_of(hits, SearchHit) and all(len(h.text) <= 1500 for h in hits)
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)
    assert search("   ") == [] and search("лаба", top_k=0) == [] and len(search("лаба", top_k=1)) == 1
    assert {h.chat for h in search("лаба", chat="models")} == {"models"}
    assert search("лаба", chat="нет-такого") == []
    assert search("лаба", role="teacher") == [h for h in hits if "teacher" in h.roles]
    assert search("лаба", date_from="2027-01-01") == [] and search("лаба", date_to="2020-01-01") == []
    assert {h.chunk_id for h in search("лаба", date_from="2026-10-21", date_to="2026-10-23")} == {
        "elektro:1040-1041", "algo:3020-3022"}                                            # границы включаются
    assert len(search("лаба", top_k=100)) <= 8


def test_stub_answer_types():
    answer = _stub("src.index.answer").answer
    ok = answer("когда сдавать лабу")
    assert isinstance(ok, Answer) and not ok.refused and _list_of(ok.sources, SearchHit)
    assert ok.prompt_version == "answer_v1"
    no = answer("когда сдавать лабу", chat="нет-такого")
    assert no.refused and no.sources == [] and no.text == "В материалах этого нет"


def test_stub_discussion_types():
    mod = _stub("src.index.discussion")
    lab2 = Deadline(discipline="elektro", kind="lab", task="Лаб.2", due_at="2026-10-30T23:59:00+03:00",
                    due_text="до пятницы", source_msg="elektro:1010", confidence=0.93)
    found = mod.get_discussion(lab2)
    assert found and _list_of(found, SearchHit) and {h.chat for h in found} == {"elektro"}
    assert len(mod.get_discussion(lab2, top_k=1)) == 1


def test_stub_files_do_not_shadow_real_ones():
    """Заглушка отмечена IS_STUB, а реальные модули ролей 4, 5 и 6 заглушками не подменялись."""
    agent = importlib.import_module("src.agent")
    assert not getattr(agent, "IS_STUB", False) and inspect.iscoroutinefunction(agent.run_agent)
    provider = importlib.import_module("ui.provider")
    assert not getattr(provider, "IS_STUB", False)
    for name in ("db", "pipeline", "schedule_query"):
        assert not getattr(importlib.import_module(f"src.tracker.{name}"), "IS_STUB", False), name
