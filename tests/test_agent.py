# path/to/tests/test_agent.py
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from src.agent import run_agent


@pytest.mark.anyio
@patch("src.agent.ollama.chat")
@patch("src.agent.ClientSession")
@patch("src.agent.stdio_client")
async def test_agent_tool_call_and_answer(mock_stdio_client, mock_session_class, mock_chat):
    # 1. Настраиваем мок stdio_client (контекстный менеджер)
    mock_read = MagicMock()
    mock_write = MagicMock()
    mock_stdio_client.return_value.__aenter__.return_value = (mock_read, mock_write)

    # 2. Настраиваем мок ClientSession
    mock_session = AsyncMock()
    mock_session_class.return_value.__aenter__.return_value = mock_session

    # Мокаем list_tools
    mock_tool = MagicMock()
    mock_tool.name = "list_deadlines"
    mock_tool.description = "Test description"
    mock_tool.inputSchema = {"type": "object", "properties": {}}
    mock_session.list_tools.return_value = MagicMock(tools=[mock_tool])

    # Мокаем call_tool
    mock_tool_result = MagicMock()
    mock_tool_result.content = [MagicMock(text='[{"id": 1, "task": "Lab"}]')]
    mock_session.call_tool.return_value = mock_tool_result

    # 3. Настраиваем мок ollama.chat
    # Первый вызов: модель просит вызвать инструмент
    mock_tc = MagicMock()
    mock_tc.function.name = "list_deadlines"
    mock_tc.function.arguments = {"days_ahead": 7}

    mock_resp_1 = MagicMock()
    mock_resp_1.message = MagicMock()
    mock_resp_1.message.tool_calls = [mock_tc]

    # Второй вызов: модель дает финальный текстовый ответ
    mock_resp_2 = MagicMock()
    mock_resp_2.message = MagicMock()
    mock_resp_2.message.tool_calls = None
    mock_resp_2.message.content = "У вас 1 дедлайн: Лабораторная."

    mock_chat.side_effect = [mock_resp_1, mock_resp_2]

    # 4. Запускаем агента
    result = await run_agent("Что сдать на этой неделе?", history=[])

    # 5. Проверяем результаты
    assert result.text == "У вас 1 дедлайн: Лабораторная."
    assert len(result.trace) == 1
    assert result.trace[0].tool == "list_deadlines"
    assert result.trace[0].args == {"days_ahead": 7}
    assert result.trace[0].error is None

    # Проверяем, что инструмент реально вызывался
    mock_session.call_tool.assert_called_once_with("list_deadlines", {"days_ahead": 7})

    # Проверяем, что модель вызывалась дважды (сначала tool_call, потом ответ)
    assert mock_chat.call_count == 2


@pytest.mark.anyio
@patch("src.agent.ollama.chat")
@patch("src.agent.ClientSession")
@patch("src.agent.stdio_client")
async def test_agent_loop_protection(mock_stdio_client, mock_session_class, mock_chat):
    # Тест защиты от зацикливания
    mock_stdio_client.return_value.__aenter__.return_value = (MagicMock(), MagicMock())
    mock_session = AsyncMock()
    mock_session_class.return_value.__aenter__.return_value = mock_session

    mock_tool = MagicMock()
    mock_tool.name = "search_messages"
    mock_tool.description = "Test"
    mock_tool.inputSchema = {}
    mock_session.list_tools.return_value = MagicMock(tools=[mock_tool])

    # ДОБАВЛЯЕМ МОК ДЛЯ ВЫЗОВА ИНСТРУМЕНТА
    mock_tool_result = MagicMock()
    mock_tool_result.content = [MagicMock(text='{"result": "ok"}')]
    mock_session.call_tool.return_value = mock_tool_result

    # Мокаем ollama.chat так, чтобы он всегда возвращал один и тот же tool_call
    mock_tc = MagicMock()
    mock_tc.function.name = "search_messages"
    mock_tc.function.arguments = {"query": "тест"}

    mock_resp = MagicMock()
    mock_resp.message = MagicMock()
    mock_resp.message.tool_calls = [mock_tc]

    mock_chat.return_value = mock_resp

    # Запускаем
    result = await run_agent("Найди что-нибудь", history=[])

    # Агент должен прерваться из-за зацикливания
    assert "зациклился" in result.text
    # Должен быть только 1 вызов инструмента в трассе, так как на втором сработала защита
    assert len(result.trace) == 1
