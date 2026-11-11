from types import SimpleNamespace

from eval.search_config_experiment import evaluate_hits, summarize


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
