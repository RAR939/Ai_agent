# Настройки

Файлы в `config/`: `config.yaml` (общие настройки), `disciplines.yaml` (дисциплины), `roles.yaml` (шаблон имён). Загружает всё
`src.config.load_config()`. Локальные значения не правят общий файл:
- `config/config.local.yaml` (не в git) накладывается на `config.yaml` **по разделам** (достаточно указать только изменяемые ключи);
- `config/roles.local.yaml` (не в git) заменяет шаблон `roles.yaml` настоящими именами.
Пример для сервера (`config/config.local.yaml`):
```yaml
ui:
  use_mock: false
models:
  llm: "qwen3:14b"
```

## config.yaml

| Ключ | Значение по умолчанию | Что означает |
|---|---|---|
| `models.llm` | `qwen3:8b` | модель для ответов агента и разбора сообщений |
| `models.embed` | `bge-m3` | модель эмбеддингов для поиска |
| `models.reranker` | `BAAI/bge-reranker-v2-m3` | реранкер (sentence-transformers, скачивается из Hugging Face один раз) |
| `models.temperature` | `0.1` | температура ответов агента |
| `models.host` | пусто | адрес Ollama (`http://сервер:11434`); пусто: `OLLAMA_HOST` или локальная |
| `models.timeout_sec` | `120` | ожидание ответа Ollama |
| `retrieval.chunk_strategy` | `window` | разбиение на чанки: `window`, `thread` (по цепочкам ответов), `day` (по дням) |
| `retrieval.window_size` / `window_step` | `10` / `5` | размер окна и шаг, в сообщениях |
| `retrieval.max_chunk_chars` | `1800` | предел длины чанка |
| `retrieval.candidates` | `20` | сколько кандидатов берёт каждый из двух поисков |
| `retrieval.rerank_top` | `15` | сколько лучших после слияния идёт в реранкер |
| `retrieval.top_k` | `5` | сколько фрагментов в ответе (не больше 8) |
| `retrieval.min_score` | `0.3` | порог релевантности реранкера; ниже: «В материалах этого нет». Без реранкера не применяется |
| `retrieval.use_reranker` | `true` | включить реранкер (на CPU медленный) |
| `retrieval.bm25` | `k1: 1.5, b: 0.75` | параметры лексического поиска |
| `tracker.prefilter_keywords` | список | слова-признаки срока (по леммам) |
| `tracker.prefilter_strong_keywords` | список | слова отмены и переноса: пропускают сообщение и без признака времени |
| `tracker.prefilter_time_words` | список | слова-признаки времени |
| `tracker.remind_hours` | `24` | за сколько часов до срока напоминать |
| `tracker.context_messages` | `3` | сколько предыдущих сообщений видит модель при разборе |
| `tracker.date_rollover_days` | `30` | дата дд.мм старше стольких дней уходит на следующий год |
| `tracker.confidence_threshold` | `0.7` | ниже: запись ждёт подтверждения человека |
| `tracker.similarity_threshold` | `85` | похожесть названий заданий (0 до 100) для сопоставления |
| `tracker.attach_window_min` | `10` | окно (минуты) для файлов того же автора |
| `tracker.attach_exts` | `pdf, docx, ...` | какие расширения считаются документами |
| `tracker.attach_max_per_msg` | `5` | не более файлов с одного сообщения |
| `schedule.semester_start` / `semester_end` | `2026-09-01` / `2026-12-27` | границы семестра (до конца разворачивается Excel-расписание) |
| `schedule.first_week_parity` | `odd` | чётность первой недели: `odd` или `even` |
| `schedule.holidays` | `[]` | даты без занятий |
| `agent.max_steps` | `5` | не более шагов агента на вопрос |
| `agent.timeout_sec` | `120` | ожидание ответа инструмента |
| `agent.prompt_version` | `agent_v2` | файл `config/prompts/<версия>.txt`; пишется в лог трассы |
| `agent.mode` | `llm` | `llm` (модель выбирает инструмент) или `rules` (запасной режим по ключевым словам) |
| `agent.routing_rules` | словарь | основы слов для режима `rules` |
| `ui.use_mock` | `true` | `true`: интерфейс на выдуманных данных, `false`: на настоящих |
| `paths.data` | `data` | папка данных |
| `paths.db` | `data/helper.db` | база SQLite |
| `paths.logs` | `logs` | папка логов |

## disciplines.yaml
Ключ латиницей (`elektro`), `name` (по-русски, для интерфейса), `color` (`#rrggbb`), `aliases` (разговорные названия). Алиасы ищутся по леммам без учёта
регистра (склонения: «по электротехнике»); аббревиатуры заглавными (`ЭТ`, `МД`) только в таком же написании; ключ и название тоже считаются алиасами.
Повтор одного алиаса у двух дисциплин запрещён (ошибка при загрузке).

## Переменные окружения

| Переменная | Что делает |
|---|---|
| `OLLAMA_HOST` | адрес Ollama; важнее `models.host`; доходит и до MCP-сервера |
| `OLLAMA_API_KEY` | токен: уходит заголовком `Authorization: Bearer` (если перед Ollama стоит прокси с проверкой) |
| `HELPER_DB` | путь к базе вместо `paths.db` (тесты, несколько копий приложения) |
| `HELPER_UI_PASSWORD` | включает вход по паролю в интерфейсе |
| `HF_HOME` | где искать скачанный реранкер (только для проверки в `scripts/check_env.py`) |
Секреты (токен, пароль) хранятся только в окружении или в файле, которого нет в git (для службы `/etc/helper.env`).

## Промпты (`config/prompts/`)
`agent_v1.txt`, `agent_v2.txt` (агент; в `agent_v2` вместо `{today}` подставляется дата и время), `extract_v1.txt` (разбор сообщений трекером, версия в `labels`
и `logs/extract_calls.jsonl`), `answer_v1.txt` (ответ по найденным фрагментам). Новая версия это новый файл: старые сохраняются для сравнения.
