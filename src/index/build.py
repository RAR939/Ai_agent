import json, hashlib, argparse
from .common import ROOT,messages,all_chunks
from .chunking import chunk_messages
from .vector_store import upsert,collection
from .lexical import save

def reindex(chat_id: str) -> dict:
    chunks=chunk_messages(messages(chat_id));p=ROOT/'data/index_state.json';p.parent.mkdir(parents=True,exist_ok=True)
    old=json.loads(p.read_text(encoding='utf8')) if p.exists() else {}
    hashes={c.id:hashlib.sha1(c.text.encode()).hexdigest() for c in chunks}
    previous=[c for c in all_chunks() if c.chat!=chat_id]
    old_chat={c.id:c for c in all_chunks() if c.chat==chat_id}
    changed=[c for c in chunks if old.get(c.id)!=hashes[c.id]]
    removed=set(old_chat)-set(hashes)
    if removed:collection().delete(ids=list(removed))
    if changed:upsert(changed)
    full=previous+chunks
    (ROOT/'data/index_chunks.jsonl').write_text(''.join(c.model_dump_json()+'\n' for c in full),encoding='utf8')
    save(full)
    old={k:v for k,v in old.items() if k not in old_chat};old.update(hashes)
    p.write_text(json.dumps(old,ensure_ascii=False,indent=2),encoding='utf8')
    return {'added':sum(c.id not in old_chat for c in changed),'updated':sum(c.id in old_chat for c in changed),'total':len(full)}
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--chat',required=True);print(reindex(a.parse_args().chat))
