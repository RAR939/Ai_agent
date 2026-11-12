from types import SimpleNamespace

from eval.search_config_experiment import evaluate_hits, summarize


def test_run_connects_search_to_temporary_chunks(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace as NS
    from eval import search_config_experiment as experiment
    import src.index as index
    chunk = NS(msg_ids=["group:1"], discipline="algo")
    modules = {name: NS(cfg=lambda: {}) for name in
               ("chunking", "common", "lexical", "search", "vector_store")}
    modules["chunking"].chunk_messages = lambda messages: [chunk]
    modules["common"].all_chunks = lambda: []
    search = modules["search"]
    original_provider = lambda: []
    search.all_chunks = original_provider
    search.search = lambda *args, **kw: [NS(score=1.0, msg_ids=c.msg_ids)
                                        for c in search.all_chunks()]
    store = modules["vector_store"]
    store.ROOT = tmp_path
    store._client = NS(cache_clear=lambda: None)
    store.upsert = lambda chunks: None
    modules["subject_classifier"] = NS(classify=lambda *args: {})
    for name, module in modules.items():
        monkeypatch.setattr(index, name, module, raising=False)
    monkeypatch.setattr(experiment, "load_config", lambda: {
        "models": {}, "retrieval": {"top_k": 5, "min_score": 0.3}})
    monkeypatch.setattr(experiment, "load_messages", lambda chat: [NS(id="group:1")])
    gold = tmp_path / "gold.jsonl"
    gold.write_text(json.dumps({"query": "test", "chat": "group",
                                "relevant_msg_ids": ["group:1"]}), encoding="utf-8")
    result = experiment.run(gold, tmp_path / "results.json", ["window_10_rerank"])
    assert result["variants"]["window_10_rerank"]["metrics"]["hit_at_k"] == 1
    assert search.all_chunks is original_provider


def test_checkpoint_exports_partial_results(tmp_path):
    import json
    import zipfile
    from eval.search_config_experiment import checkpoint
    output = tmp_path / "results.json"
    (tmp_path / "search_gold.jsonl").write_text('{}\n', encoding="utf-8")
    partial = {"status": "running", "variants": {"window": {"queries": [1]}}}
    checkpoint(output, partial)
    assert json.loads(output.read_text(encoding="utf-8")) == partial
    with zipfile.ZipFile(output.with_suffix(".zip")) as archive:
        assert json.loads(archive.read("results.json")) == partial
        assert "search_gold.jsonl" in archive.namelist()


def test_relevance_threshold_changes_hit_and_no_answer_decision():
    hits = [SimpleNamespace(score=0.2, msg_ids=["chat:1"]),
            SimpleNamespace(score=0.9, msg_ids=["chat:2"])]
    assert evaluate_hits(hits, {"chat:2"}, None)["reciprocal_rank"] == 0.5
    assert evaluate_hits(hits, {"chat:2"}, 0.3)["reciprocal_rank"] == 1.0
    assert not evaluate_hits(hits[:1], set(), 0.3)["accepted"]


def test_summary_separates_answerable_and_unanswerable_queries():
    rows = [dict(relevant_msg_ids=["chat:2"], hit=True, reciprocal_rank=0.5,
                 accepted=True, seconds=1.0),
            dict(relevant_msg_ids=[], hit=False, reciprocal_rank=0.0,
                 accepted=False, seconds=3.0)]
    metrics = summarize(rows)
    assert metrics["hit_at_k"] == 1.0
    assert metrics["mrr"] == 0.5
    assert metrics["false_accept_rate"] == 0.0
    assert metrics["mean_search_seconds"] == 2.0
