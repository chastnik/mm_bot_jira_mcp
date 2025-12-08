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
from mcp.client.streamable_http import streamablehttp_client

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
        self._mcp_url: Optional[str] = None
        # Сессии для каждого пользователя (ключ - mm_user_id)
        self._user_sessions: dict[str, ClientSession] = {}
        self._user_contexts: dict[str, Any] = {}

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
        # Перенаправляем stdout/stderr в файлы для отладки
        log_dir = os.path.expanduser("~/.mcp_atlassian_logs")
        os.makedirs(log_dir, exist_ok=True)
        stdout_file = open(f"{log_dir}/mcp_server_stdout.log", "a")
        stderr_file = open(f"{log_dir}/mcp_server_stderr.log", "a")
        self._server_process = subprocess.Popen(
            cmd,
            env=env,
            stdout=stdout_file,
            stderr=stderr_file,
        )

        # Ждем, пока сервер запустится
        max_attempts = 30
        for i in range(max_attempts):
            try:
                response = await self.client.get(f"http://{host}:{port}/healthz")
                if response.status_code == 200:
                    logger.info(f"MCP сервер запущен на http://{host}:{port}/mcp")
                    self._mcp_url = f"http://{host}:{port}/mcp"
                    return
            except Exception:
                pass
            await asyncio.sleep(1)

        raise RuntimeError("Не удалось запустить MCP сервер")


    async def _get_or_create_session(
        self, mm_user_id: str, auth_headers: Optional[dict[str, str]] = None
    ) -> ClientSession:
        """Получить или создать MCP сессию для пользователя."""
        if mm_user_id in self._user_sessions:
            return self._user_sessions[mm_user_id]
        
        if not self._mcp_url:
            raise RuntimeError("MCP сервер не запущен")
        
        try:
            # Создаем streamable HTTP клиент с заголовками авторизации пользователя
            headers = auth_headers or {}
            logger.info(f"Создание MCP сессии для пользователя {mm_user_id} с заголовками: {list(headers.keys())}")
            if "Authorization" in headers:
                # Маскируем токен для логирования
                auth_header = headers["Authorization"]
                masked = auth_header[:10] + "..." + auth_header[-10:] if len(auth_header) > 20 else "***"
                logger.info(f"Authorization заголовок: {masked}")
            else:
                logger.warning(f"Authorization заголовок отсутствует для пользователя {mm_user_id}")
            context = streamablehttp_client(self._mcp_url, headers=headers)
            
            # Входим в контекст
            logger.info(f"Вход в streamablehttp_client контекст для {mm_user_id}")
            read_stream, write_stream, _ = await context.__aenter__()
            logger.info(f"Контекст streamablehttp_client открыт для {mm_user_id}")
            
            # Создаем сессию
            logger.info(f"Создание ClientSession для {mm_user_id}")
            session = ClientSession(read_stream, write_stream)
            await session.__aenter__()
            logger.info(f"ClientSession открыт для {mm_user_id}")
            
            # Инициализируем соединение
            logger.info(f"Инициализация MCP сессии для {mm_user_id}")
            try:
                await session.initialize()
                logger.info(f"MCP сессия инициализирована для {mm_user_id}")
            except Exception as init_error:
                logger.error(f"Ошибка при инициализации MCP сессии для {mm_user_id}: {init_error}", exc_info=True)
                raise
            
            # Сохраняем сессию и контекст
            self._user_sessions[mm_user_id] = session
            self._user_contexts[mm_user_id] = context
            
            logger.info(f"MCP сессия создана для пользователя {mm_user_id}")
            return session
        except Exception as e:
            logger.error(f"Ошибка при создании MCP сессии для пользователя {mm_user_id}: {e}")
            raise

    async def stop_server(self) -> None:
        """Остановить MCP сервер."""
        # Закрываем все пользовательские сессии
        for mm_user_id, session in list(self._user_sessions.items()):
            try:
                await session.__aexit__(None, None, None)
            except Exception as e:
                logger.warning(f"Ошибка при закрытии MCP сессии для {mm_user_id}: {e}")
        
        for mm_user_id, context in list(self._user_contexts.items()):
            try:
                await context.__aexit__(None, None, None)
            except Exception as e:
                logger.warning(f"Ошибка при закрытии MCP контекста для {mm_user_id}: {e}")
        
        self._user_sessions.clear()
        self._user_contexts.clear()
        
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
        self, auth_headers: Optional[dict[str, str]] = None, mm_user_id: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Получить список доступных инструментов.

        Args:
            auth_headers: Заголовки авторизации для пользователя
            mm_user_id: ID пользователя в Mattermost (для создания сессии)

        Returns:
            Список доступных инструментов
        """
        if not mm_user_id:
            logger.error("mm_user_id не указан для list_tools")
            return []

        try:
            # Получаем или создаем сессию для пользователя
            session = await self._get_or_create_session(mm_user_id, auth_headers)
            
            # Используем MCP ClientSession для получения списка инструментов
            # list_tools() возвращает ListToolsResult (Pydantic модель) с полем tools
            list_tools_result = await session.list_tools()
            
            logger.debug(f"list_tools_result type: {type(list_tools_result)}")
            logger.debug(f"list_tools_result: {list_tools_result}")
            
            # Извлекаем список инструментов из результата
            # ListToolsResult имеет поле tools (список объектов Tool)
            if hasattr(list_tools_result, 'tools'):
                tools = list_tools_result.tools
                logger.debug(f"Извлечено {len(tools) if tools else 0} инструментов из list_tools_result.tools")
            elif isinstance(list_tools_result, tuple):
                # Если это кортеж, берем первый элемент (список инструментов)
                tools = list_tools_result[0] if list_tools_result else []
                logger.debug(f"Извлечено {len(tools) if tools else 0} инструментов из кортежа")
            elif isinstance(list_tools_result, list):
                # Если это уже список, используем его
                tools = list_tools_result
                logger.debug(f"Использован список напрямую, {len(tools)} инструментов")
            else:
                logger.error(f"Неожиданный тип результата list_tools: {type(list_tools_result)}, значение: {list_tools_result}")
                logger.error(f"Атрибуты list_tools_result: {dir(list_tools_result)}")
                return []
            
            if not tools:
                logger.warning("Список инструментов пуст")
                return []
            
            # Преобразуем в формат, ожидаемый handlers
            result = []
            for tool in tools:
                # Проверяем, что tool - это объект с атрибутом name
                if hasattr(tool, 'name'):
                    result.append({
                        "name": tool.name,
                        "description": getattr(tool, 'description', '') or "",
                        "inputSchema": tool.inputSchema.model_dump() if hasattr(tool.inputSchema, 'model_dump') else (tool.inputSchema if hasattr(tool, 'inputSchema') else {}),
                    })
                else:
                    logger.warning(f"Инструмент не имеет атрибута name: {type(tool)}, {tool}")
            
            logger.debug(f"Преобразовано {len(result)} инструментов в формат для handlers")
            return result
        except Exception as e:
            logger.error(f"Ошибка при получении списка инструментов: {e}", exc_info=True)
            return []

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        auth_headers: Optional[dict[str, str]] = None,
        mm_user_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Вызвать инструмент MCP.

        Args:
            tool_name: Название инструмента
            arguments: Аргументы инструмента
            auth_headers: Заголовки авторизации для пользователя
            mm_user_id: ID пользователя в Mattermost (для создания сессии)

        Returns:
            Результат выполнения инструмента
        """
        if not mm_user_id:
            raise RuntimeError("mm_user_id не указан для call_tool")

        try:
            # Получаем или создаем сессию для пользователя
            session = await self._get_or_create_session(mm_user_id, auth_headers)
            
            # Используем MCP ClientSession для вызова инструмента
            result = await session.call_tool(tool_name, arguments)
            return result
        except Exception as e:
            logger.error(f"Ошибка при вызове инструмента {tool_name}: {e}")
            raise

    async def close(self) -> None:
        """Закрыть клиент и остановить сервер."""
        await self.stop_server()
        await self.client.aclose()

