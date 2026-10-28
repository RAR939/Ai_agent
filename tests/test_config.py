"""Тесты словарей и конфига (задача 0.4): load_config, find_discipline."""
import pytest

from src import config


def test_load_config_has_all_parts():
    cfg = config.load_config()
    assert cfg["tracker"]["confidence_threshold"] == 0.7
    assert set(cfg["disciplines"]) >= {"elektro", "models"}
    assert cfg["roles"] == {}                    # roles.yaml в git не лежит


def test_names_and_colors():
    assert config.discipline_name("elektro") == "Электротехника"
    assert config.discipline_name("нет") == "нет"
    assert config.discipline_color("elektro").startswith("#")
    assert config.discipline_color("нет") == "#888888"


@pytest.mark.parametrize("text,key", [
    ("лаба по электротехнике", "elektro"), ("Электротех: сдать", "elektro"),
    ("сдаём ЭТ до пятницы", "elektro"), ("сегодня электра", "elektro"),
    ("ЛР по моделям данных", "models"), ("сдать бд", "models"), ("БД, лаба 1", "models"),
    ("база данных", "models"), ("elektro", "elektro"),
])
def test_find_discipline(text, key):
    assert config.find_discipline(text) == key


@pytest.mark.parametrize("text", ["", "привет", "это этот этап", "электрот", "бдительность"])
def test_find_discipline_none(text):
    assert config.find_discipline(text) is None           # короткие алиасы только целым словом


def test_tracker_settings_are_read_from_yaml_not_code():
    cfg = config.load_config()
    assert "сдавать" in cfg["tracker"]["prefilter_keywords"]
    assert cfg["schedule"]["semester_start"] == "2026-09-01"
