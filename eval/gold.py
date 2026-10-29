"""Эталонная разметка дедлайнов (задача Q1): подбор сообщений, таблицы для разметчиков, сборка и согласованность.

Порядок работы (подробно: docs/annotation_guide.md):
  1. python -m eval.gold sample --chat elektro --out data/labels/selected.json
  2. python -m eval.gold assign --selected data/labels/selected.json --annotators 6
  3. разметчики заполняют data/labels/sheet_<имя>.csv (ответ модели им не показывается)
  4. python -m eval.gold build data/labels/sheet_*.csv --out data/labels/gold_<имя>.jsonl  (по одному файлу на разметчика)
  5. python -m eval.gold agreement data/labels/gold_a.jsonl data/labels/gold_b.jsonl
  6. python -m eval.gold merge ... --out eval/gold_deadlines.jsonl  (итог после обсуждения расхождений)

Таблицы с текстами сообщений лежат в data/labels/ (не в git); в eval/gold_deadlines.jsonl только метки без текстов.
Формат записи: LabelRecord (src/schemas.py), human_json это DeadlineExtract плюс due_at_gold и files_gold.
"""
import argparse
import csv
import json
import random
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from src.schemas import DeadlineExtract, LabelRecord, Message, check_iso_msk

ROOT = Path(__file__).resolve().parent.parent
GUIDE_VERSION = "guide_v1"          # версия руководства по разметке (в LabelRecord.prompt_version)
HUMAN = "human"                     # LabelRecord.model_name для меток человека

# колонки таблицы: первые читает разметчик, остальные заполняет
READ_COLUMNS = ["msg_id", "ts", "author_role", "reply_to_text", "text", "files"]
LABEL_COLUMNS = ["has_deadline", "discipline", "kind", "task", "due_text", "due_at", "action", "fuzzy",
                 "files_gold", "comment"]
KINDS = {"lab", "hw", "midterm", "exam", "other"}
ACTIONS = {"new", "move", "cancel"}
YES = {"да", "yes", "y", "true", "1", "+"}
NO = {"нет", "no", "n", "false", "0", "-"}
# поля, по которым считается согласованность (имя в human_json)
FIELDS = ["has_deadline", "discipline", "kind", "task", "action", "fuzzy", "due_at_gold", "files_gold"]


class LabelError(ValueError):
    """Ошибка в строке разметки (текст на русском, с номером строки)."""


# ---------- разбор значений ----------
def parse_bool(value: str, field: str) -> bool:
    v = (value or "").strip().lower()
    if v in YES:
        return True
    if v in NO:
        return False
    raise LabelError(f"поле {field}: нужно «да» или «нет», получено {value!r}")


def parse_due(value: str) -> str | None:
    """«2026-10-23», «23.10.2026», «2026-10-23 18:00» или полный ISO в строку ISO с поясом +03:00."""
    v = (value or "").strip()
    if not v:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+03:00", v):
        return check_iso_msk(v)
    for fmt, has_time in (("%Y-%m-%d", False), ("%d.%m.%Y", False), ("%Y-%m-%d %H:%M", True),
                          ("%d.%m.%Y %H:%M", True)):
        try:
            moment = datetime.strptime(v, fmt)
        except ValueError:
            continue
        if not has_time:
            moment = moment.replace(hour=23, minute=59)          # дата без времени: 23:59 (контракт)
        return check_iso_msk(moment.strftime("%Y-%m-%dT%H:%M:00+03:00"))
    raise LabelError(f"поле due_at: не понимаю дату {value!r} (пример: 2026-10-23 или 23.10.2026 18:00)")


def parse_files(value: str) -> list[str]:
    return sorted({x.strip() for x in re.split(r"[;,\s]+", value or "") if x.strip()})


