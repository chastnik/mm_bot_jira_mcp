"""Управление аутентификацией пользователей."""

import logging
from typing import Optional

import requests
from requests.auth import HTTPBasicAuth

from .storage import Storage

logger = logging.getLogger(__name__)


class AuthManager:
    """Менеджер аутентификации пользователей."""

    def __init__(self, storage: Storage, jira_url: str, confluence_url: Optional[str] = None):
        """Инициализация менеджера аутентификации.

        Args:
            storage: Экземпляр хранилища
            jira_url: URL Jira сервера
            confluence_url: URL Confluence сервера (опционально)
        """
        self.storage = storage
        self.jira_url = jira_url.rstrip("/")
        self.confluence_url = confluence_url.rstrip("/") if confluence_url else None

    def validate_jira_credentials(
        self, username: str, password: str
    ) -> tuple[bool, Optional[str]]:
        """Проверить валидность учетных данных Jira.

        Args:
            username: Логин пользователя
            password: Пароль пользователя

        Returns:
            Кортеж (успех, сообщение об ошибке)
        """
        try:
            # Пробуем получить информацию о текущем пользователе
            response = requests.get(
                f"{self.jira_url}/rest/api/2/myself",
                auth=HTTPBasicAuth(username, password),
                timeout=10,
            )

            if response.status_code == 200:
                user_info = response.json()
                logger.info(
                    f"Успешная валидация Jira для пользователя {user_info.get('displayName', username)}"
                )
                return True, None
            elif response.status_code == 401:
                return False, "Неверный логин или пароль"
            else:
                return False, f"Ошибка при проверке: {response.status_code}"
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка при валидации Jira: {e}")
            return False, f"Ошибка подключения: {str(e)}"

    def validate_confluence_credentials(
        self, username: str, password: str
    ) -> tuple[bool, Optional[str]]:
        """Проверить валидность учетных данных Confluence.

        Args:
            username: Логин пользователя
            password: Пароль пользователя

        Returns:
            Кортеж (успех, сообщение об ошибке)
        """
        if not self.confluence_url:
            return False, "Confluence URL не настроен"

        try:
            # Пробуем получить информацию о текущем пользователе
            response = requests.get(
                f"{self.confluence_url}/rest/api/user/current",
                auth=HTTPBasicAuth(username, password),
                timeout=10,
            )

            if response.status_code == 200:
                user_info = response.json()
                logger.info(
                    f"Успешная валидация Confluence для пользователя {user_info.get('displayName', username)}"
                )
                return True, None
            elif response.status_code == 401:
                return False, "Неверный логин или пароль"
            else:
                return False, f"Ошибка при проверке: {response.status_code}"
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка при валидации Confluence: {e}")
            return False, f"Ошибка подключения: {str(e)}"

    def save_and_validate_jira(
        self, mm_user_id: str, username: str, password: str
    ) -> tuple[bool, Optional[str]]:
        """Сохранить и проверить учетные данные Jira.

        Args:
            mm_user_id: ID пользователя в Mattermost
            username: Логин Jira
            password: Пароль Jira

        Returns:
            Кортеж (успех, сообщение об ошибке)
        """
        success, error = self.validate_jira_credentials(username, password)
        if success:
            self.storage.save_user_credentials(
                mm_user_id, jira_username=username, jira_password=password
            )
        return success, error

    def save_and_validate_confluence(
        self, mm_user_id: str, username: str, password: str
    ) -> tuple[bool, Optional[str]]:
        """Сохранить и проверить учетные данные Confluence.

        Args:
            mm_user_id: ID пользователя в Mattermost
            username: Логин Confluence
            password: Пароль Confluence

        Returns:
            Кортеж (успех, сообщение об ошибке)
        """
        success, error = self.validate_confluence_credentials(username, password)
        if success:
            self.storage.save_user_credentials(
                mm_user_id,
                confluence_username=username,
                confluence_password=password,
            )
        return success, error

    def get_user_auth_headers(
        self, mm_user_id: str, service: str = "jira"
    ) -> Optional[dict[str, str]]:
        """Получить заголовки авторизации для пользователя.

        Args:
            mm_user_id: ID пользователя в Mattermost
            service: Сервис ('jira' или 'confluence')

        Returns:
            Словарь с заголовками авторизации или None
        """
        creds = self.storage.get_user_credentials(mm_user_id)

        if service == "jira":
            username = creds["jira_username"]
            password = creds["jira_password"]
        elif service == "confluence":
            username = creds["confluence_username"]
            password = creds["confluence_password"]
        else:
            return None

        if not username or not password:
            return None

        # Для basic auth создаем заголовок Authorization
        import base64

        credentials = f"{username}:{password}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return {"Authorization": f"Basic {encoded}"}

