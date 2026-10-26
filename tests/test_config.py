"""Тесты src/config.py: загрузка конфигов, справочник дисциплин, поиск по алиасам."""
import os
import shutil

import pytest
import yaml

from src import config
from src.config import (
    discipline_color, discipline_name, find_discipline, load_config,
)

REAL_DIR = config.CONFIG_DIR


@pytest.fixture
def cfg_dir(tmp_path, monkeypatch):
    """Копия config/ во временной папке, чтобы менять файлы."""
    d = tmp_path / "config"
    shutil.copytree(REAL_DIR, d)
    monkeypatch.setattr(config, "CONFIG_DIR", d)
    return d


def _write(path, data):
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    st = path.stat()   # mtime мог совпасть с прежним: сдвигаем, чтобы кэш обновился
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))


# ---------- load_config ----------
def test_load_real_config():
    cfg = load_config()
    for section in config.REQUIRED_SECTIONS:
        assert isinstance(cfg[section], dict)
    assert cfg["models"]["llm"] == "qwen3:8b"
    assert cfg["tracker"]["attach_window_min"] == 10
    assert set(cfg["disciplines"]) == {"elektro", "models", "algo"}
    assert cfg["roles"]["starosta"] == ["Имя Фамилия как в экспорте"]


def test_changing_config_changes_result(cfg_dir):
    data = yaml.safe_load((cfg_dir / "config.yaml").read_text(encoding="utf-8"))
    data["models"]["llm"] = "qwen3:4b"
    _write(cfg_dir / "config.yaml", data)
    assert load_config()["models"]["llm"] == "qwen3:4b"


def test_missing_section(cfg_dir):
    data = yaml.safe_load((cfg_dir / "config.yaml").read_text(encoding="utf-8"))
    del data["tracker"]
    _write(cfg_dir / "config.yaml", data)
    with pytest.raises(ValueError, match="tracker"):
        load_config()


def test_reserved_keys(cfg_dir):
    data = yaml.safe_load((cfg_dir / "config.yaml").read_text(encoding="utf-8"))
    data["roles"] = {}
    _write(cfg_dir / "config.yaml", data)
    with pytest.raises(ValueError, match="зарезервированы"):
        load_config()


def test_missing_file(cfg_dir):
    (cfg_dir / "config.yaml").unlink()
    with pytest.raises(FileNotFoundError, match="config.yaml"):
        load_config()


def test_broken_yaml(cfg_dir):
    (cfg_dir / "config.yaml").write_text("models: [unclosed", encoding="utf-8")
    with pytest.raises(ValueError, match="config.yaml"):
        load_config()


def test_roles_local_overrides_template(cfg_dir):
    _write(cfg_dir / "roles.local.yaml", {"starosta": ["Тест Тестов"], "teachers": {}, "students": []})
    assert load_config()["roles"]["starosta"] == ["Тест Тестов"]


def test_gitignore_has_roles_local():
    gitignore = (REAL_DIR.parent / ".gitignore").read_text(encoding="utf-8")
    assert "config/roles.local.yaml" in gitignore


# ---------- проверки disciplines.yaml ----------
@pytest.mark.parametrize("data,match", [
    ({}, "непустой"),
    ({"Elektro": {"name": "Э"}}, "латиницей"),
    ({"эл": {"name": "Э"}}, "латиницей"),
    ({"a": {"color": "#000000"}}, "name"),
    ({"a": {"name": "A", "color": "red"}}, "цвет"),
    ({"a": {"name": "A", "aliases": "один"}}, "aliases"),
    ({"a": {"name": "A", "aliases": [""]}}, "aliases"),
    ({"a": {"name": "A", "aliases": ["Тест"]}, "b": {"name": "B", "aliases": ["тест"]}}, "повторяется"),
])
def test_bad_disciplines(cfg_dir, data, match):
    _write(cfg_dir / "disciplines.yaml", data)
    with pytest.raises(ValueError, match=match):
        load_config()


def test_default_color_and_no_aliases(cfg_dir):
    _write(cfg_dir / "disciplines.yaml", {"a": {"name": "Альфа"}})
    assert discipline_color("a") == config.DEFAULT_COLOR
    assert load_config()["disciplines"]["a"]["aliases"] == []


# ---------- discipline_name / discipline_color ----------
def test_name_and_color():
    assert discipline_name("elektro") == "Электротехника"
    assert discipline_color("elektro") == "#4c78a8"
    assert discipline_name("models") == "Модели данных"


@pytest.mark.parametrize("fn", [discipline_name, discipline_color])
@pytest.mark.parametrize("key", ["nope", "", "ELEKTRO"])
def test_unknown_key(fn, key):
    with pytest.raises(KeyError, match="Неизвестная"):
        fn(key)


def test_edit_is_picked_up(cfg_dir):
    assert discipline_name("elektro") == "Электротехника"
    data = yaml.safe_load((cfg_dir / "disciplines.yaml").read_text(encoding="utf-8"))
    data["elektro"]["name"] = "Электротехника и электроника"
    _write(cfg_dir / "disciplines.yaml", data)
    assert discipline_name("elektro") == "Электротехника и электроника"


# ---------- find_discipline ----------
@pytest.mark.parametrize("text,expected", [
    ("Лаб.2 по электротехнике сдаём до пятницы", "elektro"),     # склонение
    ("Электротехнику перенесли на среду", "elektro"),            # винительный падеж
    ("ЭЛЕКТРОТЕХ в четверг", "elektro"),                         # регистр
    ("сдаём лабу по электре", "elektro"),                        # разговорный вариант
    ("Рубежка по электротехнике", "elektro"),
    ("ЭТ завтра", "elektro"),                                    # аббревиатура
    ("эт завтра", None),                                         # не аббревиатура
    ("Это ЭТО, а не ЭТ", "elektro"),
    ("ЭТА лаба", None),                                          # ЭТА не ЭТ
    ("Домашка по моделям данных", "models"),
    ("кто сделал БД?", "models"),
    ("МД в пятницу", "models"),
    ("алгосы сдавать", "algo"),
    ("АиСД: рубежка", "algo"),
    ("по алгоритмам и структурам данных", "algo"),
    ("всем привет", None),
    ("ахах 😂😂", None),
    ("", None),
    ("   ", None),
])
def test_find_discipline(text, expected):
    assert find_discipline(text) == expected


def test_most_mentions_wins():
    assert find_discipline("электра и модели данных") == "models"   # модели + «модели данных»


def test_tie_goes_to_first_mentioned():
    assert find_discipline("алгосы, потом электра") == "algo"
    assert find_discipline("электра, потом алгосы") == "elektro"


def test_long_text_and_emoji():
    text = "ахах " * 5000 + "сдаём электротехнику 😂"
    assert find_discipline(text) == "elektro"


def test_find_after_config_edit(cfg_dir):
    assert find_discipline("сдаём физику") is None
    data = yaml.safe_load((cfg_dir / "disciplines.yaml").read_text(encoding="utf-8"))
    data["phys"] = {"name": "Физика", "color": "#e45756", "aliases": ["физика"]}
    _write(cfg_dir / "disciplines.yaml", data)
    assert find_discipline("сдаём по физике") == "phys"
