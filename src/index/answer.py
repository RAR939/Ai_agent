import json, logging
from src.schemas import Answer
from .search import search
from .common import cfg,min_score,ROOT
logger=logging.getLogger(__name__)
def answer(question: str, **filters) -> Answer:
    hits=search(question,**filters);conf=cfg();minimum=min_score()
    if not hits or hits[0].score<minimum:return Answer(text='В материалах этого нет',sources=[],refused=True,prompt_version='answer_v1')
    template=(ROOT/'config/prompts/answer_v1.txt').read_text(encoding='utf8')
    context='\n\n'.join(f'Источник {i+1}: {h.ts_from} {h.roles} ({h.chunk_id})\n{h.text}' for i,h in enumerate(hits[:4]))
    from src import llm
    response=llm.chat(model=conf['models']['llm'],messages=[{'role':'user','content':template.format(context=context,question=question)}],options={'temperature':conf['models'].get('temperature',0.1)})
    text=response['message']['content'].strip()
    logger.info('answer prompt_version=answer_v1 model=%s',conf['models']['llm'])
    return Answer(text=text or 'В материалах этого нет',sources=hits,refused=not text or 'В материалах этого нет' in text,prompt_version='answer_v1')
