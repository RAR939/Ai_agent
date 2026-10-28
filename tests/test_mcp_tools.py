# path/to/tests/test_mcp_tools.py
import json
import pytest
from src.mcp_server import (
    search_messages, list_deadlines, add_deadline,
    get_attachments, process_new_messages
)

def test_search_messages_success():
    res_str = search_messages(query="лаб2")
    res = json.loads(res_str)
    assert isinstance(res, list)
    assert res[0]["chunk_id"] == "elektro:1040-1051"

def test_search_messages_error():
    # Передаем пустой запрос, чтобы спровоцировать ValueError в моке
    res_str = search_messages(query="")
    res = json.loads(res_str)
    assert "error" in res
    assert "Пустой поисковый запрос" in res["error"]

def test_list_deadlines_success():
    res_str = list_deadlines(discipline="elektro")
    res = json.loads(res_str)
    assert isinstance(res, list)
    assert res[0]["task"] == "Лаб.2"

def test_list_deadlines_invalid_discipline():
    res_str = list_deadlines(discipline="math")
    res = json.loads(res_str)
    assert "error" in res
    assert "Дисциплина не найдена" in res["error"]

def test_add_deadline_pending():
    # Наш мок возвращает PendingItem, проверяем, что сервер правильно обработал
    res_str = add_deadline(discipline="elektro", task="Лаб.3", due_text="завтра", source_msg="elektro:1060")
    res = json.loads(res_str)
    assert res["status"] == "pending"
    assert "Ожидает подтверждения" in res["message"]
    assert res["data"]["id"] == 12

def test_get_attachments_success():
    res_str = get_attachments(deadline_id=5)
    res = json.loads(res_str)
    assert len(res) == 1
    assert res[0]["name"] == "lab2_elektro.pdf"

def test_process_new_messages():
    res_str = process_new_messages(chat="elektro")
    res = json.loads(res_str)
    assert res["processed"] == 10