# Документация проекта «Анализатор учебных чатов»

Начните с `README.md` в корне (быстрый старт). Дальше по тому, кто вы.

## Пользователь (студент)
| Документ | Что внутри |
|---|---|
| [user_guide.md](user_guide.md) | как подключиться, что есть в интерфейсе, какие вопросы задавать, как подтверждать записи, ограничения |

## Администратор (тот, кто ведёт сервер и данные)
| Документ | Что внутри |
|---|---|
| [server_setup.md](server_setup.md) | запуск на сервере с GPU: Ollama, приложение, служба, SSH-туннель, защита |
| [operations.md](operations.md) | жизненный цикл данных, обновление, резервные копии, логи, напоминания, разбор неполадок |
| [configuration.md](configuration.md) | все настройки `config/*.yaml`, переменные окружения, промпты |

## Разработчик
| Документ | Что внутри |
|---|---|
| [architecture.md](architecture.md) | слои, модули, потоки данных, где что хранится, режимы запуска |
| [contracts.md](contracts.md) | **источник правды**: схемы данных, сигнатуры функций, база SQLite, форматы файлов |
| [mcp_tools.md](mcp_tools.md) | 9 MCP-инструментов агента |
| [CONTRIBUTING.md](CONTRIBUTING.md) | ветки, pull request, ревью, правило `contract-change` |
| [known_issues.md](known_issues.md) | открытые вопросы, расхождения в документах, ограничения, что не проверено |

## Данные, качество и исследование
| Документ | Что внутри |
|---|---|
| [project.md](project.md) | описание проекта, задачи, риски, основа для статьи |
| [role_1.md](role_1.md) | задачи роли 1 (тимлид), общие правила, структура репозитория |
| [annotation_guide.md](annotation_guide.md) | руководство по разметке эталона (Q1) |
| [tracker_notes.md](tracker_notes.md), [tracker_eval.md](tracker_eval.md) | трекер: решения, ограничения, метрики на синтетике |
| [agent_eval.md](agent_eval.md) | оценка агента (метрики и таблица, цифр пока нет) |
| [retrieval_experiments.md](retrieval_experiments.md) | эксперименты поиска (цифр пока нет) |
| [ui_notes.md](ui_notes.md) | интерфейс: что есть и как запускать |

Документация по модулям лежит рядом с кодом: `src/ingest/README.md`, `src/index/README.md`, `src/tracker/README.md`, `ui/README.md`, `eval/README.md`.
Шаблон расписания: `docs/schedule_template.xlsx`. Проверка, что ссылки и команды в документах не устарели: `tests/test_docs.py`.
