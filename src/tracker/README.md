# Трекер дедлайнов и расписание (роль 4)

Читает обезличенные сообщения чата, находит дедлайны, переносы и отмены, считает даты по
тексту и расписанию, прикрепляет файлы из чата. База: `data/helper.db` (SQLite, в git не
попадает). Другие модули ходят в неё **только через `db.py`**.

## Модули

| Файл | Что делает |
|---|---|
| `db.py`, `schema.sql` | таблицы, дедлайны, история переносов, очередь подтверждений, файлы, карточка |
| `schedule_import.py` | `.ics` и Excel -> занятия по датам; шаблон `docs/schedule_template.xlsx` |
| `schedule_query.py` | `lessons_on`, `lessons_between`, `next_lesson`, `lessons_tomorrow` |
| `prefilter.py` | отсев сообщений без срока (леммы + признаки времени) |
| `extract.py` | Ollama: сообщение -> `DeadlineExtract`; промпт `config/prompts/extract_v1.txt` |
| `dates.py` | «до пятницы», «завтра до 18:00», «на следующей паре по X» -> дата ISO |
| `match.py` | то же ли это задание; новый, перенос, отмена, очередь `pending` |
| `attach.py` | какие файлы относятся к дедлайну (по связям сообщений) |
| `pipeline.py` | `process_new(chat_id)` собирает всё вместе |
| `reminders.py` | уведомления ОС о дедлайнах в ближайшие часы |

## Запуск

```bash
pip install -r requirements.txt
pytest                                          # все тесты (Ollama не нужна)

# расписание
python -m src.tracker.schedule_import моё_расписание.xlsx --dry-run   # предпросмотр
python -m src.tracker.schedule_import моё_расписание.xlsx             # записать

# обработка чата (нужны Ollama с qwen3:8b и data/clean/<chat>.jsonl)
python -m src.tracker.pipeline --chat elektro

# напоминания (можно поставить в планировщик задач)
python -m src.tracker.reminders --hours 24

# оценка
python -m eval.tracker_eval --write
```

Из кода:

```python
from src.tracker import db, schedule_query
from src.tracker.pipeline import process_new

process_new("elektro")                       # -> Report
db.list_deadlines(date_from="2026-10-21", date_to="2026-10-31")
db.get_card(5)                               # дедлайн + история + файлы + обсуждение
db.list_pending(); db.resolve_pending(3, accept=True)
```

Подробности решений и ограничений: `docs/tracker_notes.md`, цифры: `docs/tracker_eval.md`.
