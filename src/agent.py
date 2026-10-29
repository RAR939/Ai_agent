"""
Агентный цикл (Роль 5). Подключение к MCP-серверу и вызов модели Ollama.
Работает из любой папки: пути считаются от корня репозитория, настройки берутся из load_config().
"""
import asyncio
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import ollama
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.config import load_config
from src.schemas import AgentResult, ToolCall, SearchHit

MSK = timezone(timedelta(hours=3))
ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = ROOT / "config" / "prompts" / "agent_v1.txt"


def _log_trace(question: str, trace: list[ToolCall], answer: str, total_sec: float, model: str):
    logs = Path(load_config()["paths"]["logs"])
    logs = logs if logs.is_absolute() else ROOT / logs
    logs.mkdir(parents=True, exist_ok=True)
    log_entry = {
        "ts": datetime.now(MSK).isoformat(timespec='seconds'),
        "question": question,
        "trace": [t.model_dump() for t in trace],
        "answer": answer,
        "total_sec": round(total_sec, 2),
        "model": model
    }
    with open(logs / "agent_trace.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")


def _route_by_rules(question: str, rules: dict) -> str:
    """Определяет инструмент по ключевым словам (запасной режим)."""
    q = question.lower()
    for tool_name, keywords in rules.items():
        if any(kw in q for kw in keywords):
            return tool_name
    return "search_messages"  # По умолчанию


def _rules_args(tool_name: str, question: str) -> dict:
    """Простые аргументы для запасного режима (без участия модели)."""
    if tool_name == "search_messages":
        return {"query": question}
    if tool_name == "get_schedule":
        today = datetime.now(MSK).date()
        return {"date_from": today.isoformat(), "date_to": (today + timedelta(days=7)).isoformat()}
    return {}


def _pending_id(parsed) -> int | None:
    """id записи в очереди подтверждения, если инструмент вернул PendingItem."""
    if isinstance(parsed, dict) and {"candidate", "reason", "id"} <= parsed.keys():
        return parsed["id"]
    return None


async def run_agent(question: str, history: list[dict], deterministic: bool = False) -> AgentResult:
    start_total = time.time()

    config = load_config()
    max_steps = config["agent"]["max_steps"]
    timeout_sec = config["agent"]["timeout_sec"]
    model_name = config["models"]["llm"]
    temperature = 0.0 if deterministic else config["models"]["temperature"]
    agent_mode = config["agent"].get("mode", "llm")
    routing_rules = config["agent"].get("routing_rules", {})

    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "src.mcp_server"],
        cwd=str(ROOT),
    )

    trace: list[ToolCall] = []
    pending_ids: list[int] = []
    sources: list[SearchHit] = []
    final_text = ""

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = (await session.list_tools()).tools
            ollama_tools = [
                {
                    "type": "function",
                    "function": {"name": t.name, "description": t.description, "parameters": t.inputSchema}
                } for t in tools
            ]

            messages = [{"role": "system", "content": system_prompt}]
            messages.extend(history)
            messages.append({"role": "user", "content": question})

            # --- ЗАПАСНОЙ РЕЖИМ (RULES) ---
            if agent_mode == "rules":
                tool_name = _route_by_rules(question, routing_rules)
                print(f"[Роутер] Выбран инструмент: {tool_name}", file=sys.stderr)

                # Формируем аргументы (очень простые, чтобы не усложнять)
                args = _rules_args(tool_name, question)

                start_time = time.time()
                error = None
                result_text = ""
                try:
                    tool_result = await asyncio.wait_for(session.call_tool(tool_name, args), timeout=timeout_sec)
                    raw_text = tool_result.content[0].text if tool_result.content else ""
                    result_text = str(raw_text)
                except Exception as e:
                    error = str(e)

                duration = time.time() - start_time

                trace.append(
                    ToolCall(tool=tool_name, args=args, result_preview=result_text[:300], duration=round(duration, 2),
                             error=error))

                if not error:
                    messages.append({"role": "tool", "content": result_text[:3000], "tool_name": tool_name})
                    # Просим модель сформулировать ответ по результатам
                    messages.append({"role": "user",
                                     "content": "Сформулируй ответ на основе данных выше. Если данных нет, скажи 'В материалах этого нет'."})
                    try:
                        response = ollama.chat(model=model_name, messages=messages,
                                               options={"temperature": temperature})
                        final_text = response.message.content or ""
                    except Exception as e:
                        final_text = f"Ошибка при генерации ответа: {e}"
                else:
                    final_text = f"Ошибка инструмента: {error}"

            # --- ОБЫЧНЫЙ РЕЖИМ (LLM) ---
            else:
                steps = 0
                last_call_signature = None
                while steps < max_steps:
                    steps += 1
                    response = ollama.chat(model=model_name, messages=messages, tools=ollama_tools,
                                           options={"temperature": temperature})
                    msg = response.message

                    if not getattr(msg, "tool_calls", None):
                        final_text = msg.content or ""
                        break
                    messages.append(msg)

                    for tc in msg.tool_calls:
                        tool_name = tc.function.name
                        args = tc.function.arguments or {}

                        current_signature = f"{tool_name}:{json.dumps(args, sort_keys=True)}"
                        if current_signature == last_call_signature:
                            final_text = "Ошибка: агент зациклился."
                            break
                        last_call_signature = current_signature

                        start_time = time.time()
                        error = None
                        result_text = ""
                        try:
                            tool_result = await asyncio.wait_for(session.call_tool(tool_name, args),
                                                                 timeout=timeout_sec)
                            raw_text = tool_result.content[0].text if tool_result.content else ""
                            result_text = str(raw_text)
                        except Exception as e:
                            error = str(e)

                        duration = time.time() - start_time
                        model_result = result_text[:3000] if not error else json.dumps({"error": error})
                        result_preview = result_text[:300] if not error else error

                        trace.append(ToolCall(tool=tool_name, args=args, result_preview=result_preview,
                                              duration=round(duration, 2), error=error))

                        if not error:
                            try:
                                parsed = json.loads(result_text)
                                if tool_name == "search_messages" and isinstance(parsed, list):
                                    for item in parsed:
                                        sources.append(SearchHit.model_validate(item))
                                if (pid := _pending_id(parsed)) is not None:
                                    pending_ids.append(pid)
                            except Exception:
                                pass

                        messages.append({"role": "tool", "content": model_result, "tool_name": tool_name})

                    if "Ошибка: агент зациклился" in final_text:
                        break
                if not final_text:
                    final_text = "Не удалось получить ответ."

    total_sec = time.time() - start_total
    _log_trace(question, trace, final_text, total_sec, model_name)

    return AgentResult(text=final_text, sources=sources, trace=trace, pending_ids=pending_ids)


if __name__ == "__main__":
    user_question = sys.argv[1] if len(sys.argv) > 1 else "Что у меня горит на этой неделе?"
    print(f"Вопрос: {user_question}\n")
    try:
        res = asyncio.run(run_agent(user_question, history=[]))
        print(f"Ответ: {res.text}\n")
        print("Трасса вызовов:")
        for t in res.trace:
            print(f"  - {t.tool} -> {t.result_preview[:50]}...")
    except KeyboardInterrupt:
        print("\nПрервано.")