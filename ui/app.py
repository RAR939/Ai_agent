from pathlib import Path
import sys

import streamlit as st


# --------------------------------------------------
# Добавляем корень проекта в Python path
# --------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# --------------------------------------------------
# Импорты проекта
# --------------------------------------------------
from ui.auth import require_password
from ui.provider import make_provider
from ui.tabs.chat import render_chat
from ui.tabs.deadlines import render_deadlines
from ui.tabs.schedule import render_schedule
from ui.tabs.sources import render_sources


# --------------------------------------------------
# Настройки страницы
# --------------------------------------------------
st.set_page_config(
    page_title="Помощник студента",
    page_icon="🎓",
    layout="wide",
)


# --------------------------------------------------
# Стили
# --------------------------------------------------
st.markdown(
    """
    <style>
        .block-container {
            padding-top: 4rem;
            padding-bottom: 3rem;
            max-width: 1400px;
        }

        .main-title {
            font-size: 38px;
            font-weight: 800;
            line-height: 1.3;
            margin-top: 0;
            margin-bottom: 0;
        }

        .subtitle {
            color: #808080;
            font-size: 16px;
            margin-top: 5px;
            margin-bottom: 28px;
        }

        div[data-testid="stMetric"] {
            background-color: #ffffff;
            border: 1px solid #e5e7eb;
            padding: 18px;
            border-radius: 12px;
        }

        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 14px;
        }

        .stButton > button {
            border-radius: 9px;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------
# Провайдер
# --------------------------------------------------
require_password()                  # только если задан HELPER_UI_PASSWORD

if "provider" not in st.session_state:
    st.session_state.provider = make_provider()

provider = st.session_state.provider


# --------------------------------------------------
# Заголовок приложения
# --------------------------------------------------
st.markdown(
    '<p class="main-title">🎓 Помощник студента</p>',
    unsafe_allow_html=True,
)

st.markdown(
    """
    <p class="subtitle">
        Анализ учебных чатов, дедлайнов и расписания
    </p>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------
# Вкладки
#
# Дедлайны оставляем первой вкладкой, потому что
# streamlit-calendar корректнее отображается
# именно в первой вкладке.
# --------------------------------------------------
tab_deadlines, tab_chat, tab_schedule, tab_sources = st.tabs(
    [
        "📅 Дедлайны",
        "💬 Чат",
        "🗓️ Расписание",
        "📚 Источники",
    ]
)


# --------------------------------------------------
# Содержимое вкладок
# --------------------------------------------------
with tab_deadlines:
    render_deadlines(provider)

with tab_chat:
    render_chat(provider)

with tab_schedule:
    render_schedule(provider)

with tab_sources:
    render_sources(provider)