def row_to_label(row: dict, disciplines: set[str] | None = None) -> dict:
    """Строка таблицы в human_json (словарь). Проверяет согласованность полей."""
    has = parse_bool(row.get("has_deadline", ""), "has_deadline")
    filled = {k: (row.get(k) or "").strip() for k in ("discipline", "kind", "task", "due_text", "due_at", "action", "files_gold")}
    if not has:
        extra = [k for k, v in filled.items() if v]
        if extra or (row.get("fuzzy") or "").strip().lower() in YES:
            raise LabelError("срока нет (has_deadline=нет), но заполнены поля: " + ", ".join(extra or ["fuzzy"]))
        return {"has_deadline": False, "discipline": None, "kind": None, "task": None, "due_text": None,
                "action": None, "fuzzy": False, "confidence": 1.0, "due_at_gold": None, "files_gold": []}
    if filled["action"] not in ACTIONS:
        raise LabelError(f"поле action: new, move или cancel, получено {filled['action']!r}")
    if filled["kind"] not in KINDS:
        raise LabelError(f"поле kind: {', '.join(sorted(KINDS))}, получено {filled['kind']!r}")
    if not filled["discipline"] or (disciplines is not None and filled["discipline"] not in disciplines):
        raise LabelError(f"поле discipline: нужен ключ из config/disciplines.yaml, получено {filled['discipline']!r}")
    if not filled["task"]:
        raise LabelError("поле task не заполнено")
    fuzzy = parse_bool(row.get("fuzzy") or "нет", "fuzzy")
    due_at = parse_due(filled["due_at"])
    if filled["action"] == "cancel":
        if due_at or fuzzy:
            raise LabelError("для отмены (cancel) due_at пуст и fuzzy=нет")
    elif fuzzy and due_at:
        raise LabelError("у размытого срока (fuzzy=да) дата due_at пуста")
    elif not fuzzy and not due_at:
        raise LabelError("не указана дата due_at (если срок размытый, поставьте fuzzy=да)")
    if filled["action"] != "cancel" and not filled["due_text"]:
        raise LabelError("поле due_text (срок как написан в сообщении) не заполнено")
    return {"has_deadline": True, "discipline": filled["discipline"], "kind": filled["kind"],
            "task": filled["task"], "due_text": filled["due_text"] or None, "action": filled["action"],
            "fuzzy": fuzzy, "confidence": 1.0, "due_at_gold": due_at, "files_gold": parse_files(filled["files_gold"])}


def make_record(msg_id: str, human: dict) -> LabelRecord:
    DeadlineExtract(**{k: v for k, v in human.items() if k in DeadlineExtract.model_fields})   # проверка схемы
    return LabelRecord(msg_id=msg_id, human_json=json.dumps(human, ensure_ascii=False, sort_keys=True),
                       prompt_version=GUIDE_VERSION, model_name=HUMAN)


# ---------- чтение и запись ----------
def read_labels(path: str | Path) -> dict[str, dict]:
    """msg_id -> human_json (словарь) из файла LabelRecord."""
    result = {}
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        rec = LabelRecord.model_validate_json(line)
        if rec.human_json is None:
            raise LabelError(f"{path}:{n}: у {rec.msg_id} нет human_json")
        if rec.msg_id in result:
            raise LabelError(f"{path}:{n}: {rec.msg_id} повторяется")
        result[rec.msg_id] = json.loads(rec.human_json)
    return result


