"""Клиент Ollama: локальный или на сервере. Единая точка доступа к модели для агента, трекера и поиска.

Настройки (config/config.yaml, раздел models):
  host         адрес сервера Ollama, например "http://localhost:11434" или "https://llm.example.org";
               пусто: переменная окружения OLLAMA_HOST, иначе локальная Ollama
  timeout_sec  время ожидания ответа сервера
Переменные окружения (имеют приоритет над конфигом, в git не попадают):
  OLLAMA_HOST     адрес сервера (удобно для SSH-туннеля у каждого свой)
  OLLAMA_API_KEY  токен: уходит заголовком Authorization: Bearer <токен> (нужен, если перед Ollama стоит прокси с проверкой токена)
"""
import os
from functools import lru_cache

import ollama

from src.config import load_config

DEFAULT_TIMEOUT = 120.0


def settings() -> dict:
    """Адрес, токен и таймаут с учётом конфига и окружения."""
    models = load_config()["models"]
    return {"host": os.environ.get("OLLAMA_HOST") or models.get("host") or None,
            "token": os.environ.get("OLLAMA_API_KEY") or None,
            "timeout": float(models.get("timeout_sec") or DEFAULT_TIMEOUT)}


@lru_cache(maxsize=8)
def _make(host: str | None, token: str | None, timeout: float) -> ollama.Client:
    headers = {"Authorization": f"Bearer {token}"} if token else None
    return ollama.Client(host=host, headers=headers, timeout=timeout)


def client(timeout: float | None = None) -> ollama.Client:
    """Клиент по текущим настройкам (кэшируется; timeout переопределяет таймаут, например для проверки связи)."""
    s = settings()
    return _make(s["host"], s["token"], timeout if timeout is not None else s["timeout"])


def chat(**kwargs):
    return client().chat(**kwargs)


def embed(**kwargs):
    return client().embed(**kwargs)


def list_models(timeout: float | None = None) -> list[str]:
    """Названия моделей, скачанных на сервере."""
    return [m.model for m in client(timeout).list().models]


def describe() -> str:
    """Куда идут запросы (без токена): для сообщений об ошибках и проверки окружения."""
    s = settings()
    return (s["host"] or "локальная Ollama") + (", токен задан" if s["token"] else "")
