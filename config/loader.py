# config/loader.py
"""Временная совместимая заглушка load_config() до модуля роли 1.

Удалить после подключения штатного загрузчика команды. Новых параметров
в этой функции нет: все настройки берутся из config/config.yaml.
"""
from __future__ import annotations

from pathlib import Path
import yaml


def load_config() -> dict:
    """Загрузить конфигурацию проекта из config/config.yaml."""
    path = Path(__file__).with_name("config.yaml")
    with path.open(encoding="utf-8") as stream:
        result = yaml.safe_load(stream)
    if not isinstance(result, dict):
        raise ValueError("Конфигурация должна быть словарём")
    return result
