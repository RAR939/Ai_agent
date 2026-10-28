# path/to/docs/mcp_tools.md
# MCP Инструменты: Анализатор учебных чатов

Все инструменты возвращают JSON-строку. При ошибке возвращается `{"error": "текст на русском"}`.

| Инструмент | Назначение | Параметры | Возвращает |
| :--- | :--- | :--- | :--- |
| `search_messages` | Поиск по смыслу в чатах. Использовать для общих вопросов, обсуждений, требований. | `query` (str), `discipline` (str, opt), `period_days` (int, 30), `role` (str, opt) | Список `SearchHit` (до 5) |
| `read_new_messages` | Показывает новые, еще не обработанные сообщения. | `chat` (str), `since` (str, opt) | Список `Message` (до 30) |
| `list_deadlines` | Список дедлайнов. Использовать для вопросов "что сдать", "когда сдавать". | `days_ahead` (int, 14), `discipline` (str, opt), `status` (str, "active") | Список `Deadline` |
| `add_deadline` | Добавить новый дедлайн. | `discipline` (str), `task` (str), `due_text` (str), `source_msg` (str) | `Deadline` или `PendingItem` |
| `update_deadline` | Перенести срок дедлайна. | `id` (int), `new_due_text` (str), `source_msg` (str) | `Deadline` или `PendingItem` |
| `get_schedule` | Занятия за период. Использовать для вопросов "какие пары", "расписание". | `date_from` (str), `date_to` (str, opt), `discipline` (str, opt) | Список `Lesson` |
| `load_schedule` | Загрузить расписание из файла. | `path` (str) | `ScheduleImport` |
| `get_attachments` | Файлы, прикрепленные к дедлайну (методички, шаблоны). | `deadline_id` (int) | Список `AttachedFile` |
| `process_new_messages` | Запускает конвейер поиска дедлайнов в новых сообщениях. | `chat` (str) | `Report` |