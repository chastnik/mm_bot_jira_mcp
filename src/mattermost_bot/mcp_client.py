"""Клиент для работы с встроенным MCP сервером."""

import asyncio
import json
import logging
import os
import subprocess
import time
from typing import Any, Optional

import httpx
from mcp import ClientSession
from mcp.client.stdio import stdio_client

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
        self.jira_url = jira_url
        self.confluence_url = confluence_url
        self.client = httpx.AsyncClient(timeout=30.0)
        self._server_process: Optional[subprocess.Popen] = None
        self._mcp_session: Optional[ClientSession] = None
        self._mcp_client_context = None

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
        env["TRANSPORT"] = "stdio"
        env["MCP_LOGGING_STDOUT"] = "true"
        env["MCP_VERBOSE"] = "true"

        # Запускаем MCP сервер в отдельном процессе с stdio транспортом
        cmd = ["uv", "run", "mcp-atlassian"]
        self._server_process = subprocess.Popen(
            cmd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,  # Используем бинарный режим для stdio
        )

        # Инициализируем MCP сессию через stdio
        await self._init_mcp_session()
        logger.info("MCP сервер запущен с stdio транспортом")

    async def _init_mcp_session(self) -> None:
        """Инициализировать MCP сессию через stdio_client."""
        try:
            if not self._server_process or not self._server_process.stdin or not self._server_process.stdout:
                raise RuntimeError("MCP сервер не запущен или потоки недоступны")
            
            # Создаем stdio клиент как async context manager
            self._mcp_client_context = stdio_client(
                self._server_process.stdin,
                self._server_process.stdout,
            )
            
            # Входим в контекст
            read_stream, write_stream = await self._mcp_client_context.__aenter__()
            
            # Создаем сессию
            self._mcp_session = ClientSession(read_stream, write_stream)
            await self._mcp_session.__aenter__()
            
            # Инициализируем соединение
            await self._mcp_session.initialize()
            
            logger.info("MCP сессия инициализирована через stdio")
        except Exception as e:
            logger.error(f"Ошибка при инициализации MCP сессии: {e}")
            raise


    async def stop_server(self) -> None:
        """Остановить MCP сервер."""
        # Закрываем MCP сессию
        if self._mcp_session:
            try:
                await self._mcp_session.__aexit__(None, None, None)
            except Exception as e:
                logger.warning(f"Ошибка при закрытии MCP сессии: {e}")
            self._mcp_session = None
        
        # Закрываем streamable HTTP клиент
        if self._mcp_client_context:
            try:
                await self._mcp_client_context.__aexit__(None, None, None)
            except Exception as e:
                logger.warning(f"Ошибка при закрытии MCP клиента: {e}")
            self._mcp_client_context = None
        
        # Останавливаем процесс сервера
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
            auth_headers: Заголовки авторизации для пользователя (игнорируются для stdio транспорта,
                        авторизация происходит через переменные окружения процесса)

        Returns:
            Список доступных инструментов
        """
        if not self._mcp_session:
            logger.error("MCP сессия не инициализирована")
            return []

        try:
            # Используем MCP ClientSession для получения списка инструментов
            tools = await self._mcp_session.list_tools()
            
            # Преобразуем в формат, ожидаемый handlers
            result = []
            for tool in tools:
                result.append({
                    "name": tool.name,
                    "description": tool.description or "",
                    "inputSchema": tool.inputSchema.model_dump() if hasattr(tool.inputSchema, 'model_dump') else tool.inputSchema,
                })
            return result
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
            auth_headers: Заголовки авторизации для пользователя (игнорируются для stdio транспорта,
                        авторизация происходит через переменные окружения процесса)

        Returns:
            Результат выполнения инструмента
        """
        if not self._mcp_session:
            logger.error("MCP сессия не инициализирована")
            raise RuntimeError("MCP сессия не инициализирована")

        try:
            # Используем MCP ClientSession для вызова инструмента
            result = await self._mcp_session.call_tool(tool_name, arguments)
            return result
        except Exception as e:
            logger.error(f"Ошибка при вызове инструмента {tool_name}: {e}")
            raise

    async def close(self) -> None:
        """Закрыть клиент и остановить сервер."""
        await self.stop_server()
        await self.client.aclose()

