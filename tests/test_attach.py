"""Тесты задачи 4.9: привязка файлов только по связям сообщений."""
from datetime import datetime, timedelta

from src.schemas import Message
from src.tracker import attach
from tests.conftest import make_file

BASE = datetime(2026, 10, 20, 14, 0)


def msg(n, minutes, author="STAROSTA", text="шум", files=(), reply_to=None, ext="pdf"):
    ts = (BASE + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:00+03:00")
    mid = f"elektro:{n}"
    return Message(id=mid, chat="elektro", ts=ts, author=author, role="starosta", text=text,
                   reply_to=reply_to, src=f"m#{n}",
                   attachments=[make_file(mid, k, ext=ext, name=f"{n}_{k}.{ext}") for k in files])


def ids(files):
    return {f.id: f.bind for f in files}


SRC = lambda **kw: msg(10, 0, text="Лаб.2 сдаём до пятницы", **kw)


def test_a_same_message():
    m = SRC(files=[1, 2])
    assert ids(attach.collect_files(m, [m])) == {
        "elektro:10:f1": "same_message", "elektro:10:f2": "same_message"}


def test_b_same_author_five_minutes_later():
    src, f = SRC(), msg(11, 5, text="вот методичка", files=[1])
    assert ids(attach.collect_files(src, [src, f])) == {"elektro:11:f1": "same_author_near"}


def test_b_same_author_shortly_before():
    src, f = SRC(), msg(9, -3, text="вот файл", files=[1])
    assert ids(attach.collect_files(src, [f, src])) == {"elektro:9:f1": "same_author_near"}


def test_c_reply_to_question_chain():
    q = msg(8, -2, author="STUDENT_1", text="когда сдавать Лаб.2?")
    src = msg(10, 0, text="до пятницы", reply_to=q.id)
    answer_file = msg(11, 30, author="TEACHER_1", text="вот условие", files=[1], reply_to=src.id)
    q_file = msg(7, -60, author="STUDENT_2", text="мой пример", files=[1])
    assert ids(attach.collect_files(src, [q_file, q, src, answer_file])) == {
        "elektro:11:f1": "reply_context"}


def test_c_file_in_the_parent_message():
    q = msg(8, -2, author="STUDENT_1", text="кто знает Лаб.2? вот условие", files=[1])
    src = msg(10, 0, text="до пятницы", reply_to=q.id)
    assert ids(attach.collect_files(src, [q, src])) == {"elektro:8:f1": "reply_context"}


def test_g_foreign_file_at_same_time_is_not_attached():
    src = SRC()
    other = msg(11, 0, author="STUDENT_4", text="мой отчёт", files=[1])
    assert attach.collect_files(src, [src, other]) == []


def test_d_file_after_an_hour_is_not_attached():
    src, late = SRC(), msg(11, 61, text="шаблон", files=[1])
    assert attach.collect_files(src, [src, late]) == []


def test_window_boundary_is_inclusive_and_configurable(set_cfg):
    src, edge, over = SRC(), msg(11, 10, files=[1]), msg(12, 11, files=[1])
    assert set(ids(attach.collect_files(src, [src, edge, over]))) == {"elektro:11:f1"}
    set_cfg({"tracker": {"attach_window_min": 30}})
    assert set(ids(attach.collect_files(src, [src, edge, over]))) == {"elektro:11:f1", "elektro:12:f1"}


def test_file_of_neighbour_with_own_other_deadline_is_not_attached():
    src = SRC()
    neighbour = msg(11, 2, text="Лаб.3 сдаём до 6.11", files=[1])
    assert attach.collect_files(src, [src, neighbour]) == []


def test_neighbour_with_same_task_deadline_is_attached():
    src = SRC()
    same_task = msg(11, 2, text="Лаб.2 вот условие, сдаём до пятницы", files=[1])
    assert ids(attach.collect_files(src, [src, same_task])) == {"elektro:11:f1": "same_author_near"}


def test_extension_filter():
    src = msg(10, 0, text="Лаб.2 до пятницы", files=[1])
    img = msg(11, 1, text="фото", files=[1], ext="png")
    assert set(ids(attach.collect_files(src, [src, img]))) == {"elektro:10:f1"}


def test_limit_per_message(set_cfg):
    set_cfg({"tracker": {"attach_max_per_msg": 2}})
    m = SRC(files=[1, 2, 3, 4])
    assert list(ids(attach.collect_files(m, [m]))) == ["elektro:10:f1", "elektro:10:f2"]


def test_duplicates_collapse_and_first_rule_wins():
    # сообщение-ответ того же автора рядом: правило 2 срабатывает раньше правила 3
    src = SRC()
    f = msg(11, 3, text="методичка", files=[1], reply_to=src.id)
    assert ids(attach.collect_files(src, [src, f, f])) == {"elektro:11:f1": "same_author_near"}


def test_no_files_anywhere():
    src = SRC()
    assert attach.collect_files(src, [src, msg(11, 1, text="привет")]) == []


def test_result_files_are_copies_with_bind_not_mutating_input():
    src, f = SRC(), msg(11, 1, files=[1])
    attach.collect_files(src, [src, f])
    assert f.attachments[0].bind is None
