from collections import Counter, defaultdict
from datetime import datetime
from src.schemas import Chunk
from .common import cfg, ROOT
import yaml, re

def discipline(text):
    p=ROOT/'config/disciplines.yaml'
    if not p.exists(): return None
    data=yaml.safe_load(p.read_text(encoding='utf8')) or {}
    scores={}
    for key, item in data.items():
        aliases=[key]+(item.get('aliases',[]) if isinstance(item,dict) else [])
        scores[key]=sum(len(re.findall(r'(?<!\w)'+re.escape(str(a))+r'(?!\w)',text,re.I)) for a in aliases)
    return max(scores,key=scores.get) if scores and max(scores.values())>0 else None

def chunk_messages(messages, strategy=None):
    c=cfg()['retrieval']; strategy=strategy or c['chunk_strategy']; limit=c['max_chunk_chars']
    msgs=sorted(messages,key=lambda m:(m.ts,m.id)); groups=[]
    if strategy=='thread':
        byid={m.id:m for m in msgs}; roots=defaultdict(list)
        for m in msgs:
            root=m; seen=set()
            while root.reply_to in byid and root.reply_to not in seen:
                seen.add(root.id);root=byid[root.reply_to]
            roots[root.id].append(m)
        groups=list(roots.values())
    elif strategy in ('window','day'):
        days=defaultdict(list)
        # окно идёт через полночь: вопрос после 00:00 остаётся рядом с объявлением; по дням режет только strategy='day'
        for m in msgs:days[(m.chat,m.ts[:10] if strategy=='day' else '')].append(m)
        for day in days.values():
            if strategy=='day':groups.append(day)
            else:
                size=c['window_size'];step=c['window_step']
                groups.extend(day[i:i+size] for i in range(0,len(day),step) if day[i:i+size])
    else:raise ValueError('Неизвестная стратегия чанкинга')
    result=[];used=set()
    for group in groups:
        group=sorted(group,key=lambda m:(m.ts,m.id));batch=[]
        def emit(batch):
            if not batch:return
            txt='\n'.join(f'[{m.ts[:16].replace("T"," ")}] {m.role.upper()}: {m.text}' for m in batch)
            # При пересечении окон один и тот же id возможен: сохраняем стабильный идентификатор.
            cid=f'{batch[0].chat}:{batch[0].id.split(":")[-1]}-{batch[-1].id.split(":")[-1]}'
            if cid in used:return
            used.add(cid)
            result.append(Chunk(id=cid,chat=batch[0].chat,msg_ids=[m.id for m in batch],ts_from=batch[0].ts,ts_to=batch[-1].ts,roles=list(dict.fromkeys(m.role for m in batch)),discipline=discipline(txt),text=txt))
        for m in group:
            line=f'[{m.ts[:16]}] {m.role.upper()}: {m.text}'
            if batch and sum(len(x.text)+40 for x in batch)+len(line)>limit:
                emit(batch);batch=[]
            # Длинное сообщение сохраняется целиком: не разрываем предложение/источник.
            batch.append(m)
        emit(batch)
    return result
