import chromadb
from .common import ROOT,cfg

def collection():
    p=ROOT/'data/chroma';p.mkdir(parents=True,exist_ok=True)
    return chromadb.PersistentClient(path=str(p)).get_or_create_collection('chat_chunks',metadata={'hnsw:space':'cosine'})
def embed(texts):
    import ollama
    result=ollama.embed(model=cfg()['models']['embed'],input=texts)
    return result['embeddings']
def upsert(chunks):
    col=collection()
    for start in range(0,len(chunks),16):
        batch=chunks[start:start+16]
        col.upsert(ids=[x.id for x in batch],embeddings=embed([x.text for x in batch]),documents=[x.text for x in batch],metadatas=[{'chat':x.chat,'ts_from':x.ts_from,'ts_to':x.ts_to,'roles':','.join(x.roles),'msg_ids':','.join(x.msg_ids),'discipline':x.discipline or ''} for x in batch])
def rank(query, eligible, count=20):
    if not eligible:return []
    col=collection()
    if col.count()==0:return []
    res=col.query(query_embeddings=embed([query]),n_results=min(col.count(),max(count*3,count)))
    return [(i,1-float(d)) for i,d in zip(res['ids'][0],res['distances'][0]) if i in eligible][:count]
