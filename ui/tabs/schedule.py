import tempfile
from datetime import datetime
from pathlib import Path

import streamlit as st


DISCIPLINE_NAMES = {
    "electro": "⚡ Электротехника",
    "probability": "📊 Теория вероятностей",
    "data_models": "🗃️ Модели данных",
    "programming": "💻 Программирование",
    "math": "📐 Математика",
}


LESSON_TYPE_NAMES = {
    "lecture": "Лекция",
    "seminar": "Семинар",
    "lab": "Лабораторная",
    "other": "Занятие",
}


DAY_NAMES = {
    0: "Понедельник",
    1: "Вторник",
    2: "Среда",
    3: "Четверг",
    4: "Пятница",
    5: "Суббота",
    6: "Воскресенье",
}


def parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def render_lesson(lesson):
    start = parse_datetime(lesson.start)
    end = parse_datetime(lesson.end)

    discipline = DISCIPLINE_NAMES.get(
        lesson.discipline,
        lesson.discipline,
    )

    lesson_type = LESSON_TYPE_NAMES.get(
        lesson.lesson_type,
        lesson.lesson_type,
    )

    st.markdown(
        f"**{start.strftime('%H:%M')} — "
        f"{end.strftime('%H:%M')}**"
    )

    st.write(discipline)

    details = lesson_type

    if lesson.room:
        details += f" · ауд. {lesson.room}"

    st.caption(details)


def render_schedule(provider):
    st.subheader("🗓️ Расписание")
    st.caption(
        "Занятия на неделю и загрузка нового расписания."
    )

    # ---------------------------------------
    # Загрузка расписания
    # ---------------------------------------
    with st.container(border=True):
        st.markdown("### 📤 Загрузить расписание")

        uploaded_file = st.file_uploader(
            "Выберите файл .xlsx или .ics",
            type=["xlsx", "ics"],
        )

        if uploaded_file is None:
            st.info(
                "Загрузите файл расписания — "
                "перед добавлением будет показан "
                "предварительный просмотр."
            )

        else:
            suffix = Path(
                uploaded_file.name
            ).suffix

            with tempfile.NamedTemporaryFile(
                delete=False,
                suffix=suffix,
            ) as temp_file:
                temp_file.write(
                    uploaded_file.getbuffer()
                )

                temp_path = temp_file.name

            preview = provider.load_schedule(
                temp_path,
                dry_run=True,
            )

            if preview.errors:
                st.error(
                    "В расписании найдены ошибки."
                )

                for error in preview.errors:
                    st.error(error)

            else:
                st.success(
                    f"Файл «{uploaded_file.name}» "
                    "успешно распознан."
                )

                st.markdown(
                    "#### Предварительный просмотр"
                )

                rows = []

                for lesson in preview.lessons:
                    start = parse_datetime(
                        lesson.start
                    )

                    end = parse_datetime(
                        lesson.end
                    )

                    rows.append(
                        {
                            "Дата": start.strftime(
                                "%d.%m.%Y"
                            ),
                            "Время": (
                                f"{start.strftime('%H:%M')}"
                                f" — "
                                f"{end.strftime('%H:%M')}"
                            ),
                            "Дисциплина": (
                                DISCIPLINE_NAMES.get(
                                    lesson.discipline,
                                    lesson.discipline,
                                )
                            ),
                            "Тип": (
                                LESSON_TYPE_NAMES.get(
                                    lesson.lesson_type,
                                    lesson.lesson_type,
                                )
                            ),
                            "Аудитория": (
                                lesson.room or "—"
                            ),
                        }
                    )

                st.dataframe(
                    rows,
                    width="stretch",
                    hide_index=True,
                )

                if st.button(
                    "✅ Загрузить расписание",
                    key="load_schedule",
                    width="stretch",
                ):
                    result = provider.load_schedule(
                        temp_path,
                        dry_run=False,
                    )

                    if result.ok:
                        st.success(
                            "Расписание загружено. "
                            f"Заменено занятий: "
                            f"{result.replaced}."
                        )
                    else:
                        st.error(
                            "Не удалось загрузить "
                            "расписание."
                        )

    st.divider()

    # ---------------------------------------
    # Недельное расписание
    # ---------------------------------------
    st.subheader("📆 Эта неделя")

    lessons = provider.lessons_between(
        "2026-11-02T00:00:00+03:00",
        "2026-11-08T23:59:00+03:00",
    )

    lessons_by_day = {}

    for lesson in lessons:
        start = parse_datetime(lesson.start)

        lessons_by_day.setdefault(
            start.weekday(),
            [],
        ).append(lesson)

    first_row = st.columns(3)

    for column, weekday in zip(
        first_row,
        [0, 1, 2],
    ):
        with column:
            with st.container(border=True):
                st.markdown(
                    f"### {DAY_NAMES[weekday]}"
                )

                day_lessons = lessons_by_day.get(
                    weekday,
                    [],
                )

                if day_lessons:
                    first_date = parse_datetime(
                        day_lessons[0].start
                    )

                    st.caption(
                        first_date.strftime(
                            "%d.%m.%Y"
                        )
                    )

                    for index, lesson in enumerate(
                        day_lessons
                    ):
                        render_lesson(lesson)

                        if index < len(day_lessons) - 1:
                            st.divider()

                else:
                    st.caption("Нет занятий")
                    st.success("Свободный день 🎉")

    second_row = st.columns(3)

    for column, weekday in zip(
        second_row,
        [3, 4, 5],
    ):
        with column:
            with st.container(border=True):
                st.markdown(
                    f"### {DAY_NAMES[weekday]}"
                )

                day_lessons = lessons_by_day.get(
                    weekday,
                    [],
                )

                if day_lessons:
                    first_date = parse_datetime(
                        day_lessons[0].start
                    )

                    st.caption(
                        first_date.strftime(
                            "%d.%m.%Y"
                        )
                    )

                    for index, lesson in enumerate(
                        day_lessons
                    ):
                        render_lesson(lesson)

                        if index < len(day_lessons) - 1:
                            st.divider()

                else:
                    st.caption("Нет занятий")
                    st.success("Свободный день 🎉")