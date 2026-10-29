"""scripts/check_env.py: отчёт о готовности окружения."""
import importlib.metadata as md
import json

import pytest

from scripts import check_env as ce


def test_requirements_parsed():
    reqs = dict(ce.requirements())
    assert reqs["pydantic"] == "2.14.1" and reqs["mcp"] == "2.3.0"            # mcp[cli]==2.3.0 без «[cli]»
    assert all(v[0].isdigit() for v in reqs.values()) and len(reqs) >= 20


def test_python_check():
    assert ce.check_python().ok


def test_packages_missing_and_mismatch(monkeypatch):
    real = md.version

    def fake(name):
        if name == "pydantic":
            raise md.PackageNotFoundError(name)
        if name == "pytest":
            return "0.0.1"
        return real(name)
    monkeypatch.setattr(md, "version", fake)
    ok, *rest = ce.check_packages()
    assert not ok.ok and "pydantic" in ok.detail
    assert rest and not rest[0].critical and "pytest 0.0.1" in rest[0].detail


def test_ollama_down_and_models(monkeypatch):
    cfg = {"models": {"llm": "qwen3:8b", "embed": "bge-m3"}}

    def down():
        raise ConnectionError("нет связи")
    monkeypatch.setattr(ce, "installed_models", down)
    (c,) = ce.check_ollama(cfg)
    assert not c.ok and "ConnectionError" in c.detail

    monkeypatch.setattr(ce, "installed_models", lambda: ["qwen3:8b", "bge-m3:latest"])
    assert all(c.ok for c in ce.check_ollama(cfg))

    monkeypatch.setattr(ce, "installed_models", lambda: ["qwen3:4b"])
    llm, embed = ce.check_ollama(cfg)[1:]
    assert not llm.ok and llm.hint == "ollama pull qwen3:8b" and not embed.ok


def test_reranker_check(monkeypatch, tmp_path):
    cfg = {"models": {"reranker": "BAAI/bge-reranker-v2-m3"}, "retrieval": {"use_reranker": True}}
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    c = ce.check_reranker(cfg)
    assert not c.ok and not c.critical
    (tmp_path / "hub" / "models--BAAI--bge-reranker-v2-m3").mkdir(parents=True)
    assert ce.check_reranker(cfg).ok
    assert ce.check_reranker({**cfg, "retrieval": {"use_reranker": False}}) is None


def test_data_and_index_checks(monkeypatch, tmp_path):
    monkeypatch.setattr(ce, "ROOT", tmp_path)
    cfg = {"paths": {"data": "data"}}
    chats, index = ce.check_data(cfg)
    assert not chats.ok and not index.ok and not chats.critical
    (tmp_path / "data" / "clean").mkdir(parents=True)
    (tmp_path / "data" / "clean" / "elektro.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "data" / "index_chunks.jsonl").write_text("{}\n{}\n", encoding="utf-8")
    chats, index = ce.check_data(cfg)
    assert chats.ok and chats.detail == "elektro" and index.ok and index.detail == "чанков: 2"


def test_database_check(tdb):
    db_check, schedule = ce.check_database()
    assert db_check.ok and "дедлайнов: 0" in db_check.detail and not schedule.ok and not schedule.critical


def test_config_check_reports_errors(monkeypatch):
    import src.config

    def broken():
        raise ValueError("config.yaml: нет разделов tracker")
    monkeypatch.setattr(src.config, "load_config", broken)
    check, cfg = ce.check_config()
    assert not check.ok and cfg is None and "tracker" in check.detail
    monkeypatch.setattr(ce, "check_python", lambda: ce.Check("Python", True, "3.11"))
    monkeypatch.setattr(ce, "check_packages", lambda: [])
    assert [c.name for c in ce.run_checks()] == ["Python", "Конфиг"]          # дальше без конфига не идём


@pytest.mark.parametrize("critical,code", [(True, 1), (False, 0)])
def test_main_exit_code(monkeypatch, capsys, critical, code):
    monkeypatch.setattr(ce, "run_checks", lambda: [ce.Check("Python", True, "3.13"),
                                                    ce.Check("Тест", False, "плохо", "почините", critical=critical)])
    assert ce.main() == code
    out = capsys.readouterr().out
    assert "→ почините" in out and ("Не хватает обязательного: Тест" in out if critical else "Предупреждений: 1" in out)


def test_ollama_check_shows_server_and_latency(monkeypatch):
    import src.llm as llm_mod
    cfg = {"models": {"llm": "qwen3:8b", "embed": "bge-m3"}}
    monkeypatch.setattr(llm_mod, "describe", lambda: "http://gpu:11434, токен задан")
    monkeypatch.setattr(ce, "installed_models", lambda: ["qwen3:8b", "bge-m3:latest"])
    first, *rest = ce.check_ollama(cfg)
    assert first.ok and "http://gpu:11434, токен задан" in first.detail and "ответ за" in first.detail
    assert all(c.ok for c in rest)

    def slow():
        import time
        time.sleep(0.05)
        return ["qwen3:8b", "bge-m3:latest"]
    ticks = iter([0.0, 3.0])
    monkeypatch.setattr(ce.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(ce, "installed_models", slow)
    checks = ce.check_ollama(cfg)
    assert any(c.name == "Связь с Ollama" and not c.ok and not c.critical for c in checks)


def test_ollama_down_mentions_server_setup(monkeypatch):
    def down():
        raise ConnectionError("нет связи")
    monkeypatch.setattr(ce, "installed_models", down)
    (c,) = ce.check_ollama({"models": {"llm": "x", "embed": "y"}})
    assert not c.ok and "docs/server_setup.md" in c.hint and "ConnectionError" in c.detail
