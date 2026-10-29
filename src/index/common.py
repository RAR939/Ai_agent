from functools import lru_cache
from pathlib import Path
import json
ROOT = Path(__file__).resolve().parents[2]
def cfg():
    from src.config import load_config    # config.yaml + config.local.yaml
    return load_config()
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
@lru_cache(maxsize=2)
def _chunks_cached(path, mtime_ns):
    from src.schemas import Chunk
    return tuple(Chunk.model_validate_json(line) for line in Path(path).read_text(encoding='utf8').splitlines())
def all_chunks():
    # файл читается и разбирается один раз, пока не изменится (поиск зовут на каждый вопрос)
    path=ROOT/'data/index_chunks.jsonl'
    return list(_chunks_cached(str(path),path.stat().st_mtime_ns)) if path.exists() else []
