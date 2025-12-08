"""Клиент для подключения к корпоративной LLM."""

import json
import logging
import re
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)


class LLMClient:
    """Клиент для работы с корпоративной LLM через Ollama-like API."""

    def __init__(
        self,
        api_url: str,
        api_key: Optional[str] = None,
        model: str = "local-model",
    ):
        """Инициализация LLM клиента.

        Args:
            api_url: URL API (например, https://llm.example.com)
            api_key: API ключ (токен прокси)
            model: Название модели
        """
        self.api_url = api_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.headers = {
            "X-PROXY-AUTH": api_key or "",
            "Content-Type": "application/json",
        }

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
            # Если есть tools, добавляем их описание в системный промпт
            final_messages = self._inject_tools_into_messages(messages, tools)

            payload = {
                "model": self.model,
                "stream": False,
                "messages": final_messages,
                "options": {
                    "num_ctx": 16384,
                    "temperature": temperature,
                },
            }

            url = f"{self.api_url}/api/chat"
            logger.debug(f"Отправляю запрос к LLM: {url}, модель: {self.model}")

            response = requests.post(
                url,
                headers=self.headers,
                json=payload,
                timeout=120,
            )

            if response.status_code != 200:
                logger.error(f"Ошибка HTTP {response.status_code}: {response.text}")
                raise Exception(f"LLM API error: {response.status_code} - {response.text}")

            # Парсим streaming ответ (каждая строка - отдельный JSON)
            content = self._parse_response(response.text)

            # Парсим tool calls из ответа, если есть tools
            tool_calls = None
            if tools:
                tool_calls = self._extract_tool_calls(content, tools)

            # Очищаем контент от tool call блоков
            clean_content = self._clean_content(content)

            return {
                "content": clean_content,
                "tool_calls": tool_calls,
            }
        except Exception as e:
            logger.error(f"Ошибка при обращении к LLM: {e}")
            raise

    def _inject_tools_into_messages(
        self,
        messages: list[dict[str, str]],
        tools: Optional[list[dict[str, Any]]],
    ) -> list[dict[str, str]]:
        """Добавляет описание tools в системный промпт."""
        if not tools:
            return messages

        # Создаём описание инструментов
        tools_description = self._format_tools_for_prompt(tools)

        # Добавляем системное сообщение с описанием tools
        system_prompt = f"""Ты - помощник для работы с Jira и Confluence. ВСЕГДА отвечай на РУССКОМ языке.

У тебя есть доступ к следующим инструментам:

{tools_description}

Чтобы использовать инструмент, ответь в формате:
<tool_call>
{{"name": "имя_инструмента", "arguments": {{"параметр": "значение"}}}}
</tool_call>

После вызова инструмента подожди результат и затем ответь пользователю НА РУССКОМ ЯЗЫКЕ.
Если инструменты не нужны для ответа на вопрос, отвечай напрямую без tool_call.

ВАЖНО: Все твои ответы должны быть на русском языке!"""

        # Добавляем /no_think для qwen моделей
        result = [{"role": "system", "content": "/no_think"}]
        result.append({"role": "system", "content": system_prompt})

        # Добавляем остальные сообщения
        for msg in messages:
            if msg.get("role") != "system":
                result.append(msg)
            else:
                # Объединяем системные сообщения
                result[1]["content"] += "\n\n" + msg.get("content", "")

        return result

    def _format_tools_for_prompt(self, tools: list[dict[str, Any]]) -> str:
        """Форматирует список tools для промпта."""
        lines = []
        for tool in tools:
            func = tool.get("function", tool)
            name = func.get("name", "")
            description = func.get("description", "")
            parameters = func.get("parameters", {})

            params_str = ""
            if parameters.get("properties"):
                required = parameters.get("required", [])
                for param_name, param_info in parameters["properties"].items():
                    param_type = param_info.get("type", "string")
                    param_desc = param_info.get("description", "")
                    is_required = param_name in required
                    req_mark = " (обязательный)" if is_required else " (опциональный)"
                    params_str += f"\n    - {param_name}: {param_type}{req_mark} - {param_desc}"

            lines.append(f"**{name}**: {description}{params_str}")

        return "\n\n".join(lines)

    def _parse_response(self, response_text: str) -> str:
        """Парсит streaming ответ от Ollama API."""
        response_text = response_text.strip()
        if not response_text:
            return ""

        full_content = ""
        lines = response_text.split("\n")

        for line in lines:
            if line.strip():
                try:
                    line_data = json.loads(line)
                    message_content = line_data.get("message", {}).get("content", "")
                    if message_content:
                        full_content += message_content
                except json.JSONDecodeError:
                    continue

        # Очищаем от thinking-блоков
        full_content = re.sub(r"<think>.*?</think>", "", full_content, flags=re.DOTALL)
        full_content = re.sub(r"\n\s*\n\s*\n", "\n\n", full_content)

        return full_content.strip()

    def _extract_tool_calls(
        self, content: str, tools: list[dict[str, Any]]
    ) -> Optional[list[dict[str, Any]]]:
        """Извлекает tool calls из ответа LLM."""
        # Ищем блоки <tool_call>...</tool_call>
        pattern = r"<tool_call>\s*(\{.*?\})\s*</tool_call>"
        matches = re.findall(pattern, content, re.DOTALL)

        if not matches:
            return None

        tool_calls = []
        tool_names = {
            t.get("function", t).get("name", "") for t in tools
        }

        for i, match in enumerate(matches):
            try:
                call_data = json.loads(match)
                name = call_data.get("name", "")
                arguments = call_data.get("arguments", {})

                if name in tool_names:
                    tool_calls.append({
                        "id": f"call_{i}",
                        "function": {
                            "name": name,
                            "arguments": json.dumps(arguments, ensure_ascii=False),
                        },
                    })
            except json.JSONDecodeError:
                logger.warning(f"Не удалось распарсить tool_call: {match}")
                continue

        return tool_calls if tool_calls else None

    def _clean_content(self, content: str) -> str:
        """Удаляет tool_call блоки из контента."""
        content = re.sub(
            r"<tool_call>\s*\{.*?\}\s*</tool_call>",
            "",
            content,
            flags=re.DOTALL,
        )
        return content.strip()

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
