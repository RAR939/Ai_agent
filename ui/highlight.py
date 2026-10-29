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