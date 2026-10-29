"""Тесты задачи 4.4: предфильтр, охват и отсечение на синтетическом наборе."""
import json
import pathlib

import pytest

from src.schemas import Message
from src.tracker import prefilter

SET = json.loads((pathlib.Path(__file__).parent / "fixtures" / "prefilter_set.json")
                 .read_text(encoding="utf-8"))


def mk(text, reply_to=None, i=1):
    return Message(id=f"t:{i}", chat="t", ts="2026-10-20T10:01:00+03:00", author="STAROSTA",
                   role="starosta", text=text, reply_to=reply_to, src="x")


def run(item):
    by_id = {}
    reply_to = None
    if item.get("parent"):
        parent = mk(item["parent"], i=0)
        by_id[parent.id] = parent
        reply_to = parent.id
    return prefilter.looks_like_deadline(mk(item["text"], reply_to), by_id)


def test_coverage_at_least_95_percent():
    hit = sum(run(i) for i in SET["positives"])
    assert hit / len(SET["positives"]) >= 0.95


def test_filters_out_most_noise():
    passed = sum(run(i) for i in SET["negatives"])
    assert 1 - passed / len(SET["negatives"]) > 0.70


@pytest.mark.parametrize("text", [
    "Лаб.2 сдаём до пятницы", "сдадим лабу завтра", "СДАВАТЬ ДЗ до 12.11", "дедлайн 5 ноября",
    "зачёт в 10:00", "зачет в 10:00",                       # ё и е равнозначны
    "Сдать лабу на следующей паре", "лр2 до среды"])
def test_lemmatization_and_forms(text):
    assert prefilter.looks_like_deadline(mk(text))


@pytest.mark.parametrize("text", [
    "", "   ", "👍", "ахах", "кто сдал лабу?", "завтра будет дождь", "дедлайн близко"])
def test_obvious_non_deadlines(text):
    assert not prefilter.looks_like_deadline(mk(text))


def test_cancel_and_move_pass_without_time():
    assert prefilter.looks_like_deadline(mk("ДЗ 1 отменяется"))
    assert prefilter.looks_like_deadline(mk("Лабу перенесли"))


def test_reply_to_task_message_passes_without_keywords():
    parent = mk("Когда сдавать Лаб.2?", i=0)
    reply = mk("до пятницы", reply_to=parent.id)
    assert prefilter.looks_like_deadline(reply, {parent.id: parent})
    assert not prefilter.looks_like_deadline(mk("до пятницы"))           # без родителя нет


def test_reply_without_time_does_not_pass():
    parent = mk("Когда сдавать Лаб.2?", i=0)
    assert not prefilter.looks_like_deadline(mk("не знаю", reply_to=parent.id), {parent.id: parent})


def test_reply_to_known_deadline_message():
    reply = mk("в среду", reply_to="t:77")
    assert prefilter.looks_like_deadline(reply, None, {"t:77"})
    assert not prefilter.looks_like_deadline(reply, None, {"t:1"})


def test_keywords_come_from_config(set_cfg):
    set_cfg({"tracker": {"prefilter_keywords": ["квиз"], "prefilter_strong_keywords": []}})
    assert prefilter.looks_like_deadline(mk("квиз завтра"))
    assert not prefilter.looks_like_deadline(mk("лабу сдаём завтра"))


def test_lemma_helpers():
    assert prefilter.lemma("Сдаём") == "сдавать" and prefilter.lemma("зачёт") == "зачет"
    assert {"сдаем", "сдавать"} <= prefilter.lemmas("Сдаём ЛР2")
    assert prefilter.has_keyword("лабу сдаём") and not prefilter.has_keyword("привет")
    assert prefilter.has_strong_keyword("отменили пару") and not prefilter.has_strong_keyword("сдаём")
    assert prefilter.has_time_marker("до 5.11") and prefilter.has_time_marker("в 18:00")
    assert prefilter.has_time_marker("12 ноября") and prefilter.has_time_marker("во вторник")
    assert not prefilter.has_time_marker("привет")
