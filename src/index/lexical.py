import re, pickle, hashlib, threading
from functools import lru_cache
from rank_bm25 import BM25Okapi
from .common import ROOT,cfg
@lru_cache(maxsize=30000)
def lemma(token):
    import pymorphy3
    if not hasattr(lemma,'morph'):lemma.morph=pymorphy3.MorphAnalyzer()
    return lemma.morph.parse(token)[0].normal_form

def tokenize(text):
    text=text.lower().replace('ё','е')
    text=re.sub(r'\b(?:лр|лаб(?:а|у|е|ы|ораторная)?)\s*[-№.]?\s*(\d+)\b',r' лаб\1 ',text)
    return [x if re.fullmatch(r'лаб\d+',x) else lemma(x) for x in re.findall(r'\w+',text)]
def save(chunks):
    p=ROOT/'data/bm25.pkl';p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('wb') as f:pickle.dump({'ids':[x.id for x in chunks],'tokens':[tokenize(x.text) for x in chunks]},f)
_bm25_lock=threading.Lock()
_bm25_cache={}
def _model(chunks,k1,b):
    """Модель BM25 для набора чанков; пересобирается только если тексты или параметры изменились."""
    digest=hashlib.blake2b('\n'.join(f'{x.id}\t{x.text}' for x in chunks).encode()+f'|{k1}|{b}'.encode(),digest_size=16).hexdigest()
    with _bm25_lock:
        if digest not in _bm25_cache:
            _bm25_cache.clear()
            _bm25_cache[digest]=BM25Okapi([tokenize(x.text) for x in chunks],k1=k1,b=b)
        return _bm25_cache[digest]
def rank(query, chunks, eligible, count=20):
    if not chunks:return []
    conf=cfg()['retrieval'].get('bm25',{})
    model=_model(chunks,conf.get('k1',1.5),conf.get('b',0.75))
    scores=model.get_scores(tokenize(query))
    return [(chunks[i].id,float(scores[i])) for i in sorted(range(len(chunks)),key=lambda i:scores[i],reverse=True) if chunks[i].id in eligible and scores[i]>0][:count]
