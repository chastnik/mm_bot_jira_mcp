"""Клиент для работы с встроенным MCP сервером."""

import asyncio
import logging
import os
import subprocess
import time
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


class MCPClient:
    """Клиент для взаимодействия с MCP сервером через HTTP."""

    def __init__(
        self,
        mcp_url: str = "http://localhost:8000/mcp",
        jira_url: str = "",
        confluence_url: Optional[str] = None,
    ):
        """Инициализация MCP клиента.

        Args:
            mcp_url: URL MCP сервера
            jira_url: URL Jira сервера (для базовой конфигурации)
            confluence_url: URL Confluence сервера (опционально)
        """
        self.mcp_url = mcp_url.rstrip("/")
        self.jira_url = jira_url
        self.confluence_url = confluence_url
        self.client = httpx.AsyncClient(timeout=30.0)
        self._server_process: Optional[subprocess.Popen] = None

    async def start_server(
        self, port: int = 8000, host: str = "127.0.0.1"
    ) -> None:
        """Запустить встроенный MCP сервер.

        Args:
            port: Порт для сервера
            host: Хост для сервера
        """
        if self._server_process is not None:
            logger.warning("MCP сервер уже запущен")
            return

        # Устанавливаем переменные окружения для MCP сервера
        env = os.environ.copy()
        env["JIRA_URL"] = self.jira_url
        if self.confluence_url:
            env["CONFLUENCE_URL"] = self.confluence_url
        env["TRANSPORT"] = "streamable-http"
        env["PORT"] = str(port)
        env["HOST"] = host
        env["MCP_LOGGING_STDOUT"] = "true"
        env["MCP_VERBOSE"] = "true"

        # Запускаем MCP сервер в отдельном процессе
        cmd = ["uv", "run", "mcp-atlassian"]
        self._server_process = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Ждем, пока сервер запустится
        max_attempts = 30
        for i in range(max_attempts):
            try:
                response = await self.client.get(f"http://{host}:{port}/healthz")
                if response.status_code == 200:
                    logger.info(f"MCP сервер запущен на http://{host}:{port}/mcp")
                    self.mcp_url = f"http://{host}:{port}/mcp"
                    return
            except Exception:
                pass
            await asyncio.sleep(1)

        raise RuntimeError("Не удалось запустить MCP сервер")

    async def stop_server(self) -> None:
        """Остановить MCP сервер."""
        if self._server_process:
            self._server_process.terminate()
            try:
                self._server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._server_process.kill()
            self._server_process = None
            logger.info("MCP сервер остановлен")

    async def list_tools(
        self, auth_headers: Optional[dict[str, str]] = None
    ) -> list[dict[str, Any]]:
        """Получить список доступных инструментов.

        Args:
            auth_headers: Заголовки авторизации для пользователя

        Returns:
            Список доступных инструментов
        """
        # Заголовки HTTP запроса
        headers = {"Content-Type": "application/json"}
        if auth_headers:
            headers.update(auth_headers)

        # MCP использует JSON-RPC протокол для запросов
        request_data = {
            "jsonrpc": "2.0",  # Версия протокола JSON-RPC
            "id": 1,  # Идентификатор запроса
            "method": "tools/list",  # Метод: получить список инструментов
            "params": {},  # Параметры запроса (пустые для списка инструментов)
        }

        try:
            response = await self.client.post(
                self.mcp_url, json=request_data, headers=headers
            )
            response.raise_for_status()
            result = response.json()
            if "result" in result and "tools" in result["result"]:
                return result["result"]["tools"]
            return []
        except Exception as e:
            logger.error(f"Ошибка при получении списка инструментов: {e}")
            return []

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        auth_headers: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """Вызвать инструмент MCP.

        Args:
            tool_name: Название инструмента
            arguments: Аргументы инструмента
            auth_headers: Заголовки авторизации для пользователя

        Returns:
            Результат выполнения инструмента
        """
        # Заголовки HTTP запроса
        headers = {"Content-Type": "application/json"}
        if auth_headers:
            headers.update(auth_headers)

        # Формируем JSON-RPC запрос на вызов инструмента
        request_data = {
            "jsonrpc": "2.0",  # Версия протокола JSON-RPC
            "id": 2,  # Идентификатор запроса
            "method": "tools/call",  # Метод: вызов инструмента
            "params": {"name": tool_name, "arguments": arguments},  # Параметры: название и аргументы инструмента
        }

        try:
            response = await self.client.post(
                self.mcp_url, json=request_data, headers=headers
            )
            response.raise_for_status()
            result = response.json()
            if "result" in result:
                return result["result"]
            elif "error" in result:
                raise RuntimeError(f"MCP ошибка: {result['error']}")
            return {}
        except Exception as e:
            logger.error(f"Ошибка при вызове инструмента {tool_name}: {e}")
            raise

    async def close(self) -> None:
        """Закрыть клиент и остановить сервер."""
        await self.stop_server()
        await self.client.aclose()

