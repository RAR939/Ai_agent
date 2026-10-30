# path/to/test_mcp_connection.py
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    # Параметры запуска сервера: команда python и путь к скрипту
    params = StdioServerParameters(
        command="python",
        args=["src/mcp_server.py"],
    )

    print("Запуск MCP-сервера через stdio...")
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Запрашиваем список инструментов
            tools = await session.list_tools()
            print(f"Успешно! Сервер вернул {len(tools.tools)} инструментов:")
            for t in tools.tools:
                print(f" - {t.name}: {t.description[:50]}...")

            # (Опционально) Вызовем один инструмент для проверки
            print("\nПроверка вызова инструмента list_deadlines...")
            result = await session.call_tool("list_deadlines", {"discipline": "elektro"})
            print(f"Результат: {result.content[0].text[:200]}...")


if __name__ == "__main__":
    
    asyncio.run(main())
