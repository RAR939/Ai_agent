"""Документация не устаревает: ссылки, пути, команды, настройки и переменные окружения сверяются с кодом."""
import pathlib
import re

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
# документы, за актуальность которых отвечает этот набор (документы ролей и отчёты проверяются только на ссылки в оглавлении)
CHECKED = ["README.md", "docs/README.md", "docs/user_guide.md", "docs/architecture.md", "docs/configuration.md",
           "docs/operations.md", "docs/known_issues.md", "docs/server_setup.md", "docs/CONTRIBUTING.md",
           "docs/annotation_guide.md", "docs/mcp_tools.md", "docs/ui_notes.md"]
ROOTS = ("docs/", "src/", "config/", "tests/", "eval/", "scripts/", "ui/", "deploy/", "data/", "logs/", ".streamlit/")
# пути, которых в репозитории нет по смыслу (создаются при работе, локальные или пример)
RUNTIME = ("data/", "logs/", "config/config.local.yaml", "config/roles.local.yaml", "docs/model_decision.md",
           "docs/article_notes.md", "docs/role_", "eval/gold_deadlines.jsonl", "docs/schedule_template.xlsx",
           "src/index/data", "tests/fixtures/mini_chat/files/")


STANDARD = {"venv", "pip"}                 # модули стандартной поставки
NOT_WRITTEN_YET = {"eval.evaluate"}          # в документах названа как пустая (docs/known_issues.md)


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def backticks(path: str) -> list[str]:
    return re.findall(r"`([^`\n]+)`", text(path))


def test_every_document_is_in_the_index():
    index = text("docs/README.md")
    for doc in sorted(DOCS.glob("*.md")):
        if doc.name != "README.md":
            assert f"({doc.name})" in index, f"{doc.name} нет в docs/README.md"


@pytest.mark.parametrize("path", CHECKED)
def test_markdown_links_resolve(path):
    base = (ROOT / path).parent
    for target in re.findall(r"\]\(([^)\s]+)\)", text(path)):
        if target.startswith(("http", "#", "mailto")):
            continue
        assert (base / target.split("#")[0]).exists(), f"{path}: ссылка {target} не найдена"


@pytest.mark.parametrize("path", CHECKED)
def test_paths_in_backticks_exist(path):
    missing = []
    for item in backticks(path):
        token = item.split()[0] if item.split() else item
        if not token.startswith(ROOTS) or any(c in token for c in "<>*{}…") or token.endswith(("/", ":")):
            continue
        token = token.rstrip(",.;")
        if token.startswith(RUNTIME) or "(" in token:
            continue
        if not (ROOT / token).exists():
            missing.append(token)
    assert not missing, f"{path}: нет файлов {sorted(set(missing))}"


@pytest.mark.parametrize("path", CHECKED)
def test_python_m_commands_point_to_runnable_modules(path):
    for item in backticks(path) + re.findall(r"^\s*(?:\$ )?(python -m [^\n#]+)", text(path), flags=re.M):
        m = re.search(r"python -m ([\w.]+)", item)
        if not m or m.group(1) in STANDARD or m.group(1) in NOT_WRITTEN_YET:
            continue
        file = ROOT / (m.group(1).replace(".", "/") + ".py")
        assert file.exists(), f"{path}: нет модуля {m.group(1)}"
        assert '__name__' in file.read_text(encoding="utf-8") and '"__main__"' in file.read_text(encoding="utf-8").replace("'", '"'), \
            f"{path}: у {m.group(1)} нет запуска как программы"


def config_keys() -> set[str]:
    cfg = yaml.safe_load((ROOT / "config" / "config.yaml").read_text(encoding="utf-8"))
    return {f"{section}.{key}" for section, values in cfg.items() for key in values}


def test_every_config_key_is_documented():
    doc = text("docs/configuration.md")
    missing = [k for k in sorted(config_keys()) if f"`{k}`" not in doc and not _documented_in_pair(k, doc)]
    assert not missing, f"в configuration.md нет ключей: {missing}"


def _documented_in_pair(key: str, doc: str) -> bool:
    """Строки вида «`retrieval.window_size` / `window_step`» описывают два ключа сразу."""
    section, name = key.split(".")
    return bool(re.search(rf"`{section}\.\w+`[^|\n]*`{name}`", doc))


def test_documented_config_keys_exist():
    known = config_keys()
    sections = {k.split(".")[0] for k in known}
    found = set(re.findall(rf"`((?:{'|'.join(sections)})\.\w+)`", text("docs/configuration.md")))
    assert not found - known, f"в документе есть несуществующие ключи: {sorted(found - known)}"


ENV_VARS = ["OLLAMA_HOST", "OLLAMA_API_KEY", "HELPER_DB", "HELPER_UI_PASSWORD", "HF_HOME"]


@pytest.mark.parametrize("name", ENV_VARS)
def test_environment_variables_are_documented_and_used(name):
    assert f"`{name}`" in text("docs/configuration.md")
    code = "".join(p.read_text(encoding="utf-8") for folder in ("src", "ui", "scripts") for p in (ROOT / folder).rglob("*.py"))
    assert name in code, f"{name} описана, но в коде не используется"


def test_prompt_files_listed_in_configuration_exist():
    for name in ("agent_v1", "agent_v2", "extract_v1", "answer_v1"):
        assert (ROOT / "config" / "prompts" / f"{name}.txt").exists() and name in text("docs/configuration.md")


def test_tool_names_in_mcp_doc_match_server():
    from src import mcp_server
    tools = {n for n, f in vars(mcp_server).items() if callable(f) and getattr(f, "__module__", "") == "src.mcp_server"
             and not n.startswith("_")}
    doc = text("docs/mcp_tools.md")
    assert tools and all(f"`{t}`" in doc for t in tools), sorted(t for t in tools if f"`{t}`" not in doc)


def test_not_written_yet_modules_are_really_empty():
    """Если eval.evaluate появится, уберите его из NOT_WRITTEN_YET и из списка «не сделано»."""
    body = (ROOT / "eval" / "evaluate.py").read_text(encoding="utf-8")
    assert "__main__" not in body and "пуст" in text("docs/known_issues.md")
