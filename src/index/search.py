"""Роль 3: гибридный поиск. ЗАГЛУШКА (docs/contracts.md, раздел 4): фиксированные фрагменты мини-чата."""
from src import _fixture_data as fx
from src.schemas import SearchHit

IS_STUB = True


def search(query: str, chat: str | None = None,
           discipline: str | None = None,
           date_from: str | None = None, date_to: str | None = None,
           role: str | None = None, top_k: int = 5) -> list[SearchHit]:
    """Фильтры chat, discipline, role и даты работают, сам запрос только проверяется на пустоту."""
    if not query.strip():
        return []
    result = []
    for h in fx.hits():
        if chat and h.chat != chat or discipline and h.discipline != discipline or role and role not in h.roles:
            continue
        if date_from and h.ts_to[:len(date_from)] < date_from or date_to and h.ts_from[:len(date_to)] > date_to:
            continue
        result.append(h)
    return result[:max(0, min(8, top_k))]
