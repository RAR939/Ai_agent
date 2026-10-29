"""Загрузка конфигов и справочник дисциплин (docs/contracts.md, раздел 4).

load_config() собирает config.yaml, disciplines.yaml и roles.yaml в один словарь:
ключи config.yaml как есть, плюс "disciplines" и "roles". Если рядом есть
roles.local.yaml (реальные имена, не в git), он используется вместо roles.yaml.
"""
import re
from functools import lru_cache
from pathlib import Path

import pymorphy3
import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"

REQUIRED_SECTIONS = ("models", "retrieval", "tracker", "schedule", "agent", "ui", "paths")
DEFAULT_COLOR = "#888888"
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_WORD_RE = re.compile(r"[\w]+")

_morph = pymorphy3.MorphAnalyzer()


def _read_yaml(path: Path):
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Не найден файл конфигурации: {path}") from None
    except yaml.YAMLError as e:
        raise ValueError(f"Ошибка в {path.name}: {e}") from e


def _roles_path() -> Path:
    local = CONFIG_DIR / "roles.local.yaml"
    return local if local.exists() else CONFIG_DIR / "roles.yaml"


def _check_disciplines(raw) -> dict[str, dict]:
    """Проверяет disciplines.yaml и подставляет цвет по умолчанию."""
    if not isinstance(raw, dict) or not raw:
        raise ValueError("disciplines.yaml: нужен непустой словарь «ключ: описание»")
    result: dict[str, dict] = {}
    seen: dict[str, str] = {}   # алиас (нижний регистр) -> ключ
    for key, item in raw.items():
        if not isinstance(key, str) or not _KEY_RE.match(key):
            raise ValueError(f"disciplines.yaml: ключ {key!r} должен быть латиницей, например elektro")
        if not isinstance(item, dict) or not item.get("name"):
            raise ValueError(f"disciplines.yaml: у {key} нет поля name")
        color = item.get("color") or DEFAULT_COLOR
        if not isinstance(color, str) or not _COLOR_RE.match(color):
            raise ValueError(f"disciplines.yaml: у {key} цвет {color!r} не вида #rrggbb")
        aliases = item.get("aliases") or []
        if not isinstance(aliases, list) or not all(isinstance(a, str) and a.strip() for a in aliases):
            raise ValueError(f"disciplines.yaml: aliases у {key} должен быть списком непустых строк")
        for a in aliases:
            other = seen.setdefault(a.strip().lower(), key)
            if other != key:
                raise ValueError(f"disciplines.yaml: алиас {a!r} повторяется у {other} и {key}")
        result[key] = {"name": item["name"], "color": color, "aliases": [a.strip() for a in aliases]}
    return result


def load_config() -> dict:
    """config.yaml + disciplines.yaml + roles.yaml одним словарём."""
    cfg = _read_yaml(CONFIG_DIR / "config.yaml")
    if not isinstance(cfg, dict):
        raise ValueError("config.yaml: нужен словарь с разделами")
    missing = [s for s in REQUIRED_SECTIONS if not isinstance(cfg.get(s), dict)]
    if missing:
        raise ValueError(f"config.yaml: нет разделов {', '.join(missing)}")
    if "disciplines" in cfg or "roles" in cfg:
        raise ValueError("config.yaml: ключи disciplines и roles зарезервированы")
    cfg["disciplines"] = _check_disciplines(_read_yaml(CONFIG_DIR / "disciplines.yaml"))
    roles = _read_yaml(_roles_path())
    if not isinstance(roles, dict):
        raise ValueError("roles.yaml: нужен словарь")
    cfg["roles"] = roles
    return cfg


def _disciplines() -> dict[str, dict]:
    path = CONFIG_DIR / "disciplines.yaml"
    return _disciplines_cached(str(path), path.stat().st_mtime_ns)


@lru_cache(maxsize=8)
def _disciplines_cached(path: str, mtime_ns: int) -> dict[str, dict]:
    # mtime в ключе: правка файла подхватывается без перезапуска
    return _check_disciplines(_read_yaml(Path(path)))


def discipline_name(key: str) -> str:
    """"elektro" -> "Электротехника". Неизвестный ключ возвращается как есть (для показа в интерфейсе)."""
    item = _disciplines().get(key)
    return item["name"] if item else key


def discipline_color(key: str) -> str:
    """"elektro" -> "#4c78a8". Для неизвестного ключа серый цвет по умолчанию."""
    item = _disciplines().get(key)
    return item["color"] if item else DEFAULT_COLOR


# ---------- поиск дисциплины в тексте ----------
def _lemmas(word: str) -> frozenset[str]:
    """Возможные начальные формы слова (до 3 разборов pymorphy3), нижний регистр."""
    return frozenset(p.normal_form for p in _morph.parse(word.lower())[:3])


def _is_abbr(alias: str) -> bool:
    """Аббревиатура: одно слово из заглавных букв (ЭТ, МД): ищется только в таком же регистре."""
    return len(alias) >= 2 and alias.isalpha() and alias.isupper()


@lru_cache(maxsize=8)
def _matcher(key: tuple) -> tuple:
    """Подготовленные алиасы: (ключ, аббревиатуры, фразы из множеств лемм). key только для кэша."""
    abbrs: dict[str, str] = {}
    phrases: list[tuple[str, tuple[frozenset[str], ...]]] = []
    for dkey, item in _disciplines().items():
        for alias in item["aliases"] + [item["name"], dkey]:
            if _is_abbr(alias):
                abbrs[alias] = dkey
            else:
                words = _WORD_RE.findall(alias)
                if words:
                    phrases.append((dkey, tuple(_lemmas(w) for w in words)))
    return abbrs, phrases


def find_discipline(text: str) -> str | None:
    """Ключ дисциплины по алиасам в тексте или None.

    Склонения учитываются через леммы ("по электротехнике" -> elektro), обычные
    алиасы без учёта регистра, аббревиатуры (ЭТ) только заглавными. Ключ дисциплины и её
    название тоже считаются алиасами. Если найдено
    несколько дисциплин, выигрывает та, у которой больше совпадений, затем та,
    что упомянута раньше.
    """
    if not text or not text.strip():
        return None
    path = CONFIG_DIR / "disciplines.yaml"
    abbrs, phrases = _matcher((str(path), path.stat().st_mtime_ns))
    tokens = _WORD_RE.findall(text)
    token_lemmas = [_lemmas(t) for t in tokens]
    score: dict[str, int] = {}
    first: dict[str, int] = {}

    def hit(dkey: str, pos: int) -> None:
        score[dkey] = score.get(dkey, 0) + 1
        first.setdefault(dkey, pos)

    for i, tok in enumerate(tokens):
        if tok in abbrs:
            hit(abbrs[tok], i)
    for dkey, parts in phrases:
        n = len(parts)
        for i in range(len(tokens) - n + 1):
            if all(token_lemmas[i + j] & parts[j] for j in range(n)):
                hit(dkey, i)
    if not score:
        return None
    return min(score, key=lambda k: (-score[k], first[k]))
