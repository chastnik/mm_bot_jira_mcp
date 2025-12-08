"""Обработчики сообщений Mattermost."""

import asyncio
import logging
from typing import Optional

from .auth_manager import AuthManager
from .llm_client import LLMClient
from .mcp_client import MCPClient
from .storage import Storage

logger = logging.getLogger(__name__)

# Состояния диалога для сбора учетных данных
DIALOG_STATE_NONE = "none"
DIALOG_STATE_WAITING_USERNAME = "waiting_username"
DIALOG_STATE_WAITING_PASSWORD = "waiting_password"


class MessageHandlers:
    """Обработчики сообщений от пользователей."""

    def __init__(
        self,
        storage: Storage,
        auth_manager: AuthManager,
        llm_client: LLMClient,
        mcp_client: MCPClient,
    ):
        """Инициализация обработчиков.

        Args:
            storage: Хранилище данных
            auth_manager: Менеджер аутентификации
            llm_client: LLM клиент
            mcp_client: MCP клиент
        """
        self.storage = storage
        self.auth_manager = auth_manager
        self.llm_client = llm_client
        self.mcp_client = mcp_client
        self.dialog_states: dict[str, str] = {}
        self.temp_data: dict[str, dict[str, str]] = {}

    def get_help_message(self) -> str:
        """Получить сообщение со справкой.

        Returns:
            Текст справки
        """
        return """Привет! Я бот для работы с Jira и Confluence.

**Как начать работу:**

1. Предоставьте свои учетные данные (логин и пароль от Jira, который также используется для Confluence)
2. После этого вы сможете задавать вопросы, связанные с Jira и Confluence

**Команды:**
- `/start` или любое сообщение - показать эту справку
- Для настройки учетных данных просто следуйте инструкциям бота

**Примеры запросов:**
- "Покажи мои открытые задачи в Jira"
- "Найди информацию о проекте PROJ в Confluence"
- "Создай задачу в Jira с названием 'Новая задача'"

**Безопасность:**
Ваши пароли хранятся в зашифрованном виде и используются только для выполнения ваших запросов.
Один пароль используется для доступа к обоим сервисам (Jira и Confluence)."""

    async def handle_message(
        self, mm_user_id: str, message: str
    ) -> str:
        """Обработать сообщение от пользователя.

        Args:
            mm_user_id: ID пользователя в Mattermost
            message: Текст сообщения

        Returns:
            Ответ бота
        """
        message = message.strip()

        # Проверяем состояние диалога
        state = self.dialog_states.get(mm_user_id, DIALOG_STATE_NONE)

        # Обработка команд
        if message.lower() in ["/start", "/help", "помощь", "справка"]:
            return self.get_help_message()

        # Обработка состояний диалога для сбора учетных данных
        if state != DIALOG_STATE_NONE:
            return await self._handle_dialog_state(mm_user_id, message, state)

        # Проверяем, есть ли у пользователя учетные данные
        has_jira = self.storage.has_jira_credentials(mm_user_id)

        if not has_jira:
            # Начинаем процесс регистрации
            return await self._start_registration(mm_user_id)

        # Обрабатываем обычный запрос через LLM + MCP
        return await self._handle_user_query(mm_user_id, message)

    async def _start_registration(self, mm_user_id: str) -> str:
        """Начать процесс регистрации пользователя.

        Args:
            mm_user_id: ID пользователя в Mattermost

        Returns:
            Сообщение с инструкциями
        """
        has_jira = self.storage.has_jira_credentials(mm_user_id)

        if not has_jira:
            self.dialog_states[mm_user_id] = DIALOG_STATE_WAITING_USERNAME
            self.temp_data[mm_user_id] = {}
            return (
                "Для начала работы необходимо настроить учетные данные.\n\n"
                "Введите ваш логин для Jira (он же используется для Confluence):"
            )

        return "Все учетные данные настроены! Теперь вы можете задавать вопросы."

    async def _handle_dialog_state(
        self, mm_user_id: str, message: str, state: str
    ) -> str:
        """Обработать состояние диалога.

        Args:
            mm_user_id: ID пользователя в Mattermost
            message: Сообщение пользователя
            state: Текущее состояние диалога

        Returns:
            Ответ бота
        """
        if state == DIALOG_STATE_WAITING_USERNAME:
            self.temp_data[mm_user_id]["username"] = message
            self.dialog_states[mm_user_id] = DIALOG_STATE_WAITING_PASSWORD
            return "Введите ваш пароль (используется для Jira и Confluence):"

        elif state == DIALOG_STATE_WAITING_PASSWORD:
            username = self.temp_data[mm_user_id]["username"]
            password = message
            # Сохраняем один пароль для обоих сервисов
            success, error = self.auth_manager.save_and_validate_both(
                mm_user_id, username, password
            )
            if success:
                self.dialog_states[mm_user_id] = DIALOG_STATE_NONE
                del self.temp_data[mm_user_id]
                services = []
                if self.auth_manager.jira_url:
                    services.append("Jira")
                if self.auth_manager.confluence_url:
                    services.append("Confluence")
                services_str = " и ".join(services)
                return (
                    f"✅ Учетные данные успешно настроены для {services_str}!\n\n"
                    "Теперь вы можете задавать вопросы, связанные с Jira и Confluence."
                )
            else:
                self.dialog_states[mm_user_id] = DIALOG_STATE_WAITING_USERNAME
                return (
                    f"❌ Ошибка при настройке учетных данных: {error}\n\n"
                    "Попробуйте еще раз. Введите ваш логин для Jira (он же используется для Confluence):"
                )

        return "Неизвестное состояние диалога. Начните заново с команды /start"

    async def _handle_user_query(
        self, mm_user_id: str, query: str
    ) -> str:
        """Обработать запрос пользователя через LLM и MCP.

        Args:
            mm_user_id: ID пользователя в Mattermost
            query: Запрос пользователя

        Returns:
            Ответ бота
        """
        try:
            # Получаем учетные данные пользователя
            creds = self.storage.get_user_credentials(mm_user_id)

            # Создаем заголовки авторизации для MCP
            # Для локального сервера используем Basic auth через username:password
            auth_headers = {}
            if creds["jira_username"] and creds["jira_password"]:
                # Для локального сервера передаем username:password через Basic Auth
                import base64

                credentials = f"{creds['jira_username']}:{creds['jira_password']}"
                encoded = base64.b64encode(credentials.encode()).decode()
                # Используем формат Basic для поддержки username:password
                auth_headers["Authorization"] = f"Basic {encoded}"

            # Примечание: для Confluence используем тот же подход, если нужно
            # В текущей реализации MCP сервер использует одну авторизацию для обоих сервисов

            # Получаем список доступных инструментов
            tools = await self.mcp_client.list_tools(auth_headers, mm_user_id)
            if not tools:
                return "Не удалось получить список инструментов MCP. Проверьте настройки сервера."

            # Форматируем инструменты для LLM
            openai_tools = self.llm_client.format_mcp_tools_for_openai(tools)

            # Формируем сообщения для LLM
            messages = [
                {
                    "role": "system",
                    "content": (
                        "Ты помощник для работы с Jira и Confluence. "
                        "Используй доступные инструменты для выполнения запросов пользователя. "
                        "Отвечай на русском языке."
                    ),
                },
                {"role": "user", "content": query},
            ]

            # Отправляем запрос к LLM
            response = await asyncio.to_thread(
                self.llm_client.chat,
                messages=messages,
                tools=openai_tools,
                tool_choice="auto",
            )

            # Если LLM хочет вызвать инструмент
            if response.get("tool_calls"):
                tool_calls = response["tool_calls"]
                tool_results = []

                for tool_call in tool_calls:
                    tool_name = tool_call["function"]["name"]
                    try:
                        import json

                        arguments = json.loads(tool_call["function"]["arguments"])
                        result = await self.mcp_client.call_tool(
                            tool_name, arguments, auth_headers, mm_user_id
                        )
                        # Форматируем результат
                        if isinstance(result, dict):
                            result_str = json.dumps(result, ensure_ascii=False, indent=2)
                        else:
                            result_str = str(result)
                        tool_results.append(
                            {
                                "role": "tool",
                                "content": result_str,
                                "tool_call_id": tool_call["id"],
                            }
                        )
                    except Exception as e:
                        logger.error(f"Ошибка при вызове инструмента {tool_name}: {e}")
                        tool_results.append(
                            {
                                "role": "tool",
                                "content": f"Ошибка: {str(e)}",
                                "tool_call_id": tool_call["id"],
                            }
                        )

                # Добавляем ответ ассистента с tool calls
                assistant_message = {
                    "role": "assistant",
                    "content": response.get("content"),
                }
                if tool_calls:
                    assistant_message["tool_calls"] = tool_calls
                messages.append(assistant_message)

                # Добавляем результаты инструментов
                messages.extend(tool_results)

                # Получаем финальный ответ
                final_response = await asyncio.to_thread(
                    self.llm_client.chat, messages=messages, tools=openai_tools
                )
                return final_response.get("content", "Не удалось получить ответ")
            else:
                return response.get("content", "Не удалось получить ответ")

        except Exception as e:
            logger.error(f"Ошибка при обработке запроса: {e}", exc_info=True)
            return f"Произошла ошибка при обработке запроса: {str(e)}"

