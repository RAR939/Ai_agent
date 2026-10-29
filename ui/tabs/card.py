"""Карточка задания: срок, история переносов, материалы (файлы), «Что говорили»."""
import os

import streamlit as st

from ui.common import BIND_NAMES, ROLE_NAMES, STATUS_NAMES, dname, fmt_date
from ui.tabs.chat import show_message_dialog

MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024


def _size(n: int) -> str:
    return f"{n / 1024:.0f} КБ" if n >= 1024 else f"{n} Б"


def render_card(provider, deadline_id: int) -> None:
    try:
        card = provider.get_card(deadline_id)
    except Exception as e:
        st.error(f"Не удалось открыть карточку: {e}")
        return
    d = card.deadline

    with st.container(border=True):
        st.markdown(f"### {d.task}")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown("**Дисциплина**")
            st.write(dname(d.discipline))
        with col2:
            st.markdown("**Срок**")
            st.write(fmt_date(d.due_at, with_time=True))
            st.caption(f"как написано: «{d.due_text}»" + (" · срок размытый" if d.fuzzy else ""))
        with col3:
            st.markdown("**Статус**")
            st.write(STATUS_NAMES.get(d.status, d.status))
        if st.button("💬 Показать сообщение-источник", key=f"card_src_{d.id}"):
            show_message_dialog(provider, d.source_msg)

    st.markdown("#### 🔄 История переносов")
    if not card.history:
        st.caption("Срок не переносили.")
    for event in card.history:
        left, right = st.columns([4, 1])
        with left:
            st.write(f"{fmt_date(event.old_due)} → {fmt_date(event.new_due)}  ·  {event.changed_at[:10]}")
        with right:
            if st.button("Показать", key=f"card_hist_{d.id}_{event.id}"):
                show_message_dialog(provider, event.source_msg)

    st.markdown("#### 📎 Материалы")
    if not d.attachments:
        st.caption("К заданию не прикреплено файлов.")
    for f in d.attachments:
        left, mid, right = st.columns([3, 3, 2])
        with left:
            st.write(f"**{f.name}**")
            st.caption(f"{f.ext.upper()} · {_size(f.size_bytes)}")
        with mid:
            st.caption(BIND_NAMES.get(f.bind or "", "привязка не указана"))
            if st.button("Показать сообщение", key=f"card_file_msg_{d.id}_{f.id}"):
                show_message_dialog(provider, f.msg_id)
        with right:
            path = provider.file_abs_path(f)
            if os.path.isfile(path) and os.path.getsize(path) <= MAX_DOWNLOAD_BYTES:
                with open(path, "rb") as fh:
                    st.download_button("⬇️ Скачать", fh.read(), file_name=f.name, key=f"card_dl_{d.id}_{f.id}")
            else:
                st.caption("Файл не найден")

    st.markdown("#### 🗣️ Что говорили")
    if not card.discussion:
        st.caption("Обсуждение не найдено: индекс не построен или нет подходящих сообщений.")
    for hit in card.discussion:
        roles = ", ".join(ROLE_NAMES.get(r, r) for r in hit.roles)
        with st.expander(f"{hit.ts_from[:10]} · {roles}"):
            st.write(hit.text)
            if hit.msg_ids and st.button("Показать в чате", key=f"card_hit_{d.id}_{hit.chunk_id}"):
                show_message_dialog(provider, hit.msg_ids[0])
