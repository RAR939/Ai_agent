import streamlit as st

from ui.highlight import find_span, highlight


def build_highlighted_text(text: str) -> str:
    spans = []

    variants = [
        ("Электротехника", "discipline"),
        ("электротехнике", "discipline"),
        ("Теория вероятностей", "discipline"),
        ("теории вероятностей", "discipline"),
        ("Лабораторную работу №2", "task"),
        ("лабораторную работу №2", "task"),
        ("Домашнее задание", "task"),
        ("домашнее задание", "task"),
        ("до конца недели", "deadline"),
        ("до понедельника", "deadline"),
        ("до пятницы", "deadline"),
    ]

    for value, label in variants:
        span = find_span(
            text,
            value,
            label,
        )

        if span is not None:
            spans.append(span)

    if not spans:
        return text

    return highlight(text, spans)


@st.dialog("Сообщение из чата")
def show_message_dialog(provider, msg_id: str):
    context = provider.get_message_context(
        msg_id,
        before=3,
        after=3,
    )

    st.caption(
        f"{context.target.chat} · "
        f"{context.target.ts[:10]} · "
        f"{context.target.author}"
    )

    if context.before:
        st.markdown("### До сообщения")

        for message in context.before:
            st.write(message.text)

    st.markdown("### Найденное сообщение")

    highlighted = build_highlighted_text(
        context.target.text
    )

    st.markdown(
        highlighted,
        unsafe_allow_html=True,
    )

    st.caption(
        "🟨 срок   ·   🟦 задание   ·   🟩 дисциплина"
    )

    if context.after:
        st.markdown("### После сообщения")

        for message in context.after:
            st.write(message.text)


def ask_agent(provider, question: str):
    history = [
        {
            "role": message["role"],
            "content": message["content"],
        }
        for message in st.session_state.messages
    ]

    st.session_state.messages.append(
        {
            "role": "user",
            "content": question,
        }
    )

    with st.spinner("Думаю..."):
        result = provider.ask(
            question,
            history,
        )

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": result.text,
            "sources": result.sources,
            "trace": result.trace,
            "pending_ids": result.pending_ids,
        }
    )


def render_sources(provider, sources, message_index: int):
    if not sources:
        return

    with st.expander("📚 Источники"):
        for source_index, source in enumerate(
            sources,
            start=1,
        ):
            st.markdown(
                f"### Источник {source_index}"
            )

            roles = ", ".join(source.roles)

            st.caption(
                f"{source.ts_from[:10]} · "
                f"{roles} · "
                f"{source.chat}"
            )

            preview = source.text[:200]

            if len(source.text) > 200:
                preview += "..."

            st.write(preview)

            if source.msg_ids:
                msg_id = source.msg_ids[0]

                if st.button(
                    "Показать сообщение",
                    key=(
                        f"source_{message_index}_"
                        f"{source_index}"
                    ),
                ):
                    show_message_dialog(
                        provider,
                        msg_id,
                    )

            if source_index < len(sources):
                st.divider()


def render_trace(trace):
    if not trace:
        return

    with st.expander(
        "🛠️ Какие инструменты вызвала модель"
    ):
        rows = []

        for call in trace:
            rows.append(
                {
                    "Инструмент": call.tool,
                    "Параметры": str(call.args),
                    "Результат": call.result_preview,
                    "Время": f"{call.duration:.2f} сек",
                    "Ошибка": call.error or "—",
                }
            )

        st.dataframe(
            rows,
            width="stretch",
            hide_index=True,
        )


def render_pending(provider, pending_ids):
    if not pending_ids:
        return

    st.warning(
        "Некоторые найденные дедлайны "
        "ожидают подтверждения."
    )

    for pending_id in pending_ids:
        col1, col2 = st.columns(2)

        with col1:
            if st.button(
                "✅ Подтвердить",
                key=f"chat_ok_{pending_id}",
                width="stretch",
            ):
                provider.resolve_pending(
                    pending_id,
                    True,
                )

                st.success(
                    "Дедлайн подтверждён."
                )

                st.rerun()

        with col2:
            if st.button(
                "❌ Отклонить",
                key=f"chat_no_{pending_id}",
                width="stretch",
            ):
                provider.resolve_pending(
                    pending_id,
                    False,
                )

                st.rerun()


def render_chat(provider):
    st.subheader("💬 Чат с помощником")

    st.caption(
        "Спросите про дедлайны, расписание "
        "или информацию из учебных чатов."
    )

    # ---------------------------------------
    # История чата
    # ---------------------------------------
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": (
                    "Привет! Я помогу найти дедлайны, "
                    "занятия и информацию "
                    "из учебных чатов."
                ),
            }
        ]

    # ---------------------------------------
    # Быстрые вопросы
    # ---------------------------------------
    st.markdown("#### Быстрые вопросы")

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button(
            "📅 Что сдавать на этой неделе?",
            key="quick_deadlines",
            width="stretch",
        ):
            ask_agent(
                provider,
                "Что сдавать на этой неделе?",
            )

            st.rerun()

    with col2:
        if st.button(
            "🕒 Когда следующая пара?",
            key="quick_schedule",
            width="stretch",
        ):
            ask_agent(
                provider,
                "Когда следующая пара?",
            )

            st.rerun()

    with col3:
        if st.button(
            "🔄 Какие сроки переносили?",
            key="quick_moves",
            width="stretch",
        ):
            ask_agent(
                provider,
                "Какие сроки переносили?",
            )

            st.rerun()

    st.divider()

    # ---------------------------------------
    # Вывод истории
    # ---------------------------------------
    for index, message in enumerate(
        st.session_state.messages
    ):
        with st.chat_message(
            message["role"]
        ):
            st.markdown(
                message["content"]
            )

            if message["role"] == "assistant":
                render_sources(
                    provider,
                    message.get(
                        "sources",
                        [],
                    ),
                    index,
                )

                render_trace(
                    message.get(
                        "trace",
                        [],
                    )
                )

                render_pending(
                    provider,
                    message.get(
                        "pending_ids",
                        [],
                    ),
                )

    # ---------------------------------------
    # Поле ввода
    # ---------------------------------------
    question = st.chat_input(
        "Спросите про сроки, расписание или чат"
    )

    if question:
        ask_agent(
            provider,
            question,
        )

        st.rerun()

    # ---------------------------------------
    # Очистка истории
    # ---------------------------------------
    st.divider()

    if st.button(
        "🗑️ Очистить историю",
        key="clear_chat_history",
    ):
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": (
                    "Привет! Я помогу найти дедлайны, "
                    "занятия и информацию "
                    "из учебных чатов."
                ),
            }
        ]

        st.rerun()