# path/to/tests/test_agent.py
# (добавь эту функцию в конец файла, остальные оставь как есть)

from src.agent import _route_by_rules

def test_rule_routing():
    rules = {
        "list_deadlines": ["сда", "срок"], # используем основу "сда"
        "get_schedule": ["пар", "расписани"] # используем основы
    }
    assert _route_by_rules("Когда сдавать лабу?", rules) == "list_deadlines"
    assert _route_by_rules("Какие пары завтра?", rules) == "get_schedule"
    assert _route_by_rules("Что говорили про перенос?", rules) == "search_messages"

# ---------- интеграция с настоящими инструментами ----------
import os  # noqa: E402

from src import agent as agent_mod  # noqa: E402


def test_pending_id_detects_pending_item():
    pending = {"id": 12, "candidate": {"task": "Лаб.3"}, "matched_id": None, "reason": "low_confidence",
               "source_text": "т", "created_at": "2026-10-29T12:00:00+03:00"}
    assert agent_mod._pending_id(pending) == 12
    assert agent_mod._pending_id({"id": 5, "task": "Лаб.2"}) is None       # обычный Deadline
    assert agent_mod._pending_id([pending]) is None and agent_mod._pending_id({"error": "x"}) is None


def test_rules_args_for_every_tool():
    assert agent_mod._rules_args("search_messages", "что говорили?") == {"query": "что говорили?"}
    sched = agent_mod._rules_args("get_schedule", "какие пары?")
    assert set(sched) == {"date_from", "date_to"} and sched["date_from"] <= sched["date_to"]   # date_from обязателен
    assert agent_mod._rules_args("list_deadlines", "когда сдавать?") == {}


def _mock_session(monkeypatch_target, tool_text):
    mock_stdio_client, mock_session_class, mock_chat = monkeypatch_target
    mock_stdio_client.return_value.__aenter__.return_value = (MagicMock(), MagicMock())
    session = AsyncMock()
    mock_session_class.return_value.__aenter__.return_value = session
    tool = MagicMock()
    tool.name, tool.description, tool.inputSchema = "add_deadline", "d", {"type": "object", "properties": {}}
    session.list_tools.return_value = MagicMock(tools=[tool])
    session.call_tool.return_value = MagicMock(content=[MagicMock(text=tool_text)])
    call = MagicMock()
    call.function.name, call.function.arguments = "add_deadline", {"task": "Лаб.3"}
    first = MagicMock(message=MagicMock(tool_calls=[call]))
    last = MagicMock(message=MagicMock(tool_calls=None, content="Запись ждёт подтверждения."))
    mock_chat.side_effect = [first, last]
    return session


@pytest.mark.anyio
@patch("src.agent.ollama.chat")
@patch("src.agent.ClientSession")
@patch("src.agent.stdio_client")
async def test_agent_collects_pending_ids_and_works_from_any_folder(mock_stdio, mock_cls, mock_chat,
                                                                     tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)                                    # раньше пути были относительно корня репозитория
    pending = json.dumps({"id": 12, "candidate": {"task": "Лаб.3"}, "matched_id": None,
                          "reason": "low_confidence", "source_text": "т",
                          "created_at": "2026-10-29T12:00:00+03:00"})
    _mock_session((mock_stdio, mock_cls, mock_chat), pending)
    result = await run_agent("Добавь Лаб.3", history=[])
    assert result.pending_ids == [12] and result.text == "Запись ждёт подтверждения."
    params = mock_stdio.call_args.args[0]
    assert params.args == ["-m", "src.mcp_server"] and os.path.isdir(params.cwd)
    assert os.path.exists(os.path.join(params.cwd, "logs", "agent_trace.jsonl"))   # лог рядом с проектом, не в cwd
    assert not (tmp_path / "logs").exists()
