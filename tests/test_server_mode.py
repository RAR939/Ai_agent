"""Режим «всё тяжёлое на сервере»: локальный конфиг, кэши поиска, очередь операций, пароль на вход, GPU."""
import pathlib
import shutil
import sys
import threading
import time
import types

import pytest
import yaml
from streamlit.testing.v1 import AppTest

from src import _fixture_data as fx
from src import config
from src.index import chunking, common, lexical, search, vector_store
from src.schemas import Report
from src.tracker import pipeline

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = str(ROOT / "ui" / "app.py")


# ---------- config.local.yaml ----------
@pytest.fixture
def cfg_dir(tmp_path, monkeypatch):
    d = tmp_path / "config"
    shutil.copytree(config.CONFIG_DIR, d)
    monkeypatch.setattr(config, "CONFIG_DIR", d)
    return d


def test_local_config_overrides_by_section(cfg_dir):
    (cfg_dir / "config.local.yaml").write_text(yaml.safe_dump(
        {"models": {"host": "http://localhost:11434", "llm": "qwen3:14b"}, "ui": {"use_mock": False}}), encoding="utf-8")
    cfg = config.load_config()
    assert cfg["models"]["llm"] == "qwen3:14b" and cfg["models"]["host"] == "http://localhost:11434"
    assert cfg["models"]["embed"] == "bge-m3" and cfg["models"]["temperature"] == 0.1      # остальное из config.yaml
    assert cfg["ui"] == {"use_mock": False} and cfg["retrieval"]["top_k"] == 5


def test_local_config_cannot_remove_sections_and_must_be_mapping(cfg_dir):
    (cfg_dir / "config.local.yaml").write_text("- не словарь\n", encoding="utf-8")
    with pytest.raises(ValueError, match="config.local.yaml"):
        config.load_config()
    (cfg_dir / "config.local.yaml").write_text("", encoding="utf-8")                      # пустой файл допустим
    assert config.load_config()["models"]["llm"] == "qwen3:8b"


def test_local_config_is_ignored_by_git_and_seen_by_search(cfg_dir):
    assert "config/config.local.yaml" in (ROOT / ".gitignore").read_text(encoding="utf-8")
    (cfg_dir / "config.local.yaml").write_text(yaml.safe_dump({"retrieval": {"use_reranker": False}}), encoding="utf-8")
    assert common.cfg()["retrieval"]["use_reranker"] is False and common.min_score() == 0.0


# ---------- кэши поиска ----------
def chunks_of_elektro(monkeypatch, size=10, step=5):
    monkeypatch.setattr(chunking, "cfg", lambda: {"retrieval": {"chunk_strategy": "window", "window_size": size,
                                                                  "window_step": step, "max_chunk_chars": 1800}})
    return chunking.chunk_messages([m for m in fx.messages() if m.chat == "elektro"])


def test_bm25_model_is_built_once_per_corpus(monkeypatch):
    chunks = chunks_of_elektro(monkeypatch, size=2, step=2)       # много непересекающихся чанков: у BM25 есть что ранжировать
    built = []
    real = lexical.BM25Okapi
    monkeypatch.setattr(lexical, "BM25Okapi", lambda *a, **k: built.append(1) or real(*a, **k))
    first = lexical.rank("перенесли методичку", chunks, {c.id for c in chunks})
    again = lexical.rank("перенесли методичку", list(chunks), {c.id for c in chunks})
    assert first == again and first and len(built) == 1
    changed = [chunks[0].model_copy(update={"text": chunks[0].text + " новое"}), *chunks[1:]]
    lexical.rank("перенесли", changed, {c.id for c in chunks})
    assert len(built) == 2                                                    # изменился текст: пересборка


def test_all_chunks_parsed_once_until_file_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "ROOT", tmp_path)
    common._chunks_cached.cache_clear()
    path = tmp_path / "data" / "index_chunks.jsonl"
    path.parent.mkdir()
    chunks = chunks_of_elektro(monkeypatch)
    path.write_text("".join(c.model_dump_json() + "\n" for c in chunks), encoding="utf-8")
    first, second = common.all_chunks(), common.all_chunks()
    assert first == second == chunks and common._chunks_cached.cache_info().hits == 1
    path.write_text("".join(c.model_dump_json() + "\n" for c in chunks[:1]), encoding="utf-8")
    import os
    os.utime(path, ns=(0, path.stat().st_mtime_ns + 5_000_000))
    assert len(common.all_chunks()) == 1                                      # файл изменился: читается заново
    path.unlink()
    assert common.all_chunks() == []


def test_chroma_client_created_once(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "ROOT", tmp_path)
    monkeypatch.setattr(vector_store, "ROOT", tmp_path)
    vector_store._client.cache_clear()
    made = []

    class Client:
        def __init__(self, path):
            made.append(path)

        def get_or_create_collection(self, name, metadata=None):
            return name
    monkeypatch.setattr(vector_store.chromadb, "PersistentClient", lambda path: Client(path))
    assert vector_store.collection() == vector_store.collection() == "chat_chunks" and len(made) == 1
    vector_store._client.cache_clear()


