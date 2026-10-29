"""Промпт агента: версия из конфига, сегодняшняя дата, версия в логе трассы."""
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src import agent as agent_mod
from src import mcp_server
from src.agent import run_agent
from src.config import load_config

pytestmark = pytest.mark.anyio

THURSDAY = datetime(2026, 10, 29, 12, 30, tzinfo=agent_mod.MSK)


@pytest.fixture
def now(monkeypatch):
    monkeypatch.setattr(agent_mod, "_now", lambda: THURSDAY)


def test_config_selects_existing_prompt():
    version = load_config()["agent"]["prompt_version"]
    assert version == "agent_v2" and (agent_mod.PROMPTS_DIR / f"{version}.txt").exists()
    assert (agent_mod.PROMPTS_DIR / "agent_v1.txt").exists()                    # прежняя версия сохранена для сравнения


def test_system_prompt_inserts_today(now):
    text = agent_mod._system_prompt("agent_v2")
    assert "Сегодня 2026-10-29, четверг, 12:30 (время московское)" in text and "{today}" not in text
    assert '{"error": ...}' in text                                          # прочие фигурные скобки не тронуты


def test_prompt_mentions_every_tool():
    text = agent_mod._system_prompt("agent_v2")
    tools = {name for name, fn in vars(mcp_server).items()
             if callable(fn) and getattr(fn, "__module__", "") == "src.mcp_server" and not name.startswith("_")}
    assert len(tools) == 9 and all(name in text for name in tools), sorted(t for t in tools if t not in text)


def test_prompt_rules_cover_known_failure_modes(now):
    text = agent_mod._system_prompt("agent_v2")
    for must in ("source_msg", "candidate и reason", "В материалах этого нет", "{\"error\"", "не больше 5 шагов",
                 "ГГГГ-ММ-ДД", "msg_ids"):
        assert must in text, must


def test_unknown_prompt_version(now):
    with pytest.raises(FileNotFoundError, match="agent_v99"):
        agent_mod._system_prompt("agent_v99")


def _chat_reply():
    reply = MagicMock()
    reply.message.tool_calls, reply.message.content = None, "Готово."
    return reply


async def _run(cfg, tmp_logs):
    seen = []

    def chat(model, messages, tools=None, options=None):
        seen.append(messages[0]["content"])
        return _chat_reply()
    with patch("src.agent.stdio_client") as stdio, patch("src.agent.ClientSession") as cls, \
            patch("src.agent.ollama.chat", side_effect=chat), patch("src.agent.load_config", return_value=cfg):
        stdio.return_value.__aenter__.return_value = (MagicMock(), MagicMock())
        session = AsyncMock()
        cls.return_value.__aenter__.return_value = session
        session.list_tools.return_value = MagicMock(tools=[])
        result = await run_agent("Что на этой неделе?", history=[])
    return result, seen


async def test_agent_sends_dated_prompt_and_logs_version(now, tmp_path):
    cfg = load_config()
    cfg["paths"] = {**cfg["paths"], "logs": str(tmp_path)}
    result, seen = await _run(cfg, tmp_path)
    assert result.text == "Готово." and "Сегодня 2026-10-29, четверг" in seen[0]
    entry = json.loads((tmp_path / "agent_trace.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert entry["prompt_version"] == "agent_v2" and entry["question"] == "Что на этой неделе?"
    assert entry["ts"].endswith("+03:00") and entry["model"] == cfg["models"]["llm"]


async def test_agent_follows_prompt_version_from_config(now, tmp_path):
    cfg = load_config()
    cfg["paths"] = {**cfg["paths"], "logs": str(tmp_path)}
    cfg["agent"] = {**cfg["agent"], "prompt_version": "agent_v1"}
    _, seen = await _run(cfg, tmp_path)
    assert "Сегодня" not in seen[0] and "ТОЛЬКО предоставленные инструменты" in seen[0]
    assert json.loads((tmp_path / "agent_trace.jsonl").read_text(encoding="utf-8"))["prompt_version"] == "agent_v1"


async def test_agent_default_version_without_config_key(now, tmp_path):
    cfg = load_config()
    cfg["paths"] = {**cfg["paths"], "logs": str(tmp_path)}
    cfg["agent"] = {k: v for k, v in cfg["agent"].items() if k != "prompt_version"}
    _, seen = await _run(cfg, tmp_path)
    assert "Сегодня 2026-10-29" in seen[0]
