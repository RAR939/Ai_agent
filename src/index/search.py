import threading
from datetime import datetime
from functools import lru_cache
from src.schemas import SearchHit
from .common import all_chunks,cfg
from .lexical import rank as lexical_rank
from .vector_store import rank as vector_rank

_rerank_lock=threading.Lock()
@lru_cache(maxsize=2)
def _reranker(name):
    # модель грузится один раз за процесс (раньше при каждом поиске); на сервере с GPU sentence-transformers берёт CUDA сам
    from sentence_transformers import CrossEncoder
    return CrossEncoder(name)

def search(query: str, chat: str | None = None, discipline: str | None = None, date_from: str | None = None, date_to: str | None = None, role: str | None = None, top_k: int = 5) -> list[SearchHit]:
    c=cfg()['retrieval'];chunks=all_chunks();top_k=max(0,min(8,top_k))
    def ok(x):
        if chat and x.chat!=chat:return False
        if discipline and x.discipline!=discipline:return False
        if role and role not in x.roles:return False
        if date_from and x.ts_to[:len(date_from)]<date_from:return False
        if date_to and x.ts_from[:len(date_to)]>date_to:return False
        return True
    eligible={x.id for x in chunks if ok(x)}
    if not eligible or not query.strip() or not top_k:return []
    n=c.get('candidates',20)
    a=vector_rank(query,eligible,n);b=lexical_rank(query,chunks,eligible,n)
    scores={}
    for ranking in (a,b):
        for rank,(id,_) in enumerate(ranking,1):scores[id]=scores.get(id,0)+1/(60+rank)
    ids=sorted(scores,key=scores.get,reverse=True)[:c.get('rerank_top',15)]
    if c.get('use_reranker',True) and ids:
        model=_reranker(cfg()['models'].get('reranker', cfg()['models'].get('renamer', 'BAAI/bge-reranker-v2-m3')))
        lookup={x.id:x for x in chunks}
        with _rerank_lock:
            values=model.predict([(query,lookup[id].text) for id in ids])
        scored=sorted(zip(ids,map(float,values)),key=lambda x:x[1],reverse=True)
    else:scored=[(id,scores[id]) for id in ids]
    lookup={x.id:x for x in chunks}
    return [SearchHit(chunk_id=id,chat=lookup[id].chat,text=lookup[id].text[:1500],ts_from=lookup[id].ts_from,ts_to=lookup[id].ts_to,roles=lookup[id].roles,msg_ids=lookup[id].msg_ids,discipline=lookup[id].discipline,score=score) for id,score in scored[:top_k]]
