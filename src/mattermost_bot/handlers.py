"""Обработчики сообщений Mattermost."""

import asyncio
import json
import logging
from datetime import datetime
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
        # История сообщений для каждого пользователя (макс 10 последних обменов)
        self.conversation_history: dict[str, list[dict]] = {}

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
- `/help` или `помощь` - показать эту справку
- `/clear` или `сброс` - очистить историю беседы
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
        
        if message.lower() in ["/clear", "/reset", "сброс", "очистить"]:
            self.clear_conversation(mm_user_id)
            return "✅ История беседы очищена. Начинаем с чистого листа!"

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

            # Системный промпт
            system_message = {
                "role": "system",
                "content": (
                    "Ты помощник для работы с Jira и Confluence. "
                    "Используй доступные инструменты для выполнения запросов пользователя. "
                    "КРИТИЧЕСКИ ВАЖНО: ВСЕГДА отвечай ТОЛЬКО на РУССКОМ языке! "
                    "ВСЕ ответы, объяснения, анализ и комментарии ОБЯЗАТЕЛЬНО должны быть на РУССКОМ! "
                    "НИКОГДА не отвечай на английском! "
                    f"\n\nТЕКУЩАЯ ДАТА: {datetime.now().strftime('%Y-%m-%d')} (год {datetime.now().year}). "
                    "Если пользователь не указывает год, используй текущий год!"
                    "\n\nПОИСК ЗАДАЧ ПОЛЬЗОВАТЕЛЯ ПО ИМЕНИ: "
                    "Если нужно найти задачи пользователя по имени (например, 'Сергей Журавлев'), "
                    "выполни два шага:\n"
                    "1. Сначала вызови search_users с query='Журавлев' чтобы найти username пользователя\n"
                    "2. Затем используй найденный username в JQL или search_worklogs\n"
                    "НЕ используй оператор ~ с именем в поле assignee - он не работает!"
                    "\n\nКРИТИЧНО - НЕ ВЫДУМЫВАЙ ИНФОРМАЦИЮ: "
                    "НИКОГДА не выдумывай номера задач (PROJ-123), имена проектов, результаты запросов или любые другие данные! "
                    "Если запрос непонятен или слишком короткий (например, просто 'да' или 'ок'), "
                    "попроси пользователя уточнить, что именно он хочет сделать. "
                    "Всегда используй инструменты для получения реальных данных из Jira/Confluence!"
                    "\n\nАНАЛИЗ ДАННЫХ: Когда получаешь данные из инструментов, АНАЛИЗИРУЙ их и давай КРАТКИЙ ОТВЕТ на вопрос пользователя. "
                    "НЕ описывай структуру JSON, а извлеки из данных нужную информацию и представь её понятно."
                    "\n\nУ тебя есть доступ к истории беседы. Используй контекст предыдущих сообщений для понимания запросов."
                ),
            }
            
            # Получаем историю беседы для пользователя (максимум 10 последних обменов)
            history = self.conversation_history.get(mm_user_id, [])
            
            # Формируем сообщения для LLM: system + history + текущий запрос
            messages = [system_message]
            messages.extend(history)
            messages.append({"role": "user", "content": query})

            # Цикл для множественных итераций tool calls (макс 5 итераций)
            max_iterations = 5
            all_tool_results = []
            
            for iteration in range(max_iterations):
                logger.info(f"LLM итерация {iteration + 1}")
                
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
                            arguments = json.loads(tool_call["function"]["arguments"])
                            logger.info(f"Вызов инструмента {tool_name} с аргументами: {arguments}")
                            result = await self.mcp_client.call_tool(
                                tool_name, arguments, auth_headers, mm_user_id
                            )
                            # Форматируем результат
                            if isinstance(result, dict):
                                result_str = json.dumps(result, ensure_ascii=False, indent=2)
                            else:
                                result_str = str(result)
                            # Логируем результат (первые 500 символов)
                            logger.info(f"Результат инструмента {tool_name}: {result_str[:500]}...")
                            tool_results.append(
                                {
                                    "role": "tool",
                                    "content": result_str,
                                    "tool_call_id": tool_call["id"],
                                }
                            )
                            all_tool_results.append(result_str)
                        except Exception as e:
                            logger.error(f"Ошибка при вызове инструмента {tool_name}: {e}", exc_info=True)
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
                    # Преобразуем arguments из JSON строки в объект для Ollama API
                    converted_tool_calls = []
                    for tc in tool_calls:
                        converted_tc = {
                            "id": tc["id"],
                            "function": {
                                "name": tc["function"]["name"],
                                "arguments": json.loads(tc["function"]["arguments"]),
                            },
                        }
                        converted_tool_calls.append(converted_tc)
                    assistant_message["tool_calls"] = converted_tool_calls
                    messages.append(assistant_message)

                    # Добавляем результаты инструментов
                    messages.extend(tool_results)
                    
                    # Продолжаем цикл - LLM может захотеть вызвать ещё инструменты
                    continue
                else:
                    # LLM не хочет вызывать инструменты - возвращаем ответ
                    content = response.get("content")
                    if content and content.strip():
                        final_response = content
                    elif all_tool_results:
                        # Если есть результаты инструментов, но нет текстового ответа
                        final_response = f"Результаты выполнения:\n" + "\n---\n".join(
                            [r[:1000] for r in all_tool_results[-3:]]  # Последние 3 результата
                        )
                    else:
                        final_response = "Не удалось получить ответ от LLM"
                    
                    # Сохраняем историю беседы
                    self._save_conversation(mm_user_id, query, final_response)
                    return final_response
            
            # Если достигли лимита итераций
            logger.warning(f"Достигнут лимит итераций ({max_iterations})")
            if all_tool_results:
                final_response = f"Результаты выполнения (достигнут лимит запросов):\n" + "\n---\n".join(
                    [r[:1000] for r in all_tool_results[-3:]]
                )
            else:
                final_response = "Не удалось завершить запрос - слишком много итераций"
            
            self._save_conversation(mm_user_id, query, final_response)
            return final_response

        except Exception as e:
            logger.error(f"Ошибка при обработке запроса: {e}", exc_info=True)
            return f"Произошла ошибка при обработке запроса: {str(e)}"
    
    def _save_conversation(self, mm_user_id: str, user_message: str, assistant_response: str):
        """Сохранить обмен сообщениями в историю беседы.
        
        Args:
            mm_user_id: ID пользователя
            user_message: Сообщение пользователя
            assistant_response: Ответ ассистента
        """
        if mm_user_id not in self.conversation_history:
            self.conversation_history[mm_user_id] = []
        
        # Добавляем сообщение пользователя и ответ ассистента
        self.conversation_history[mm_user_id].append({"role": "user", "content": user_message})
        self.conversation_history[mm_user_id].append({"role": "assistant", "content": assistant_response})
        
        # Ограничиваем историю 20 сообщениями (10 обменов)
        max_history = 20
        if len(self.conversation_history[mm_user_id]) > max_history:
            self.conversation_history[mm_user_id] = self.conversation_history[mm_user_id][-max_history:]
    
    def clear_conversation(self, mm_user_id: str):
        """Очистить историю беседы для пользователя.
        
        Args:
            mm_user_id: ID пользователя
        """
        if mm_user_id in self.conversation_history:
            del self.conversation_history[mm_user_id]

