"""Compare retrieval configurations on the same annotated questions.

Gold JSONL: {"query": "...", "relevant_msg_ids": ["chat:123"], "chat": "chat"}.
An empty relevant_msg_ids list means that the answer is absent from the corpus.
Requires the configured Ollama embedding model; reranked variants also require
the configured CrossEncoder. Indexes are isolated in a temporary directory.
"""
from __future__ import annotations

import argparse
import copy
import json
import tempfile
import time
from pathlib import Path

from src.config import load_config
from src.ingest.store import load_messages


VARIANTS = {
    "window_10_rerank": {"chunk_strategy": "window", "window_size": 10, "window_step": 5,
                         "candidates": 20, "rerank_top": 15, "use_reranker": True},
    "window_5_rerank": {"chunk_strategy": "window", "window_size": 5, "window_step": 2,
                        "candidates": 20, "rerank_top": 15, "use_reranker": True},
    "thread_rerank": {"chunk_strategy": "thread", "candidates": 20,
                      "rerank_top": 15, "use_reranker": True},
    "window_10_no_rerank": {"chunk_strategy": "window", "window_size": 10,
                            "window_step": 5, "candidates": 20,
                            "rerank_top": 15, "use_reranker": False},
}


def evaluate_hits(hits, relevant: set[str], threshold: float | None) -> dict:
    """Score message-level evidence, including queries with no answer."""
    accepted = [h for h in hits if threshold is None or h.score >= threshold]
    first = next((rank for rank, hit in enumerate(accepted, 1)
                  if relevant.intersection(hit.msg_ids)), None)
    return {"hit": first is not None, "reciprocal_rank": 1 / first if first else 0.0,
            "accepted": bool(accepted), "returned": len(accepted),
            "top_score": hits[0].score if hits else None,
            "top_msg_ids": hits[0].msg_ids if hits else []}


def summarize(rows: list[dict]) -> dict:
    positive = [r for r in rows if r["relevant_msg_ids"]]
    negative = [r for r in rows if not r["relevant_msg_ids"]]
    fraction = lambda n, d: n / d if d else None
    return {
        "questions": len(rows), "answerable": len(positive), "unanswerable": len(negative),
        "hit_at_k": fraction(sum(r["hit"] for r in positive), len(positive)),
        "mrr": fraction(sum(r["reciprocal_rank"] for r in positive), len(positive)),
        "false_accept_rate": fraction(sum(r["accepted"] for r in negative), len(negative)),
        "mean_search_seconds": fraction(sum(r["seconds"] for r in rows), len(rows)),
    }


def load_gold(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    if not rows:
        raise ValueError("Gold file is empty")
    seen = set()
    for i, row in enumerate(rows, 1):
        if not isinstance(row.get("query"), str) or not row["query"].strip():
            raise ValueError(f"Line {i}: query must be nonempty")
        if not isinstance(row.get("relevant_msg_ids"), list) or not all(
                isinstance(x, str) and ":" in x for x in row["relevant_msg_ids"]):
            raise ValueError(f"Line {i}: relevant_msg_ids must be a list of message IDs")
        if row["query"] in seen:
            raise ValueError(f"Line {i}: duplicate query")
        seen.add(row["query"])
    return rows


def run(gold_path: Path, output: Path, selected: list[str]) -> dict:
    from src.index import chunking, common, lexical, search, vector_store

    gold = load_gold(gold_path)
    chats = sorted({r.get("chat") or mid.split(":", 1)[0]
                    for r in gold for mid in (r["relevant_msg_ids"] or [""])} - {""})
    if any(not r.get("chat") and not r["relevant_msg_ids"] for r in gold):
        raise ValueError("Questions without an answer require an explicit chat")
    messages = [m for chat in chats for m in load_messages(chat)]
    if not messages:
        raise ValueError("No clean chat messages found; place them in data/clean/<chat>.jsonl")
    all_ids = {m.id for m in messages}
    unknown = {mid for row in gold for mid in row["relevant_msg_ids"] if mid not in all_ids}
    if unknown:
        raise ValueError(f"Gold references missing messages: {sorted(unknown)[:5]}")

    base = load_config()
    result = {"gold": str(gold_path), "chats": chats,
              "models": base["models"], "base_retrieval": base["retrieval"], "variants": {}}
    original = (chunking.cfg, common.cfg, lexical.cfg, search.cfg, vector_store.cfg,
                common.all_chunks, vector_store.ROOT)
    try:
        for name in selected:
            config = copy.deepcopy(base)
            config["retrieval"].update(VARIANTS[name])
            chunking.cfg = common.cfg = lexical.cfg = search.cfg = vector_store.cfg = lambda: config
            chunks = chunking.chunk_messages(messages)
            with tempfile.TemporaryDirectory(prefix="chat_retrieval_") as temp:
                vector_store.ROOT = Path(temp)
                vector_store._client.cache_clear()
                vector_store.upsert(chunks)
                common.all_chunks = lambda: chunks
                rows = []
                for question in gold:
                    start = time.perf_counter()
                    hits = search.search(question["query"], chat=question.get("chat"),
                                         top_k=int(config["retrieval"]["top_k"]))
                    seconds = time.perf_counter() - start
                    threshold = (float(config["retrieval"]["min_score"])
                                 if config["retrieval"].get("use_reranker") and
                                 config["retrieval"].get("filter_tool_results_by_score") else None)
                    score = evaluate_hits(hits, set(question["relevant_msg_ids"]), threshold)
                    rows.append({"query": question["query"], "chat": question.get("chat"),
                                 "relevant_msg_ids": question["relevant_msg_ids"],
                                 "seconds": seconds, **score})
                result["variants"][name] = {"config": config["retrieval"],
                                            "metrics": summarize(rows), "queries": rows,
                                            "chunks": len(chunks)}
                vector_store._client.cache_clear()
    finally:
        (chunking.cfg, common.cfg, lexical.cfg, search.cfg, vector_store.cfg,
         common.all_chunks, vector_store.ROOT) = original
        vector_store._client.cache_clear()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("data/eval/search_config_results.json"))
    parser.add_argument("--variants", nargs="+", choices=sorted(VARIANTS), default=list(VARIANTS))
    args = parser.parse_args()
    result = run(args.gold, args.out, args.variants)
    for name, variant in result["variants"].items():
        print(name, json.dumps(variant["metrics"], ensure_ascii=False))
    print(f"Detailed results: {args.out}")


if __name__ == "__main__":
    main()
