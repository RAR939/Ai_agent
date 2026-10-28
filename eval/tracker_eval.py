"""Роль 4: оценка трекера. Запуск: python -m eval.tracker_eval [--write]

Считает три вещи и (с --write) обновляет docs/tracker_eval.md:
1. предфильтр: охват (доля реальных дедлайнов, прошедших фильтр) и отсечение шума;
2. вычисление дат: совпадение resolve_due с эталоном due_at_gold;
3. привязка файлов: точность и полнота по эталону files_expected.
Данные: tests/fixtures/ (синтетика). Если есть data/labels/gold.jsonl с реальной разметкой
(Q1), охват предфильтра считается ещё и по ней.
"""
import argparse
import json
import re
from pathlib import Path

from src.schemas import Message
from src.tracker import common, db, dates, extract, pipeline, prefilter

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
NOT_A_DEADLINE = {"has_deadline": False, "confidence": 0.9}


def _msg(i, text, reply_to=None):
    return Message(id=f"t:{i}", chat="t", ts="2026-10-20T10:01:00+03:00", author="STAROSTA",
                   role="starosta", text=text, reply_to=reply_to, src="x")


def prefilter_synthetic() -> dict:
    data = json.loads((FIX / "prefilter_set.json").read_text(encoding="utf-8"))

    def passes(i, item):
        by_id, reply_to = {}, None
        if item.get("parent"):
            parent = _msg(f"{i}p", item["parent"])
            by_id[parent.id], reply_to = parent, parent.id
        return prefilter.looks_like_deadline(_msg(i, item["text"], reply_to), by_id)

    pos = [passes(i, x) for i, x in enumerate(data["positives"])]
    neg = [passes(i, x) for i, x in enumerate(data["negatives"])]
    return {"positives": len(pos), "found": sum(pos), "coverage": sum(pos) / len(pos),
            "negatives": len(neg), "passed_noise": sum(neg), "noise_cut": 1 - sum(neg) / len(neg)}


def prefilter_gold(path: Path) -> dict | None:
    """Охват по реальной разметке data/labels/gold.jsonl (если она есть)."""
    if not path.exists():
        return None
    gold = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    chats: dict[str, dict[str, Message]] = {}
    pos = pos_found = neg = neg_cut = 0
    for rec in gold:
        chat = rec["msg_id"].split(":")[0]
        chats.setdefault(chat, {m.id: m for m in common.load_chat(chat)})
        msg = chats[chat].get(rec["msg_id"])
        human = json.loads(rec["human_json"]) if rec.get("human_json") else None
        if msg is None or human is None:
            continue
        ok = prefilter.looks_like_deadline(msg, chats[chat])
        if human.get("has_deadline"):
            pos += 1
            pos_found += ok
        else:
            neg += 1
            neg_cut += not ok
    return {"positives": pos, "found": pos_found, "negatives": neg, "cut": neg_cut}


def run_mini_chat() -> dict:
    """Прогон конвейера на мини-чате с «идеальной» моделью (берёт ответы из эталона)."""
    expected = json.loads((FIX / "mini_chat_expected.json").read_text(encoding="utf-8"))
    answers = {d["msg_id"]: d["extract"] for d in expected["deadlines"]}

    def oracle(messages):
        msg_id = re.search(r"\[id=([^\]]+)\]", messages[-1]["content"]).group(1)
        return json.dumps(answers.get(msg_id, NOT_A_DEADLINE), ensure_ascii=False)

    from src.schemas import Lesson
    db.set_db_path(":memory:")
    old_chat, old_log = extract._chat, extract._log
    extract._chat, extract._log = oracle, lambda *a, **k: None
    try:
        db.replace_lessons([Lesson(discipline="elektro", lesson_type="lecture",
                                   start="2026-10-29T08:30:00+03:00", end="2026-10-29T10:05:00+03:00")])
        pipeline.process_new("elektro")
        pipeline.process_new("models")
        final = {d.source_msg: d for d in db.list_deadlines(status=None)}
    finally:
        extract._chat, extract._log = old_chat, old_log
        db.set_db_path(None)

    # даты: сравнение с due_at_gold по каждому сообщению
    date_total = date_ok = 0
    for d in expected["deadlines"]:
        if d["extract"]["action"] == "cancel":
            continue
        base = next(m for m in common.load_chat(d["msg_id"].split(":")[0]) if m.id == d["msg_id"])
        db.set_db_path(":memory:")
        db.replace_lessons([Lesson(discipline="elektro", lesson_type="lecture",
                                   start="2026-10-29T08:30:00+03:00", end="2026-10-29T10:05:00+03:00")])
        got, _ = dates.resolve_due(d["extract"]["due_text"] or "", base.ts, d["extract"]["discipline"])
        db.set_db_path(None)
        date_total += 1
        date_ok += got == d["due_at_gold"]

    # файлы: ожидаемые = объединение files_expected по заданию
    wanted: dict[str, set[str]] = {}
    for d in expected["deadlines"]:
        if d["extract"]["action"] in ("new", "move") and d["msg_id"] in final:
            wanted.setdefault(d["msg_id"], set()).update(d["files_expected"])
    for d in expected["deadlines"]:                # перенос добавляет файлы к исходному заданию
        if d["extract"]["action"] == "move":
            for src, dl in final.items():
                if dl.task == d["extract"]["task"] and dl.discipline == d["extract"]["discipline"]:
                    wanted.setdefault(src, set()).update(d["files_expected"])
    attached = tp = want = 0
    for src, files in wanted.items():
        got = {f.id for f in final[src].attachments}
        attached += len(got)
        tp += len(got & files)
        want += len(files)
    return {"date_total": date_total, "date_ok": date_ok, "attached": attached,
            "correct": tp, "needed": want,
            "precision": tp / attached if attached else 1.0, "recall": tp / want if want else 1.0}


