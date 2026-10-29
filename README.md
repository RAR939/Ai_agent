# Анализатор учебных чатов

Локальный ИИ-агент с RAG и MCP: читает обезличенные учебные чаты Telegram, отвечает на вопросы со ссылками на источники,
сам находит дедлайны и переносы, прикрепляет к заданиям файлы из чата и сопоставляет сроки с расписанием.
Всё работает на ноутбуке без интернета (Ollama, модель до 8B). Подробнее: `docs/project.md`.

## Быстрый старт (10 минут)

```bash
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
ollama pull qwen3:8b && ollama pull bge-m3                # на 8 ГБ памяти вместо 8b возьмите qwen3:4b и поправьте config/config.yaml
python scripts/check_env.py                               # что готово и чего не хватает
pytest                                                    # тесты не требуют Ollama
streamlit run ui/app.py                                   # интерфейс, http://localhost:8501
```

Без настоящих данных интерфейс работает в режиме макета (`ui.use_mock: true` в `config/config.yaml`), а на «настоящих
данных» (`false`) берёт базу дедлайнов, расписание и индекс. Синтетический мини-чат из `tests/fixtures/` лежит в основе
тестов и демонстрации.

## Как это устроено

```
Экспорт Telegram (HTML + files/)      Расписание (.ics / .xlsx)
        │ парсер, обезличивание (роль 2)        │
   data/clean/<чат>.jsonl  ──┬────────────────────┤
                             │                    │
            индекс и поиск (роль 3)        трекер дедлайнов (роль 4)
            Chroma + BM25 + реранк         предфильтр, модель, даты, переносы, файлы, SQLite
                             └──────┬─────────────┘
                         MCP-сервер и агент (роль 5)
                                    │
                       интерфейс Streamlit (роль 6)
```

| Что | Где |
|---|---|
| Контракт данных (источник правды) | `docs/contracts.md`, `src/schemas.py` |
| Настройки (модели, пороги, пути, дисциплины) | `config/*.yaml`, `src/config.py` |
| Парсер, обезличивание, хранилище сообщений | `src/ingest/` |
| Индекс и поиск | `src/index/` |
| Трекер и расписание | `src/tracker/` |
| MCP-инструменты и агент | `src/mcp_server.py`, `src/agent.py`, `docs/mcp_tools.md` |
| Интерфейс | `ui/` |
| Тестовые данные | `tests/fixtures/` (мини-чат, эталон, файлы) |
| Оценка качества | `eval/`, `docs/tracker_eval.md`, `docs/agent_eval.md` |

## Рабочий процесс с данными

1. Положите обезличенный чат в `data/clean/<чат>.jsonl` (формат `Message`; делает роль 2). Папка `data/` не попадает в git.
2. Индекс: `python -m src.index.build --chat elektro` (нужна Ollama с `bge-m3`).
3. Дедлайны: кнопка «Обработать новые сообщения» во вкладке «Источники» или `python -m src.tracker.pipeline --chat elektro`.
4. Расписание: вкладка «Расписание» (шаблон Excel: `docs/schedule_template.xlsx`).
5. Вопросы агенту: вкладка «Чат» или `python -m src.agent "Что у меня горит на этой неделе?"` (из любой папки).

Реальные имена участников хранятся в `config/roles.local.yaml` (не в git), шаблон: `config/roles.yaml`.

## Тесты и качество

```bash
pytest                                  # весь набор; Ollama не нужна, модель подменена
python -m eval.tracker_eval             # метрики трекера на мини-чате
```
`tests/test_contracts.py` сверяет сигнатуры всех функций с разделом 4 контракта.

## Правила команды

Ветки `feature/<задача>-<кратко>`, слияние только через pull request и ревью не автором, любое изменение контракта с
пометкой `contract-change`. Данные чатов в репозиторий не попадают. Подробнее: `docs/CONTRIBUTING.md`.
