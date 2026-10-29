"""Роль 3: обсуждение вокруг задания. ЗАГЛУШКА (docs/contracts.md, раздел 4)."""
from src import _fixture_data as fx
from src.schemas import Deadline, SearchHit

IS_STUB = True


def get_discussion(deadline: Deadline, top_k: int = 5) -> list[SearchHit]:
    """Фрагменты того же чата, кроме тех, что состоят только из сообщения-объявления."""
    chat = deadline.source_msg.split(":")[0]
    found = [h for h in fx.hits() if h.chat == chat and set(h.msg_ids) != {deadline.source_msg}]
    return found[:max(0, min(8, top_k))]
