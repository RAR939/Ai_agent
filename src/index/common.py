from pathlib import Path
import json, yaml
ROOT = Path(__file__).resolve().parents[2]
def cfg():
    p=ROOT/'config/config.yaml'
    return yaml.safe_load(p.read_text(encoding='utf8')) if p.exists() else {'retrieval': {'chunk_strategy':'window','window_size':10,'window_step':5,'max_chunk_chars':1800,'candidates':20,'rerank_top':15,'top_k':5,'min_score':0.3,'use_reranker':True,'bm25':{'k1':1.5,'b':0.75}},'models':{'embed':'bge-m3','llm':'qwen3:8b','reranker':'BAAI/bge-reranker-v2-m3','temperature':0.1}}
def min_score():
    # оценка RRF (около 0.03 максимум) несравнима с порогом 0..1: без реранкера порог не применяется
    c=cfg()['retrieval']
    return c.get('min_score',0.3) if c.get('use_reranker',True) else 0.0
def messages(chat):
    try:
        from src.ingest.store import load_messages
        return load_messages(chat)
    except ImportError:
        path=ROOT/f'data/clean/{chat}.jsonl'
        if not path.exists(): path=ROOT/'tests/fixtures/mini_chat.jsonl'
        from src.schemas import Message
        return [Message.model_validate_json(line) for line in path.read_text(encoding='utf8').splitlines() if line.strip() and json.loads(line).get('chat')==chat]
def all_chunks():
    path=ROOT/'data/index_chunks.jsonl'
    from src.schemas import Chunk
    return [Chunk.model_validate_json(line) for line in path.read_text(encoding='utf8').splitlines()] if path.exists() else []
