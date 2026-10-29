from datetime import date, datetime

import streamlit as st
from streamlit_calendar import calendar

from ui.common import dcolor, dname
from ui.tabs.card import render_card


PENDING_REASONS = {
    "low_confidence": "Низкая уверенность агента",
    "ambiguous_match": "Неясно: новый дедлайн или перенос",
    "no_match_for_move": "Не найден исходный дедлайн для переноса",
}


def format_date(value: str | None) -> str:
    if not value:
        return "Срок не указан"

    try:
        return datetime.fromisoformat(value).strftime("%d.%m.%Y")
    except ValueError:
        return value


def short_date(value: str | None) -> str:
    if not value:
        return "—"

    try:
        return datetime.fromisoformat(value).strftime("%d.%m")
    except ValueError:
        return value


def render_deadlines(provider):
    st.subheader("📅 Дедлайны")
    st.caption(
        "Все найденные задания, подтверждения "
        "и история изменения сроков."
    )

    deadlines = provider.list_deadlines()
    pending = provider.list_pending()

    active_deadlines = [
        item for item in deadlines
        if item.status == "active"
    ]

    # ---------------------------------------
    # Счётчики
    # ---------------------------------------
    today = date.today()

    next_week_count = 0

    for item in active_deadlines:
        if not item.due_at:
            continue

        try:
            due_date = datetime.fromisoformat(
                item.due_at
            ).date()

            days_left = (due_date - today).days

            if 0 <= days_left <= 7:
                next_week_count += 1

        except ValueError:
            pass

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric(
            "Активных дедлайнов",
            len(active_deadlines),
        )

    with col2:
        st.metric(
            "В ближайшие 7 дней",
            next_week_count,
        )

    with col3:
        st.metric(
            "Ждут подтверждения",
            len(pending),
        )

    st.divider()

    # ---------------------------------------
    # Ожидают подтверждения
    # ---------------------------------------
    st.subheader("⏳ Ожидают подтверждения")

    if not pending:
        st.success(
            "Все найденные дедлайны уже обработаны 🎉"
        )

    for item in pending:
        candidate = item.candidate

        discipline_name = dname(candidate.discipline)

        with st.container(border=True):
            st.markdown(
                f"### 📝 {candidate.task}"
            )

            info1, info2, info3 = st.columns(3)

            with info1:
                st.markdown("**Дисциплина**")
                st.write(discipline_name)

            with info2:
                st.markdown("**Найденный срок**")

                if candidate.due_at:
                    st.write(
                        format_date(candidate.due_at)
                    )
                else:
                    st.write(candidate.due_text)

            with info3:
                st.markdown("**Статус**")
                st.warning("Требует проверки")

            reason = PENDING_REASONS.get(
                item.reason,
                item.reason,
            )

            st.caption(
                f"Причина: {reason}"
            )

            st.markdown("**Исходное сообщение:**")

            st.info(item.source_text)

            col_ok, col_no, _ = st.columns(
                [1, 1, 3]
            )

            with col_ok:
                if st.button(
                    "✅ Подтвердить",
                    key=f"ok_{item.id}",
                    width="stretch",
                ):
                    provider.resolve_pending(
                        item.id,
                        True,
                    )

                    st.rerun()

            with col_no:
                if st.button(
                    "❌ Отклонить",
                    key=f"no_{item.id}",
                    width="stretch",
                ):
                    provider.resolve_pending(
                        item.id,
                        False,
                    )

                    st.rerun()

    st.divider()

    # ---------------------------------------
    # История переноса
    # ---------------------------------------
    st.subheader("🔄 История переноса")

    deadline_with_history = None
    history = []

    for deadline in deadlines:
        if deadline.id is None:
            continue

        deadline_history = (
            provider.get_deadline_history(deadline.id)
        )

        if deadline_history:
            deadline_with_history = deadline
            history = deadline_history
            break

    if deadline_with_history and history:
        discipline_name = dname(deadline_with_history.discipline)

        with st.container(border=True):
            st.markdown(
                f"### 🧪 {deadline_with_history.task}"
            )

            st.caption(discipline_name)

            dates = [
                short_date(event.new_due)
                for event in history
                if event.new_due
            ]

            if dates:
                st.markdown(
                    "## " + " → ".join(dates)
                )

            columns = st.columns(len(history))

            for column, event in zip(
                columns,
                history,
            ):
                with column:
                    st.markdown(
                        f"**{short_date(event.new_due)}**"
                    )

                    if event.old_due is None:
                        st.caption(
                            "Первоначальный срок"
                        )
                    else:
                        st.caption(
                            "Перенос срока"
                        )

            st.info(
                "Система сохранила историю "
                "изменений дедлайна."
            )

    else:
        st.info(
            "История переносов пока не найдена."
        )

    st.divider()

    # ---------------------------------------
    # Календарь
    # ---------------------------------------
    st.subheader("Календарь")

    events = []

    for deadline in active_deadlines:
        if not deadline.due_at:
            continue

        title = deadline.task

        if deadline.attachments:
            title += (
                f" 📎 {len(deadline.attachments)}"
            )

        events.append(
            {
                "id": str(deadline.id),
                "title": title,
                "start": deadline.due_at[:10],
                "allDay": True,
                "color": dcolor(deadline.discipline),
            }
        )

    calendar_options = {
        "initialView": "dayGridMonth",
        "initialDate": date.today().isoformat(),
        "height": 470,
        "locale": "ru",
        "firstDay": 1,
        "buttonText": {"today": "сегодня", "month": "месяц", "week": "неделя", "list": "список"},
        "headerToolbar": {
            "left": "prev,next today",
            "center": "title",
            "right": (
                "dayGridMonth,"
                "timeGridWeek,"
                "listWeek"
            ),
        },
    }

    clicked = calendar(
        events=events,
        options=calendar_options,
        callbacks=["eventClick"],
        key="provider_deadline_calendar",
    )

    # ---------------------------------------
    # Карточка задания
    # ---------------------------------------
    st.divider()
    st.subheader("🗂️ Карточка задания")

    options = {d.id: d for d in deadlines if d.id is not None}

    event = (clicked or {}).get("eventClick", {}).get("event", {})
    clicked_id = int(event["id"]) if str(event.get("id", "")).isdigit() else None
    if clicked_id in options and clicked_id != st.session_state.get("card_clicked_id"):
        st.session_state["card_clicked_id"] = clicked_id      # новый клик выбирает задание
        st.session_state["card_deadline_id"] = clicked_id

    if not options:
        st.info("Пока нет заданий.")
    else:
        if st.session_state.get("card_deadline_id") not in options:
            st.session_state.pop("card_deadline_id", None)   # задание могло исчезнуть из списка
        selected = st.selectbox(
            "Задание",
            list(options),
            key="card_deadline_id",
            format_func=lambda i: (
                f"{options[i].task} · {dname(options[i].discipline)} · "
                f"{short_date(options[i].due_at)}"
            ),
        )
        render_card(provider, selected)
