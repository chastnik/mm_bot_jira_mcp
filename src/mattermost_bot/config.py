"""Конфигурация бота."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass
class BotConfig:
    """Конфигурация Mattermost бота."""

    # Mattermost настройки
    mattermost_url: str
    mattermost_token: str
    mattermost_team: str | None = None

    # LLM настройки
    llm_api_url: str
    llm_api_key: str | None = None
    llm_model: str = "local-model"

    # Jira/Confluence настройки
    jira_url: str
    confluence_url: str | None = None

    # База данных
    database_path: str = "bot_data.db"

    # Шифрование
    encryption_key: str | None = None

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

        llm_api_url = os.getenv("LLM_API_URL")
        if not llm_api_url:
            raise ValueError("LLM_API_URL не установлен")

        jira_url = os.getenv("JIRA_URL")
        if not jira_url:
            raise ValueError("JIRA_URL не установлен")

        return cls(
            mattermost_url=mattermost_url,
            mattermost_token=mattermost_token,
            mattermost_team=os.getenv("MATTERMOST_TEAM"),
            llm_api_url=llm_api_url,
            llm_api_key=os.getenv("LLM_API_KEY"),
            llm_model=os.getenv("LLM_MODEL", "local-model"),
            jira_url=jira_url,
            confluence_url=os.getenv("CONFLUENCE_URL"),
            database_path=os.getenv("DATABASE_PATH", "bot_data.db"),
            encryption_key=os.getenv("ENCRYPTION_KEY"),
        )

