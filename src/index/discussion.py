from functools import lru_cache
from datetime import datetime,timedelta
from src.schemas import Deadline,SearchHit
from .search import search
from .common import cfg, messages

def get_discussion(deadline: Deadline, top_k: int = 5) -> list[SearchHit]:
    chat=deadline.source_msg.split(':')[0]
    return _discussion(deadline.model_dump_json(),chat,min(8,top_k))
@lru_cache(maxsize=128)
def _discussion(serialized,chat,top_k):
    deadline=Deadline.model_validate_json(serialized)
    ms=messages(chat);origin=next((m for m in ms if m.id==deadline.source_msg),None)
    if not origin:return []
    days=cfg()['retrieval'].get('discussion_window_days',7)
    dt=datetime.fromisoformat(origin.ts);lo=(dt-timedelta(days=days)).date().isoformat();hi=(dt+timedelta(days=days)).date().isoformat()
    query=f'{deadline.discipline} {deadline.task} требования отчёт оформление защита как сдавать {deadline.due_text}'
    results=search(query,chat=chat,date_from=lo,date_to=hi,top_k=8)
    excluded={deadline.source_msg}
    return [h for h in results if set(h.msg_ids)-excluded and h.score>=cfg()['retrieval'].get('min_score',0.3)][:top_k]
