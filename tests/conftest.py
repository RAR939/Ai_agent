"""Общие фикстуры тестов трекера (роль 4)."""
import copy

import pytest

from src import config
from src.schemas import AttachedFile, Deadline
from src.tracker import common, db


@pytest.fixture
def tdb():
    """Чистая база в памяти; после теста путь возвращается к конфигурации."""
    db.set_db_path(":memory:")
    db.init_db()
    yield db
    db.set_db_path(None)


@pytest.fixture
def set_cfg(monkeypatch):
    """set_cfg({"schedule": {...}}) накладывает правки на реальный конфиг (на один уровень)."""
    def apply(overrides: dict):
        base = copy.deepcopy(config.load_config())
        for section, values in overrides.items():
            if isinstance(values, dict):
                base.setdefault(section, {}).update(values)
            else:
                base[section] = values
        monkeypatch.setattr(common, "cfg", lambda: base)
        return base
    return apply


def make_file(msg_id="elektro:1", n=1, ext="pdf", bind=None, name=None) -> AttachedFile:
    return AttachedFile(id=f"{msg_id}:f{n}", msg_id=msg_id, name=name or f"file{n}.{ext}",
                        ext=ext, size_bytes=1000, path=f"files/file{n}.{ext}", bind=bind)


def make_deadline(**kw) -> Deadline:
    base = dict(discipline="elektro", kind="lab", task="Лаб.2",
                due_at="2026-10-23T23:59:00+03:00", due_text="до пятницы",
                source_msg="elektro:10", confidence=0.93)
    base.update(kw)
    return Deadline(**base)
