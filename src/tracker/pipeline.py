"""Роль 4 (задача 4.8): конвейер «обработать новые сообщения чата».

Для каждого необработанного сообщения по порядку времени:
предфильтр -> модель (extract) -> даты (dates) -> сопоставление и запись (match) + файлы (attach).
Сообщение помечается обработанным независимо от результата (кроме случая, когда
модель недоступна: тогда сообщение остаётся в очереди на следующий запуск).

Запуск: python -m src.tracker.pipeline --chat elektro
"""
import argparse
import json
import logging

from src.schemas import Deadline, Message, Report
from src.tracker import attach, common, dates, db, extract, match, prefilter

log = logging.getLogger(__name__)


def _candidate(msg: Message, ex, discipline: str, chat_msgs: list[Message]) -> Deadline:
    """Собирает Deadline из ответа модели; даты считает код."""
    action = ex.action or "new"
    if action == "cancel":
        due_at, fuzzy, due_text = None, False, ex.due_text or "отмена"
    else:
        due_at, fuzzy = dates.resolve_due(ex.due_text or "", msg.ts, discipline)
        due_text = ex.due_text or "не указан"
    return Deadline(
        discipline=discipline, kind=ex.kind or "other", task=(ex.task or "Задание").strip(),
        due_at=due_at, due_text=due_text, fuzzy=fuzzy, status="active", source_msg=msg.id,
        confidence=ex.confidence, attachments=attach.collect_files(msg, chat_msgs))


def process_new(chat_id: str) -> Report:
    """Обрабатывает новые сообщения чата и возвращает отчёт. Повторный запуск ничего не меняет."""
    chat_msgs = common.load_chat(chat_id)
    by_id = {m.id: m for m in chat_msgs}
    index = {m.id: i for i, m in enumerate(chat_msgs)}
    done = db.processed_ids(chat_id)
    deadline_ids = db.deadline_msg_ids(chat_id)
    context_size = int(common.tracker_cfg()["context_messages"])
    rep = dict(processed=0, added=0, moved=0, cancelled=0, pending=0, skipped_prefilter=0, failed=0)

    def ts_of(msg_id: str) -> str | None:
        m = by_id.get(msg_id)
        return m.ts if m else None

    for msg in chat_msgs:
        if msg.id in done:
            continue
        try:
            if not prefilter.looks_like_deadline(msg, by_id, deadline_ids):
                rep["skipped_prefilter"] += 1
                db.mark_processed(msg.id, False)
                rep["processed"] += 1
                continue
            i = index[msg.id]
            previous = chat_msgs[max(0, i - context_size):i]
            parent = by_id.get(msg.reply_to) if msg.reply_to else None
            ex = extract.extract_deadline(msg, previous, parent)
            if ex is None:                          # негодный JSON дважды: в логе, идём дальше
                rep["failed"] += 1
                db.mark_processed(msg.id, False)
                rep["processed"] += 1
                continue
            if not ex.has_deadline:
                db.mark_processed(msg.id, False)
                rep["processed"] += 1
                continue
            discipline = extract.resolve_discipline(ex, msg)
            if discipline is None:                  # ключа дисциплины нет: записать нельзя
                extract._log("extract_failures.jsonl", {
                    "ts": common.now_iso(), "msg_id": msg.id, "prompt_version": extract.PROMPT_VERSION,
                    "error": f"не определена дисциплина (ответ модели: {ex.discipline!r})"})
                rep["failed"] += 1
                db.mark_processed(msg.id, True)
                deadline_ids.add(msg.id)
                rep["processed"] += 1
                continue
            cand = _candidate(msg, ex, discipline, chat_msgs)
            outcome = match.apply_candidate(cand, ex.action, msg.ts, msg.text, ts_of)
            db.mark_processed(msg.id, True)
            deadline_ids.add(msg.id)
            rep["processed"] += 1
            key = {"added": "added", "moved": "moved", "cancelled": "cancelled",
                   "pending": "pending"}.get(outcome.kind)
            if key:
                rep[key] += 1
        except extract.ModelUnavailable as e:
            log.error("Модель недоступна, остановка конвейера: %s", e)
            rep["failed"] += 1
            break                                   # сообщение останется необработанным
        except Exception:
            log.exception("Ошибка обработки сообщения %s", msg.id)
            rep["failed"] += 1                      # не помечаем: повторится при следующем запуске
    return Report(**rep)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Обработка новых сообщений чата трекером")
    parser.add_argument("--chat", required=True, help="идентификатор чата, например elektro")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(json.dumps(process_new(args.chat).model_dump(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
