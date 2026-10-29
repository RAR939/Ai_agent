"""Проверка окружения перед запуском: python scripts/check_env.py

Показывает, что готово и чего не хватает (с подсказкой, как исправить). Код возврата 1,
если не работает что-то обязательное (Python, пакеты, конфиг, Ollama и её модели).
"""
import importlib.metadata as md
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MIN_PYTHON = (3, 11)


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    hint: str = ""
    critical: bool = True     # False: только предупреждение


def check_python() -> Check:
    have = sys.version_info[:3]
    ok = have >= MIN_PYTHON
    return Check("Python", ok, ".".join(map(str, have)), f"нужен Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} или новее")


def requirements() -> list[tuple[str, str]]:
    """(пакет, версия) из requirements.txt."""
    result = []
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9_.-]+)(?:\[[^\]]*\])?==([^\s#]+)", line.strip())
        if m:
            result.append((m.group(1), m.group(2)))
    return result


def check_packages() -> list[Check]:
    missing, other = [], []
    for name, wanted in requirements():
        try:
            have = md.version(name)
        except md.PackageNotFoundError:
            missing.append(name)
            continue
        if have != wanted:
            other.append(f"{name} {have} (в requirements {wanted})")
    checks = [Check("Пакеты", not missing, "все установлены" if not missing else "нет: " + ", ".join(missing),
                    "pip install -r requirements.txt")]
    if other:
        checks.append(Check("Версии пакетов", False, "; ".join(other), "pip install -r requirements.txt",
                            critical=False))
    return checks


def check_config() -> tuple[Check, dict | None]:
    try:
        from src.config import load_config
        cfg = load_config()
    except Exception as e:
        return Check("Конфиг", False, str(e), "проверьте config/*.yaml"), None
    return Check("Конфиг", True, f"дисциплин: {len(cfg['disciplines'])}, режим интерфейса: "
                                 f"{'макет' if cfg['ui'].get('use_mock', True) else 'настоящие данные'}"), cfg


def installed_models() -> list[str]:
    from src import llm
    return llm.list_models(timeout=5)


def check_ollama(cfg: dict) -> list[Check]:
    from src import llm
    where = llm.describe()
    started = time.monotonic()
    try:
        have = installed_models()
    except Exception as e:
        return [Check("Ollama", False, f"{where}: не отвечает ({type(e).__name__})",
                      "запустите Ollama; на сервере проверьте SSH-туннель или models.host/OLLAMA_HOST и токен "
                      "(docs/server_setup.md)")]
    ping = time.monotonic() - started
    checks = [Check("Ollama", True, f"{where}, моделей: {len(have)}, ответ за {ping:.2f} с")]
    if ping > 1.5:
        checks.append(Check("Связь с Ollama", False, f"медленно ({ping:.1f} с на простой запрос)",
                            "проверьте сеть и туннель: каждый запрос агента делает несколько обращений", critical=False))
    for role, name in (("LLM", cfg["models"]["llm"]), ("Эмбеддинги", cfg["models"]["embed"])):
        ok = any(m == name or m.split(":")[0] == name.split(":")[0] and ":" not in name for m in have)
        checks.append(Check(f"Модель {role}", ok, name if ok else f"{name} не скачана", f"ollama pull {name}"))
    return checks


def check_reranker(cfg: dict) -> Check | None:
    if not cfg["retrieval"].get("use_reranker", True):
        return None
    repo = cfg["models"]["reranker"].replace("/", "--")
    hub = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    ok = (hub / f"models--{repo}").exists()
    return Check("Реранкер", ok, cfg["models"]["reranker"] if ok else "ещё не скачан",
                 "скачается при первом поиске (нужен интернет один раз) или отключите retrieval.use_reranker",
                 critical=False)


def check_gpu(cfg: dict) -> Check | None:
    """Реранкер (torch) на GPU или на CPU. Не нужна, если реранкер выключен."""
    if not cfg["retrieval"].get("use_reranker", True):
        return None
    try:
        import torch
    except ImportError:
        return Check("GPU для реранкера", False, "torch не установлен", "pip install -r requirements.txt", critical=False)
    if torch.cuda.is_available():
        return Check("GPU для реранкера", True, torch.cuda.get_device_name(0))
    return Check("GPU для реранкера", False, "нет, реранкер считается на CPU (медленно)",
                 "на сервере с GPU поставьте torch с CUDA или отключите retrieval.use_reranker", critical=False)


def check_data(cfg: dict) -> list[Check]:
    clean = sorted((ROOT / cfg["paths"]["data"] / "clean").glob("*.jsonl"))
    checks = [Check("Данные чатов", bool(clean), ", ".join(p.stem for p in clean) if clean
                    else "нет data/clean/*.jsonl, используется синтетический мини-чат",
                    "положите обезличенные чаты в data/clean/<чат>.jsonl (роль 2)", critical=False)]
    chunks = ROOT / cfg["paths"]["data"] / "index_chunks.jsonl"
    n = sum(1 for _ in chunks.open(encoding="utf-8")) if chunks.exists() else 0
    checks.append(Check("Индекс поиска", n > 0, f"чанков: {n}" if n else "не построен",
                        "python -m src.index.build --chat <чат> (нужна Ollama с bge-m3)", critical=False))
    return checks


def check_database() -> list[Check]:
    try:
        from src.tracker import db
        deadlines, lessons = db.count_deadlines(), db.count_lessons()
    except Exception as e:
        return [Check("База дедлайнов", False, str(e), "проверьте paths.db в config.yaml")]
    return [Check("База дедлайнов", True, f"дедлайнов: {deadlines}"),
            Check("Расписание", lessons > 0, f"занятий: {lessons}" if lessons else "не загружено",
                  "вкладка «Расписание» в интерфейсе (.ics или .xlsx)", critical=False)]


def run_checks() -> list[Check]:
    checks = [check_python(), *check_packages()]
    config_check, cfg = check_config()
    checks.append(config_check)
    if cfg is None:
        return checks
    checks += check_ollama(cfg)
    if (reranker := check_reranker(cfg)) is not None:
        checks.append(reranker)
    if (gpu := check_gpu(cfg)) is not None:
        checks.append(gpu)
    checks += check_data(cfg)
    checks += check_database()
    return checks


def main() -> int:
    checks = run_checks()
    width = max(len(c.name) for c in checks)
    for c in checks:
        mark = "✓" if c.ok else ("✗" if c.critical else "!")
        line = f" {mark} {c.name.ljust(width)}  {c.detail}"
        print(line + (f"\n   {' ' * width}  → {c.hint}" if not c.ok and c.hint else ""))
    failed = [c for c in checks if not c.ok and c.critical]
    warned = [c for c in checks if not c.ok and not c.critical]
    print(f"\nГотово к запуску." if not failed else f"\nНе хватает обязательного: {', '.join(c.name for c in failed)}.")
    if warned:
        print(f"Предупреждений: {len(warned)} (работать можно, часть функций ограничена).")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
