"""Роль 3: ответ по найденным фрагментам. ЗАГЛУШКА (docs/contracts.md, раздел 4)."""
from src.index.search import search
from src.schemas import Answer

IS_STUB = True


def answer(question: str, **filters) -> Answer:
    hits = search(question, **filters)
    if not hits:
        return Answer(text="В материалах этого нет", sources=[], refused=True, prompt_version="answer_v1")
    return Answer(text=f"Заглушка: ближайший фрагмент от {hits[0].ts_from[:10]} ({hits[0].chunk_id}).",
                  sources=hits, refused=False, prompt_version="answer_v1")
