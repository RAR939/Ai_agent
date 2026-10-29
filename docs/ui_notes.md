# Интерфейс и визуализация

Роль 6. Интерфейс на Python и Streamlit, четыре вкладки: «Дедлайны» (календарь, очередь подтверждений, история переноса, **карточка задания**),
«Чат», «Расписание», «Источники». Как пользоваться: `docs/user_guide.md`. Как устроен: `docs/architecture.md`.

## Запуск
Из корня проекта с активным окружением:
```bash
streamlit run ui/app.py            # http://localhost:8501, настройки в .streamlit/config.toml
```
По умолчанию интерфейс показывает выдуманные данные (`ui.use_mock: true`). Настоящие данные: `ui.use_mock: false` в `config/config.local.yaml`.
Пароль на вход: переменная окружения `HELPER_UI_PASSWORD`. На сервере: `docs/server_setup.md`.

## Устройство
- `ui/app.py`: страница, вкладки, вход по паролю (`ui/auth.py`).
- `ui/provider.py`: `Provider` (контракт), `MockProvider` (выдуманные данные), `RealProvider` (настоящие модули), `make_provider()` по `ui.use_mock`.
- `ui/tabs/`: `deadlines.py` (календарь и карточка через `card.py`), `chat.py`, `schedule.py`, `sources.py`.
- `ui/common.py`: названия и цвета дисциплин из `config/disciplines.yaml`, подписи статусов. `ui/highlight.py`: подсветка срока, задания и дисциплины в тексте сообщения.
