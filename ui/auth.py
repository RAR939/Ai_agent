"""Необязательный вход по паролю: если задана переменная окружения HELPER_UI_PASSWORD, приложение просит пароль.

Нужен, когда интерфейс на сервере доступен не только через SSH-туннель (VPN, обратный прокси).
Пароль в конфиг и git не кладётся.
"""
import hmac
import os

import streamlit as st

ENV = "HELPER_UI_PASSWORD"


def expected_password() -> str | None:
    return os.environ.get(ENV) or None


def password_ok(entered: str, expected: str) -> bool:
    return hmac.compare_digest(entered.encode(), expected.encode())


def require_password() -> None:
    """Пропускает дальше только после правильного пароля; без заданного пароля ничего не делает."""
    expected = expected_password()
    if expected is None or st.session_state.get("authed"):
        return
    st.title("🔒 Вход")
    with st.form("login"):
        entered = st.text_input("Пароль", type="password")
        submitted = st.form_submit_button("Войти")
    if submitted:
        if password_ok(entered, expected):
            st.session_state["authed"] = True
            st.rerun()
        st.error("Неверный пароль")
    st.stop()