def test_reranker_loaded_once_and_used_for_scores(monkeypatch):
    inits = []

    class FakeCrossEncoder:
        def __init__(self, name):
            inits.append(name)

        def predict(self, pairs):
            return [0.9 - 0.1 * i for i, _ in enumerate(pairs)]
    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(CrossEncoder=FakeCrossEncoder))
    search._reranker.cache_clear()
    chunks = chunks_of_elektro(monkeypatch)
    cfg = {"retrieval": {"candidates": 5, "rerank_top": 3, "use_reranker": True},
           "models": {"reranker": "BAAI/bge-reranker-v2-m3"}}
    monkeypatch.setattr(search, "cfg", lambda: cfg)
    monkeypatch.setattr(search, "all_chunks", lambda: chunks)
    monkeypatch.setattr(search, "vector_rank", lambda q, el, n: [(c.id, 0.9) for c in chunks][:n])
    for _ in range(3):
        hits = search.search("когда сдавать лабу")
    assert inits == ["BAAI/bge-reranker-v2-m3"] and len(hits) == 3
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)
    search._reranker.cache_clear()


# ---------- очередь долгих операций ----------
def test_process_new_runs_one_at_a_time_per_chat(monkeypatch):
    from ui.provider import RealProvider
    running, peak, calls = [0], [0], []

    def slow(chat):
        running[0] += 1
        peak[0] = max(peak[0], running[0])
        time.sleep(0.05)
        calls.append(chat)
        running[0] -= 1
        return Report(processed=1, added=0, moved=0, cancelled=0, pending=0, skipped_prefilter=1, failed=0)
    monkeypatch.setattr(pipeline, "process_new", slow)
    threads = [threading.Thread(target=RealProvider().process_new, args=("elektro",)) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(calls) == 4 and peak[0] == 1                                    # одновременно только одна обработка


def test_different_chats_do_not_block_each_other(monkeypatch):
    from ui.provider import RealProvider
    started = threading.Event()
    release = threading.Event()

    def process(chat):
        if chat == "elektro":
            started.set()
            release.wait(2)
        return Report(processed=1, added=0, moved=0, cancelled=0, pending=0, skipped_prefilter=1, failed=0)
    monkeypatch.setattr(pipeline, "process_new", process)
    slow = threading.Thread(target=RealProvider().process_new, args=("elektro",))
    slow.start()
    assert started.wait(2)
    done = []
    other = threading.Thread(target=lambda: done.append(RealProvider().process_new("models")))
    other.start()
    other.join(1)
    assert done                                                                # models прошёл, пока elektro занят
    release.set()
    slow.join()


# ---------- пароль на вход ----------
def test_no_password_means_no_gate(monkeypatch):
    monkeypatch.delenv("HELPER_UI_PASSWORD", raising=False)
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception and len(at.tabs) == 4 and not at.text_input


def test_password_gate(monkeypatch):
    monkeypatch.setenv("HELPER_UI_PASSWORD", "секрет")
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception and len(at.tabs) == 0 and at.text_input[0].label == "Пароль"
    at.text_input[0].input("не то")
    at.button[0].click().run()
    assert at.error[0].value == "Неверный пароль" and len(at.tabs) == 0
    at.text_input[0].input("секрет")
    at.button[0].click().run()
    assert not at.exception and len(at.tabs) == 4 and at.session_state["authed"] is True


def test_password_compare_is_exact():
    from ui.auth import password_ok
    assert password_ok("секрет", "секрет") and not password_ok("секрет ", "секрет") and not password_ok("", "секрет")


# ---------- GPU и файлы развёртывания ----------
def test_gpu_check(monkeypatch):
    from scripts import check_env as ce
    cfg = {"retrieval": {"use_reranker": True}}
    cuda = types.SimpleNamespace(is_available=lambda: True, get_device_name=lambda i: "NVIDIA A10")
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(cuda=cuda))
    assert ce.check_gpu(cfg).ok and "A10" in ce.check_gpu(cfg).detail
    cpu = types.SimpleNamespace(is_available=lambda: False, get_device_name=lambda i: "")
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(cuda=cpu))
    c = ce.check_gpu(cfg)
    assert not c.ok and not c.critical and "CPU" in c.detail
    assert ce.check_gpu({"retrieval": {"use_reranker": False}}) is None


def test_streamlit_config_listens_only_locally():
    text = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    assert 'address = "127.0.0.1"' in text and "headless = true" in text and "gatherUsageStats = false" in text


def test_service_template_runs_the_app():
    text = (ROOT / "deploy" / "helper-ui.service").read_text(encoding="utf-8")
    assert "streamlit run ui/app.py" in text and "EnvironmentFile" in text and "WantedBy=multi-user.target" in text
