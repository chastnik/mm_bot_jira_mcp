"""Клиент для подключения к локальной LLM (LM Studio)."""

import logging
from typing import Any, Optional

from openai import OpenAI

logger = logging.getLogger(__name__)


class LLMClient:
    """Клиент для работы с локальной LLM через OpenAI-совместимый API."""

    def __init__(
        self,
        api_url: str,
        api_key: Optional[str] = None,
        model: str = "local-model",
    ):
        """Инициализация LLM клиента.

        Args:
            api_url: URL API (например, http://localhost:1234/v1)
            api_key: API ключ (опционально)
            model: Название модели
        """
        self.api_url = api_url.rstrip("/")
        self.model = model
        self.client = OpenAI(
            base_url=self.api_url,
            api_key=api_key or "not-needed",
        )

    def chat(
        self,
        messages: list[dict[str, str]],
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        temperature: float = 0.7,
    ) -> dict[str, Any]:
        """Отправить запрос к LLM.

        Args:
            messages: Список сообщений в формате OpenAI
            tools: Список доступных инструментов (MCP tools)
            tool_choice: Стратегия выбора инструментов
            temperature: Температура генерации

        Returns:
            Ответ от LLM
        """
        try:
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
            }

            if tools:
                kwargs["tools"] = tools
                if tool_choice:
                    kwargs["tool_choice"] = tool_choice

            response = self.client.chat.completions.create(**kwargs)
            return {
                "content": response.choices[0].message.content,
                "tool_calls": (
                    [
                        {
                            "id": call.id,
                            "function": {
                                "name": call.function.name,
                                "arguments": call.function.arguments,
                            },
                        }
                        for call in response.choices[0].message.tool_calls or []
                    ]
                    if response.choices[0].message.tool_calls
                    else None
                ),
            }
        except Exception as e:
            logger.error(f"Ошибка при обращении к LLM: {e}")
            raise

    def format_mcp_tools_for_openai(
        self, mcp_tools: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Преобразовать MCP tools в формат OpenAI.

        Args:
            mcp_tools: Список инструментов MCP

        Returns:
            Список инструментов в формате OpenAI
        """
        openai_tools = []
        for tool in mcp_tools:
            openai_tool = {
                "type": "function",
                "function": {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("inputSchema", {}),
                },
            }
            openai_tools.append(openai_tool)
        return openai_tools

