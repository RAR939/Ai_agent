import streamlit as st


CHAT_NAMES = {
    "electro": "⚡ Электротехника",
    "probability": "📊 Теория вероятностей",
    "data_models": "🗃️ Модели данных",
}


def format_date(value: str | None) -> str:
    if value is None:
        return "Нет данных"

    try:
        date_part = value[:10]
        year, month, day = date_part.split("-")
        return f"{day}.{month}.{year}"
    except (ValueError, IndexError):
        return value


def render_sources(provider):
    st.subheader("📚 Источники")
    st.caption(
        "Состояние подключённых учебных чатов "
        "и индекса поиска."
    )

    # -------------------------
    # Общая статистика
    # -------------------------
    stats = provider.corpus_stats()

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "Подключено чатов",
            stats.get("chats", 0),
        )

    with col2:
        st.metric(
            "Сообщений",
            f"{stats.get('messages', 0):,}".replace(",", " "),
        )

    with col3:
        st.metric(
            "Дедлайнов",
            stats.get("deadlines", 0),
        )

    with col4:
        st.metric(
            "Чанков в индексе",
            stats.get("chunks", 0),
        )

    st.divider()

    # -------------------------
    # Подключённые чаты
    # -------------------------
    st.subheader("💬 Подключённые чаты")

    chats = provider.index_status()

    for chat in chats:
        with st.container(border=True):
            col_info, col_status = st.columns([4, 1])

            with col_info:
                name = CHAT_NAMES.get(
                    chat.chat,
                    f"💬 {chat.chat}",
                )

                st.markdown(f"### {name}")

                info1, info2, info3 = st.columns(3)

                with info1:
                    st.markdown("**Сообщений**")
                    st.write(
                        f"{chat.messages:,}".replace(",", " ")
                    )

                with info2:
                    st.markdown("**Чанков**")
                    st.write(chat.chunks)

                with info3:
                    st.markdown("**Дедлайнов**")
                    st.write(chat.deadlines)

                st.caption(
                    "Период: "
                    f"{format_date(chat.period_from)} — "
                    f"{format_date(chat.period_to)}"
                )

                st.caption(
                    "Последняя обработка: "
                    f"{format_date(chat.last_processed)}"
                )

            with col_status:
                st.success("Актуально")

    st.divider()

    # -------------------------
    # Управление
    # -------------------------
    st.subheader("⚙️ Управление")

    col1, col2 = st.columns(2)

    with col1:
        if st.button(
            "🔄 Обновить индекс",
            key="reindex_all",
            use_container_width=True,
        ):
            result = provider.reindex("all")

            if result.get("status") == "ok":
                st.success(
                    "Индекс успешно обновлён. "
                    f"Чанков: {result.get('chunks', 0)}."
                )
            else:
                st.error("Не удалось обновить индекс.")

    with col2:
        if st.button(
            "📥 Обработать новые сообщения",
            key="process_new_all",
            use_container_width=True,
        ):
            report = provider.process_new("all")

            st.success(
                "Обработка завершена: "
                f"{report.processed} сообщений · "
                f"новых дедлайнов: {report.added} · "
                f"переносов: {report.moved} · "
                f"ожидают подтверждения: {report.pending}"
            )