def write_labels(path: str | Path, labels: dict[str, dict]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("".join(make_record(i, h).model_dump_json() + "\n" for i, h in sorted(labels.items())),
                          encoding="utf-8")


def read_sheet(path: str | Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def build_labels(sheet_paths: list[str | Path], disciplines: set[str] | None = None,
                 known_files: dict[str, set[str]] | None = None) -> tuple[dict[str, dict], list[str]]:
    """Таблицы разметчика в метки. Возвращает (метки, ошибки вида «файл:строка msg_id: текст»)."""
    labels, errors = {}, []
    for path in sheet_paths:
        for n, row in enumerate(read_sheet(path), 2):                # строка 1 это заголовок
            msg_id = (row.get("msg_id") or "").strip()
            where = f"{Path(path).name}:{n} {msg_id}"
            if not msg_id:
                errors.append(f"{where}: пустой msg_id")
                continue
            if not (row.get("has_deadline") or "").strip():
                errors.append(f"{where}: не заполнено has_deadline")
                continue
            try:
                human = row_to_label(row, disciplines)
                chat = msg_id.split(":")[0]
                if known_files is not None and chat in known_files:      # чаты без списка файлов не проверяются
                    unknown = set(human["files_gold"]) - known_files[chat]
                    if unknown:
                        raise LabelError("неизвестные файлы: " + ", ".join(sorted(unknown)))
            except (LabelError, ValidationError, ValueError) as e:
                errors.append(f"{where}: {e}")
                continue
            if msg_id in labels:
                errors.append(f"{where}: сообщение уже размечено выше")
                continue
            labels[msg_id] = human
    return labels, errors


# ---------- подбор сообщений ----------
def sample_messages(messages: list[Message], per_class: tuple[int, int, int] = (20, 10, 10), seed: int = 1) -> dict:
    """Расслоённая выборка: сообщения с вероятным сроком, перенос или отмена, трудные «похожие» без срока.

    Классы определяет предфильтр роли 4 (это только подбор кандидатов, метки ставит человек).
    """
    from src.tracker import prefilter
    by_id = {m.id: m for m in messages}
    strong = [m for m in messages if prefilter.has_strong_keyword(m.text)]
    strong_ids = {m.id for m in strong}
    likely = [m for m in messages if m.id not in strong_ids and prefilter.looks_like_deadline(m, by_id)]
    hard = [m for m in messages if m.id not in strong_ids and not prefilter.looks_like_deadline(m, by_id)
            and (prefilter.has_keyword(m.text) or "до" in prefilter.lemmas(m.text))]
    rng = random.Random(seed)
    groups = {"likely_deadline": likely, "move_or_cancel": strong, "hard_negative": hard}
    chosen = {}
    for (name, pool), count in zip(groups.items(), per_class):
        picked = list(pool)
        rng.shuffle(picked)
        chosen[name] = sorted(m.id for m in picked[:count])
    chosen["counts"] = {name: len(pool) for name, pool in groups.items()}      # сколько кандидатов было в каждом классе
    return chosen


def assign(ids: list[str], annotators: int, overlap_share: float = 0.2, seed: int = 1) -> dict[int, list[str]]:
    """Раздаёт сообщения: каждое одному разметчику, а overlap_share набора ещё и второму (независимо)."""
    rng = random.Random(seed)
    ids = list(ids)
    rng.shuffle(ids)
    result: dict[int, list[str]] = {a: [] for a in range(annotators)}
    for i, msg_id in enumerate(ids):
        result[i % annotators].append(msg_id)
    for k, msg_id in enumerate(ids[:round(len(ids) * overlap_share)]):
        owner = next(a for a, lst in result.items() if msg_id in lst)
        result[(owner + 1 + k % max(annotators - 1, 1)) % annotators].append(msg_id)
    return {a: sorted(lst) for a, lst in result.items()}


def write_sheet(path: str | Path, messages: list[Message], ids: list[str]) -> None:
    """Таблица для разметчика: текст сообщения и контекст, пустые колонки для меток (без ответа модели)."""
    by_id = {m.id: m for m in messages}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=READ_COLUMNS + LABEL_COLUMNS)
        w.writeheader()
        for msg_id in ids:
            m = by_id[msg_id]
            parent = by_id.get(m.reply_to) if m.reply_to else None
            w.writerow({"msg_id": m.id, "ts": m.ts, "author_role": m.role,
                        "reply_to_text": parent.text if parent else "", "text": m.text,
                        "files": "; ".join(f"{a.id} ({a.name})" for a in m.attachments)})


# ---------- согласованность ----------
def _norm(field: str, value):
    if field == "task":
        return re.sub(r"[\s.]+", "", (value or "").casefold())
    return value


def cohen_kappa(a: list, b: list) -> float | None:
    """Каппа Коэна для двух списков меток; None, если считать нечего (пусто или одна и та же метка у всех)."""
    n = len(a)
    if n == 0:
        return None
    observed = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    if expected == 1:
        return 1.0 if observed == 1 else None
    return (observed - expected) / (1 - expected)


def agreement(first: dict[str, dict], second: dict[str, dict]) -> dict:
    """Согласованность двух разметчиков на общих сообщениях."""
    common = sorted(set(first) & set(second))
    report: dict = {"messages": len(common), "only_first": len(set(first) - set(second)),
                    "only_second": len(set(second) - set(first)), "fields": {}, "kappa": {}}
    if not common:
        return report
    a, b = [first[i] for i in common], [second[i] for i in common]
    both_yes = [i for i in common if first[i]["has_deadline"] and second[i]["has_deadline"]]
    for field in FIELDS:
        # поля про срок сравниваются там, где оба видят срок; has_deadline на всех сообщениях
        ids = common if field == "has_deadline" else both_yes
        if ids:
            same = sum(_norm(field, first[i][field]) == _norm(field, second[i][field]) for i in ids)
            report["fields"][field] = {"agree": same, "of": len(ids), "share": same / len(ids)}
    report["full_match"] = {"agree": sum(_decision(x) == _decision(y) for x, y in zip(a, b)), "of": len(common)}
    report["full_match"]["share"] = report["full_match"]["agree"] / len(common)
    report["kappa"]["has_deadline"] = cohen_kappa([x["has_deadline"] for x in a], [y["has_deadline"] for y in b])
    for field in ("action", "kind"):
        report["kappa"][field] = cohen_kappa([first[i][field] for i in both_yes], [second[i][field] for i in both_yes])
    report["ok_threshold"] = 0.8
    report["passed"] = report["full_match"]["share"] >= 0.8
    return report


def _decision(label: dict) -> tuple:
    """Решение целиком: наличие срока, задание, действие, дата, размытость, файлы."""
    if not label["has_deadline"]:
        return (False,)
    return (True, label["discipline"], _norm("task", label["task"]), label["action"], label["due_at_gold"],
            label["fuzzy"], tuple(label["files_gold"]))


def disagreements(first: dict[str, dict], second: dict[str, dict]) -> list[dict]:
    """Сообщения, где решения расходятся: что у первого и у второго по каждому спорному полю."""
    result = []
    for msg_id in sorted(set(first) & set(second)):
        a, b = first[msg_id], second[msg_id]
        if _decision(a) == _decision(b):
            continue
        diff = {f: (a.get(f), b.get(f)) for f in FIELDS if _norm(f, a.get(f)) != _norm(f, b.get(f))}
        result.append({"msg_id": msg_id, "fields": diff})
    return result


def merge(first: dict[str, dict], second: dict[str, dict], resolved: dict[str, dict] | None = None) -> dict[str, dict]:
    """Итоговый набор: метки первого и второго; при расхождении берётся решение из resolved (после обсуждения).

    Расхождение без решения даёт LabelError: молча выбирать одну из меток нельзя.
    """
    resolved = resolved or {}
    result = {}
    for msg_id in sorted(set(first) | set(second)):
        a, b = first.get(msg_id), second.get(msg_id)
        if msg_id in resolved:
            result[msg_id] = resolved[msg_id]
        elif a is None or b is None or _decision(a) == _decision(b):
            result[msg_id] = a or b
        else:
            raise LabelError(f"{msg_id}: расходятся {', '.join(disagreements({msg_id: a}, {msg_id: b})[0]['fields'])}; "
                             "нужно решение после обсуждения (--resolved)")
    return result


# ---------- командная строка ----------
def _load_chat_messages(chat: str) -> list[Message]:
    from src.tracker import common
    return common.load_chat(chat)


def _print_agreement(report: dict) -> None:
    if not report["messages"]:
        print("Нет общих сообщений: нечего сравнивать.")
        return
    print(f"Общих сообщений: {report['messages']} (только у первого: {report['only_first']}, "
          f"только у второго: {report['only_second']})")
    for field, r in report["fields"].items():
        print(f"  {field:<12} {r['agree']}/{r['of']}  {r['share']:.0%}")
    full = report["full_match"]
    print(f"Решение целиком совпало: {full['agree']}/{full['of']}  {full['share']:.0%}  "
          f"(порог {report['ok_threshold']:.0%}: {'пройден' if report['passed'] else 'НЕ пройден'})")
    for name, k in report["kappa"].items():
        print(f"  каппа Коэна, {name}: {'нет данных' if k is None else f'{k:.2f}'}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Эталонная разметка дедлайнов")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("sample", help="подобрать сообщения для разметки")
    p.add_argument("--chat", action="append", required=True)
    p.add_argument("--out", default="data/labels/selected.json")
    p.add_argument("--seed", type=int, default=1)
    p = sub.add_parser("assign", help="раздать выбранные сообщения и создать таблицы")
    p.add_argument("--selected", default="data/labels/selected.json")
    p.add_argument("--annotators", type=int, default=6)
    p.add_argument("--outdir", default="data/labels")
    p = sub.add_parser("build", help="таблицы разметчика в файл меток")
    p.add_argument("sheets", nargs="+")
    p.add_argument("--out", required=True)
    p = sub.add_parser("validate", help="проверить таблицы, ничего не записывая")
    p.add_argument("sheets", nargs="+")
    p = sub.add_parser("agreement", help="согласованность двух разметчиков")
    p.add_argument("first")
    p.add_argument("second")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("diff", help="спорные сообщения")
    p.add_argument("first")
    p.add_argument("second")
    p = sub.add_parser("merge", help="итоговый набор из двух разметок")
    p.add_argument("first")
    p.add_argument("second")
    p.add_argument("--resolved", help="файл меток с решениями по спорным сообщениям")
    p.add_argument("--out", default="eval/gold_deadlines.jsonl")
    args = ap.parse_args(argv)

    from src.config import load_config
    disciplines = set(load_config()["disciplines"])
    try:
        if args.cmd == "sample":
            msgs = [m for chat in args.chat for m in _load_chat_messages(chat)]
            chosen = sample_messages(msgs, seed=args.seed)
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(json.dumps(chosen, ensure_ascii=False, indent=2), encoding="utf-8")
            print({k: (len(v) if isinstance(v, list) else v) for k, v in chosen.items()})
        elif args.cmd == "assign":
            chosen = json.loads(Path(args.selected).read_text(encoding="utf-8"))
            ids = [i for k, v in chosen.items() if k != "counts" for i in v]
            msgs = {}
            for chat in {i.split(":")[0] for i in ids}:
                msgs.update({m.id: m for m in _load_chat_messages(chat)})
            for a, mine in assign(ids, args.annotators).items():
                path = Path(args.outdir) / f"sheet_{a + 1}.csv"
                write_sheet(path, list(msgs.values()), mine)
                print(f"{path}: {len(mine)} сообщений")
        elif args.cmd in ("build", "validate"):
            chats = {(row.get("msg_id") or "").split(":")[0] for sheet in args.sheets for row in read_sheet(sheet)}
            known = {}
            for chat in chats - {""}:
                msgs = _load_chat_messages(chat)
                if msgs:
                    known[chat] = {a.id for m in msgs for a in m.attachments}
            if args.cmd == "validate":          # каждая таблица отдельно: одно сообщение может быть у двух разметчиков
                results = [build_labels([sheet], disciplines, known) for sheet in args.sheets]
                errors = [e for _, errs in results for e in errs]
                labels = {k: v for part, _ in results for k, v in part.items()}
            else:                                # build: таблицы одного разметчика
                labels, errors = build_labels(args.sheets, disciplines, known)
            for e in errors:
                print("ОШИБКА", e)
            if errors:
                return 1
            if args.cmd == "build":
                write_labels(args.out, labels)
                print(f"Записано {len(labels)} меток в {args.out}")
            else:
                print(f"Таблицы в порядке: {len(labels)} меток")
        elif args.cmd == "agreement":
            report = agreement(read_labels(args.first), read_labels(args.second))
            print(json.dumps(report, ensure_ascii=False, indent=2)) if args.json else _print_agreement(report)
            return 0 if report.get("passed", False) else 1
        elif args.cmd == "diff":
            diffs = disagreements(read_labels(args.first), read_labels(args.second))
            for d in diffs:
                print(d["msg_id"], {f: {"первый": v[0], "второй": v[1]} for f, v in d["fields"].items()})
            print(f"Спорных сообщений: {len(diffs)}")
        elif args.cmd == "merge":
            resolved = read_labels(args.resolved) if args.resolved else None
            write_labels(args.out, merge(read_labels(args.first), read_labels(args.second), resolved))
            print(f"Итоговый набор записан в {args.out}")
    except (LabelError, FileNotFoundError, ValidationError) as e:
        print("ОШИБКА", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
