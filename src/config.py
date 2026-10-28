"""Конфигурация проекта (задача 0.4): config.yaml + disciplines.yaml + roles.yaml.

Сигнатуры по docs/contracts.md, раздел 4. Если роль 1 уже выложила свою версию,
при слиянии берите её: контракт функций тот же.
"""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_config(config_dir: str | Path | None = None) -> dict:
    """Собирает настройки: config.yaml + ключи «disciplines» и «roles» из соседних файлов."""
    folder = Path(config_dir) if config_dir else CONFIG_DIR
    cfg = _read_yaml(folder / "config.yaml")
    cfg["disciplines"] = _read_yaml(folder / "disciplines.yaml")
    cfg["roles"] = _read_yaml(folder / "roles.yaml")
    return cfg


def _disciplines() -> dict:
    return load_config()["disciplines"]


def discipline_name(key: str) -> str:
    """'elektro' -> 'Электротехника'; неизвестный ключ возвращается как есть."""
    return (_disciplines().get(key) or {}).get("name", key)


def discipline_color(key: str) -> str:
    """Цвет дисциплины для интерфейса; серый, если не задан."""
    return (_disciplines().get(key) or {}).get("color", "#888888")


def _norm(text: str) -> str:
    """Нижний регистр, ё -> е, всё кроме букв и цифр заменено пробелами."""
    text = text.lower().replace("ё", "е")
    return re.sub(r"[^a-zа-я0-9]+", " ", text).strip()


def find_discipline(text: str) -> str | None:
    """Ключ дисциплины по алиасам в тексте или None.

    Короткие алиасы (до 3 символов, например «ЭТ», «БД») совпадают только как целое
    слово, длинные как начало слова («электротех» найдёт «электротехнике»).
    Побеждает самый длинный совпавший алиас.
    """
    if not text:
        return None
    norm = _norm(text)
    tokens = norm.split()
    padded = f" {norm} "
    best_key, best_len = None, 0
    for key, info in _disciplines().items():
        names = [key, (info or {}).get("name", ""), *(info or {}).get("aliases", [])]
        for alias in names:
            a = _norm(alias)
            if not a:
                continue
            if " " in a:
                hit = f" {a}" in padded
            elif len(a) <= 3:
                hit = a in tokens
            else:
                hit = any(t.startswith(a) for t in tokens)
            if hit and len(a) > best_len:
                best_key, best_len = key, len(a)
    return best_key
