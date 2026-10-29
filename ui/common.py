"""Общие подписи интерфейса: названия и цвета дисциплин берутся из config/disciplines.yaml."""
from src.config import DEFAULT_COLOR, discipline_color, discipline_name

# значки по ключам дисциплин; для остальных значок по умолчанию
ICONS = {"elektro": "⚡", "models": "🗃️", "algo": "🧮"}
DEFAULT_ICON = "📘"

# ключи старого макета (MockProvider), которых нет в конфиге
LEGACY_NAMES = {"electro": "Электротехника", "probability": "Теория вероятностей",
                "data_models": "Модели данных", "programming": "Программирование", "math": "Математика"}
LEGACY_COLORS = {"electro": "#4F46E5", "probability": "#0891B2", "data_models": "#DC2626",
                 "programming": "#7C3AED", "math": "#059669"}

STATUS_NAMES = {"active": "Действует", "moved": "Перенесён", "done": "Выполнен",
                "cancelled": "Отменён", "pending": "Ждёт подтверждения"}
BIND_NAMES = {"same_message": "в сообщении с заданием", "same_author_near": "от того же автора рядом",
              "reply_context": "в ответе или в сообщении, на которое ответили"}


def dname(key: str) -> str:
    """Русское название дисциплины (неизвестный ключ возвращается как есть)."""
    name = discipline_name(key)
    return name if name != key else LEGACY_NAMES.get(key, key)


def dcolor(key: str) -> str:
    color = discipline_color(key)
    return color if color != DEFAULT_COLOR else LEGACY_COLORS.get(key, "#4F46E5")


def dlabel(key: str) -> str:
    """Значок и название: «⚡ Электротехника»."""
    return f"{ICONS.get(key, DEFAULT_ICON)} {dname(key)}"

ROLE_NAMES = {"starosta": "староста", "teacher": "преподаватель", "student": "студент", "unknown": "неизвестно"}


def fmt_date(value: str | None, with_time: bool = False) -> str:
    """ISO-строка в «30.10.2026» (или «12.11.2026 10:00», если время не 23:59)."""
    from datetime import datetime
    if not value:
        return "Срок не указан"
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return value
    if with_time and (moment.hour, moment.minute) != (23, 59):
        return moment.strftime("%d.%m.%Y %H:%M")
    return moment.strftime("%d.%m.%Y")
