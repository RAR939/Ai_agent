import html


COLORS = {
    "deadline": "#FFE08A",
    "task": "#BDE0FE",
    "discipline": "#CAFFBF",
}


def find_span(
    text: str,
    value: str,
    label: str,
) -> tuple[int, int, str] | None:
    start = text.find(value)

    if start == -1:
        return None

    return start, start + len(value), label


def highlight(
    text: str,
    spans: list[tuple[int, int, str]],
) -> str:
    valid_spans = []

    for start, end, label in spans:
        if (
            0 <= start < end <= len(text)
            and label in COLORS
        ):
            valid_spans.append((start, end, label))

    valid_spans.sort(key=lambda item: item[0])

    result = []
    last_position = 0

    for start, end, label in valid_spans:
        if start < last_position:
            continue

        result.append(
            html.escape(text[last_position:start])
        )

        fragment = html.escape(text[start:end])

        result.append(
            f'<mark style="'
            f'background-color:{COLORS[label]};'
            f'padding:2px 5px;'
            f'border-radius:5px;'
            f'color:#111827;'
            f'">'
            f'{fragment}'
            f'</mark>'
        )

        last_position = end

    result.append(
        html.escape(text[last_position:])
    )

    return "".join(result)

# ---------- автоматическая подсветка срока, задания и дисциплины ----------
import re  # noqa: E402

from src.config import load_config  # noqa: E402

_MONTHS = ("января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря")
_TASK_RE = re.compile(
    r"(?:лаб(?:ораторн\w*)?\.?(?:\s*работ\w*)?|лр|дз|домашн\w+(?:\s+(?:задани\w+|работ\w+))?|рубежк\w*|"
    r"контрольн\w+(?:\s+работ\w*)?|курсов\w+|экзамен\w*|зач[её]т\w*)(?:\s*[№#.]?\s*\d+)?", re.I)
_DEADLINE_RE = re.compile(
    rf"(?:(?:до|на|к|в|через)\s+)?(?:\d{{1,2}}\.\d{{1,2}}(?:\.\d{{2,4}})?|\d{{1,2}}\s+(?:{_MONTHS})|"
    r"понедельник\w*|вторник\w*|сред[аеуы]\b|четверг\w*|пятниц\w*|суббот\w*|воскресень\w*|"
    r"послезавтра|завтра|сегодня|на днях|скоро|следующей\s+паре|недел\w+|месяц\w*|\d+\s+дн\w+)"
    r"(?:\s+(?:в|к)\s+\d{1,2}:\d{2})?", re.I)


def _discipline_res() -> list[re.Pattern]:
    """Регулярки по алиасам и названиям дисциплин из config/disciplines.yaml (формы слов по основе)."""
    stems, abbrs = [], []
    for item in load_config()["disciplines"].values():
        for alias in item["aliases"] + [item["name"]]:
            if len(alias) >= 2 and alias.isalpha() and alias.isupper():
                abbrs.append(re.escape(alias))                   # ЭТ, МД: только заглавными и целым словом
            else:
                stems.append(re.escape(alias[:-1] if len(alias) > 5 else alias) + r"\w*")
    result = []
    if stems:
        result.append(re.compile(r"(?<!\w)(?:" + "|".join(sorted(stems, key=len, reverse=True)) + ")", re.I))
    if abbrs:
        result.append(re.compile(r"(?<!\w)(?:" + "|".join(abbrs) + r")(?!\w)"))
    return result


def auto_spans(text: str) -> list[tuple[int, int, str]]:
    """Участки текста со сроком, заданием и дисциплиной для highlight()."""
    spans = [(m.start(), m.end(), "task") for m in _TASK_RE.finditer(text)]
    spans += [(m.start(), m.end(), "deadline") for m in _DEADLINE_RE.finditer(text)]
    for pattern in _discipline_res():
        spans += [(m.start(), m.end(), "discipline") for m in pattern.finditer(text)]
    return spans