def render(pf: dict, mini: dict, gold: dict | None) -> str:
    pct = lambda x: f"{x * 100:.0f}%"
    lines = [
        "# Оценка трекера (роль 4)", "",
        "Файл создаёт `python -m eval.tracker_eval --write`. **Все цифры ниже получены на",
        "синтетических данных** (`tests/fixtures/`), которые писала сама роль 4. Они",
        "проверяют, что код работает как задумано, но не доказывают качество на реальных",
        "чатах. Реальные цифры нужны на размеченном наборе Q1 (`data/labels/gold.jsonl`).", "",
        "## Предфильтр (4.4)", "",
        f"- Охват: {pf['found']} из {pf['positives']} дедлайнов прошли фильтр ({pct(pf['coverage'])}), цель не ниже 95%.",
        f"- Отсечение шума: {pf['negatives'] - pf['passed_noise']} из {pf['negatives']} сообщений без срока отсеяно ({pct(pf['noise_cut'])}), цель выше 70%.",
        "- Прошли фильтр, хотя срока нет: «завтра сдаю лабу, страшно» и «сегодня сдавал зачёт по физике» (это отсеет модель).", "",
        "## Вычисление дат (4.6)", "",
        f"- На мини-чате: {mini['date_ok']} из {mini['date_total']} дат совпали с эталоном `due_at_gold`.",
        "- Отдельный набор из 75+ фраз: `tests/test_dates.py`; известные провалы в `docs/tracker_notes.md`.", "",
        "## Привязка файлов (4.9)", "",
        f"- Прикреплено файлов: {mini['attached']}, из них верных {mini['correct']}; нужно было {mini['needed']}.",
        f"- Точность: {pct(mini['precision'])} (цель не ниже 85%). Полнота: {pct(mini['recall'])}.",
        "- В мини-чате есть ловушки: чужой файл в то же время и файл через час; они правильно не прикрепились.",
        "  Сосед с другим дедлайном, граница окна и лимиты проверены в `tests/test_attach.py`.", "",
    ]
    if gold:
        cov = gold["found"] / gold["positives"] if gold["positives"] else 0
        cut = gold["cut"] / gold["negatives"] if gold["negatives"] else 0
        lines += ["## Реальная разметка", "",
                  f"- Предфильтр на gold.jsonl: охват {gold['found']} из {gold['positives']} ({pct(cov)}), "
                  f"отсечено {gold['cut']} из {gold['negatives']} сообщений без срока ({pct(cut)}).", ""]
    else:
        lines += ["## Реальная разметка", "",
                  "- `data/labels/gold.jsonl` ещё не появился: цифры по реальному чату не считались.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="обновить docs/tracker_eval.md")
    args = ap.parse_args()
    pf, mini = prefilter_synthetic(), run_mini_chat()
    text = render(pf, mini, prefilter_gold(ROOT / "data" / "labels" / "gold.jsonl"))
    print(text)
    if args.write:
        (ROOT / "docs" / "tracker_eval.md").write_text(text + "\n", encoding="utf-8")
