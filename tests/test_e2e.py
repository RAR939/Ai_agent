"""Сквозная проверка: настоящий агент <-> настоящий MCP-сервер (процесс по stdio) <-> настоящая база трекера.

Подставлена только модель: ollama.chat отвечает по сценарию (вызов инструмента, затем текст).
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from src import _fixture_data as fx
from src.agent import run_agent
from src.tracker import db

from tests.conftest import make_deadline

pytestmark = pytest.mark.anyio


class ScriptedModel:
    """Сначала просит вызвать инструменты по списку, потом отвечает текстом из последнего результата."""

    def __init__(self, calls: list[tuple[str, dict]], final):
        self.calls, self.final, self.tool_results = calls, final, []

    def __call__(self, model, messages, tools=None, options=None):
        self.tool_results = [m["content"] for m in messages if isinstance(m, dict) and m.get("role") == "tool"]
        step = len(self.tool_results)
        resp = MagicMock()
        if step < len(self.calls):
            name, args = self.calls[step]
            call = MagicMock()
            call.function.name, call.function.arguments = name, args
            resp.message.tool_calls, resp.message.content = [call], ""
        else:
            resp.message.tool_calls, resp.message.content = None, self.final(self.tool_results)
        return resp


@pytest.fixture
def real_db(tmp_path, monkeypatch):
    """Файл базы, общий для теста и процесса сервера (путь передаётся через HELPER_DB)."""
    monkeypatch.setenv("HELPER_DB", str(tmp_path / "helper.db"))
    db.set_db_path(None)
    db.init_db()
    files = [f.model_copy(update={"bind": "same_message"}) for f in fx.message_by_id()["elektro:1010"].attachments]
    lab2 = db.add_deadline(make_deadline(task="Лаб.2", due_at="2099-01-10T23:59:00+03:00", source_msg="elektro:1010",
                                         attachments=files))
    yield lab2
    db.set_db_path(None)


async def test_agent_answers_from_real_tracker(real_db):
    model = ScriptedModel([("list_deadlines", {"days_ahead": 100000, "discipline": "elektro"}),
                           ("get_attachments", {"deadline_id": real_db})],
                          lambda results: "Лаб.2 до 10.01.2099, файл " + json.loads(results[1])[0]["name"])
    with patch("src.agent.llm.chat", side_effect=model):
        result = await run_agent("Когда сдавать Лаб.2 и какие материалы?", history=[])
    assert result.text == "Лаб.2 до 10.01.2099, файл lab2_elektro.pdf"
    assert [t.tool for t in result.trace] == ["list_deadlines", "get_attachments"] and not any(t.error for t in result.trace)
    listed = json.loads(model.tool_results[0])
    assert [d["task"] for d in listed] == ["Лаб.2"] and listed[0]["attachments"][0]["bind"] == "same_message"


async def test_agent_unclear_move_goes_to_confirmation_queue(real_db):
    model = ScriptedModel([("update_deadline", {"id": real_db, "new_due_text": "потом скажу",
                                                "source_msg": "elektro:1040"})],
                          lambda results: "Перенос ждёт подтверждения.")
    with patch("src.agent.llm.chat", side_effect=model):
        result = await run_agent("Перенеси Лаб.2 когда-нибудь", history=[])
    (pending,) = db.list_pending()
    assert result.pending_ids == [pending.id] and pending.reason == "low_confidence"
    assert db.get_deadline(real_db).due_at == "2099-01-10T23:59:00+03:00"          # срок не тронут


async def test_agent_applies_move_with_history(real_db):
    model = ScriptedModel([("update_deadline", {"id": real_db, "new_due_text": "на 30.10",
                                                "source_msg": "elektro:1040"})], lambda results: "Перенесла.")
    with patch("src.agent.llm.chat", side_effect=model):
        result = await run_agent("Лаб.2 перенесли на 30.10", history=[])
    assert result.pending_ids == [] and db.get_deadline(real_db).due_at == "2026-10-30T23:59:00+03:00"
    (event,) = db.get_history(real_db)
    assert event.source_msg == "elektro:1040"


async def test_agent_survives_tool_error_json(real_db):
    model = ScriptedModel([("get_attachments", {"deadline_id": 9999})],
                          lambda results: "Такого задания нет: " + json.loads(results[0])["error"])
    with patch("src.agent.llm.chat", side_effect=model):
        result = await run_agent("Файлы к несуществующему заданию", history=[])
    assert result.text.startswith("Такого задания нет: Ошибка получения файлов: Дедлайн не найден")


async def test_rules_mode_calls_real_schedule_tool(real_db):
    """Запасной режим: инструмент выбирается словами вопроса, get_schedule получает обязательный date_from."""
    from src.config import load_config
    cfg = load_config()
    cfg["agent"] = {**cfg["agent"], "mode": "rules"}
    sent = []

    def chat(model, messages, tools=None, options=None):
        sent.append(messages[-2]["content"])                   # результат инструмента, переданный модели
        resp = MagicMock()
        resp.message.content = "Пар нет."
        return resp
    with patch("src.agent.load_config", return_value=cfg), patch("src.agent.llm.chat", side_effect=chat):
        result = await run_agent("Какие пары завтра?", history=[])
    (call,) = result.trace
    assert call.tool == "get_schedule" and call.error is None and set(call.args) == {"date_from", "date_to"}
    assert sent == ["[]"] and result.text == "Пар нет."
