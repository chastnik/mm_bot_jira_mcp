"""Конфигурация бота."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass
class BotConfig:
    """Конфигурация Mattermost бота."""

    # Mattermost настройки (обязательные)
    mattermost_url: str
    mattermost_token: str

    # LLM настройки (обязательные)
    llm_api_url: str

    # Jira/Confluence настройки (обязательные)
    jira_url: str

    # Mattermost настройки (опциональные)
    mattermost_team: str | None = None

    # LLM настройки (опциональные)
    llm_api_key: str | None = None
    llm_model: str = "local-model"

    # Jira/Confluence настройки (опциональные)
    confluence_url: str | None = None

    # База данных (опциональные)
    database_path: str = "bot_data.db"

    # Шифрование (опциональные)
    encryption_key: str | None = None

    # MCP сервер настройки (опциональные)
    mcp_port: int = 8000
    mcp_host: str = "127.0.0.1"

    @classmethod
    def from_env(cls) -> "BotConfig":
        """Создать конфигурацию из переменных окружения.

        Returns:
            BotConfig: Конфигурация бота

        Raises:
            ValueError: Если отсутствуют обязательные переменные окружения
        """
        mattermost_url = os.getenv("MATTERMOST_URL")
        if not mattermost_url:
            raise ValueError("MATTERMOST_URL не установлен")

        mattermost_token = os.getenv("MATTERMOST_TOKEN")
        if not mattermost_token:
            raise ValueError("MATTERMOST_TOKEN не установлен")

        llm_api_url = os.getenv("LLM_BASE_URL")
        if not llm_api_url:
            raise ValueError("LLM_BASE_URL не установлен")

        jira_url = os.getenv("JIRA_URL")
        if not jira_url:
            raise ValueError("JIRA_URL не установлен")

        # Парсим PORT из окружения (по умолчанию 8000)
        # Используем PORT вместо MCP_PORT для совместимости с MCP сервером
        port_str = os.getenv("PORT", "8000")
        try:
            mcp_port = int(port_str)
        except ValueError:
            raise ValueError(f"PORT должен быть числом, получено: {port_str}")

        # Для бота используем 127.0.0.1 по умолчанию (безопаснее для локального запуска)
        # Если HOST не указан, используем 127.0.0.1 вместо 0.0.0.0
        mcp_host = os.getenv("HOST", "127.0.0.1")

        return cls(
            mattermost_url=mattermost_url,
            mattermost_token=mattermost_token,
            mattermost_team=os.getenv("MATTERMOST_TEAM"),
            llm_api_url=llm_api_url,
            llm_api_key=os.getenv("LLM_PROXY_TOKEN"),
            llm_model=os.getenv("LLM_MODEL", "local-model"),
            jira_url=jira_url,
            confluence_url=os.getenv("CONFLUENCE_URL"),
            database_path=os.getenv("DATABASE_PATH", "bot_data.db"),
            encryption_key=os.getenv("ENCRYPTION_KEY"),
            mcp_port=mcp_port,
            mcp_host=mcp_host,
        )

