"""Главный класс Mattermost бота."""

import asyncio
import logging
import signal
import sys
from typing import Optional

from mattermostdriver import Driver
from mattermostdriver.exceptions import (
    InvalidOrMissingParameters,
    NoAccessTokenProvided,
    ResourceNotFound,
)

from .auth_manager import AuthManager
from .config import BotConfig
from .handlers import MessageHandlers
from .llm_client import LLMClient
from .mcp_client import MCPClient
from .storage import Storage

logger = logging.getLogger(__name__)


class MattermostBot:
    """Бот для Mattermost с интеграцией MCP сервера."""

    def __init__(self, config: BotConfig):
        """Инициализация бота.

        Args:
            config: Конфигурация бота
        """
        self.config = config
        self.driver: Optional[Driver] = None
        self.storage: Optional[Storage] = None
        self.auth_manager: Optional[AuthManager] = None
        self.llm_client: Optional[LLMClient] = None
        self.mcp_client: Optional[MCPClient] = None
        self.handlers: Optional[MessageHandlers] = None
        self.running = False

    async def initialize(self) -> None:
        """Инициализировать все компоненты бота."""
        logger.info("Инициализация бота...")

        # Инициализация хранилища
        self.storage = Storage(
            self.config.database_path, self.config.encryption_key
        )

        # Инициализация менеджера аутентификации
        self.auth_manager = AuthManager(
            self.storage,
            self.config.jira_url,
            self.config.confluence_url,
        )

        # Инициализация LLM клиента
        self.llm_client = LLMClient(
            self.config.llm_api_url,
            self.config.llm_api_key,
            self.config.llm_model,
        )

        # Инициализация MCP клиента
        self.mcp_client = MCPClient(
            jira_url=self.config.jira_url,
            confluence_url=self.config.confluence_url,
        )

        # Запуск MCP сервера
        try:
            await self.mcp_client.start_server(port=8000, host="127.0.0.1")
        except Exception as e:
            logger.error(f"Не удалось запустить MCP сервер: {e}")
            raise

        # Инициализация обработчиков
        self.handlers = MessageHandlers(
            self.storage,
            self.auth_manager,
            self.llm_client,
            self.mcp_client,
        )

        # Инициализация Mattermost драйвера
        # Извлекаем домен из URL (убираем протокол)
        mattermost_url = self.config.mattermost_url
        if mattermost_url.startswith("https://"):
            scheme = "https"
            port = 443
            url = mattermost_url[8:]  # Убираем "https://"
        elif mattermost_url.startswith("http://"):
            scheme = "http"
            port = 80
            url = mattermost_url[7:]  # Убираем "http://"
        else:
            # Если протокол не указан, предполагаем https
            scheme = "https"
            port = 443
            url = mattermost_url

        self.driver = Driver(
            {
                "url": url,
                "token": self.config.mattermost_token,
                "scheme": scheme,
                "port": port,
            }
        )

        # Подключение к Mattermost
        try:
            self.driver.login()
            logger.info("Успешное подключение к Mattermost")
        except Exception as e:
            logger.error(f"Ошибка при подключении к Mattermost: {e}")
            raise

        logger.info("Бот инициализирован")

    def handle_post(self, post: dict) -> None:
        """Обработать сообщение от пользователя.

        Args:
            post: Объект сообщения от Mattermost
        """
        try:
            # Получаем информацию о сообщении
            channel_id = post.get("channel_id")
            user_id = post.get("user_id")
            message = post.get("message", "").strip()

            if not message or not user_id:
                return

            # Проверяем, что это личное сообщение (direct message)
            channel = self.driver.channels.get_channel(channel_id)
            if channel.get("type") != "D":
                # Игнорируем сообщения не в личных чатах
                return

            # Получаем информацию о пользователе
            user = self.driver.users.get_user(user_id)
            username = user.get("username", "неизвестный")

            logger.info(f"Получено сообщение от {username}: {message}")

            # Обрабатываем сообщение (синхронно, так как вызывается из WebSocket)
            # mattermostdriver использует синхронный API, поэтому нужно получить event loop
            import asyncio
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                # Если event loop не существует, создаем новый
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            response = loop.run_until_complete(
                self.handlers.handle_message(user_id, message)
            )

            # Отправляем ответ
            self.driver.posts.create_post(
                {
                    "channel_id": channel_id,
                    "message": response,
                }
            )

            logger.info(f"Отправлен ответ пользователю {username}")

        except Exception as e:
            logger.error(f"Ошибка при обработке сообщения: {e}", exc_info=True)

    async def start(self) -> None:
        """Запустить бота."""
        if self.running:
            logger.warning("Бот уже запущен")
            return

        await self.initialize()
        self.running = True

        logger.info("Бот запущен и готов к работе")

        # Подписываемся на события
        try:
            # Получаем WebSocket соединение
            # mattermostdriver использует синхронный API, поэтому запускаем в отдельном потоке
            def start_websocket():
                """Запуск WebSocket соединения для получения сообщений от Mattermost."""
                # Создаем новый event loop для потока
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    self.driver.init_websocket(self.handle_post)
                finally:
                    loop.close()

            # Запускаем WebSocket в отдельном потоке (daemon=True означает, что поток завершится при выходе программы)
            import threading
            ws_thread = threading.Thread(target=start_websocket, daemon=True)
            ws_thread.start()

            # Ожидаем сигналов для остановки
            loop = asyncio.get_event_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(
                    sig, lambda: asyncio.create_task(self.stop())
                )

            # Ждем, пока бот работает
            while self.running:
                await asyncio.sleep(1)

        except KeyboardInterrupt:
            logger.info("Получен сигнал остановки")
        except Exception as e:
            logger.error(f"Ошибка при работе бота: {e}", exc_info=True)
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Остановить бота."""
        if not self.running:
            return

        logger.info("Остановка бота...")
        self.running = False

        # Останавливаем MCP сервер
        if self.mcp_client:
            await self.mcp_client.close()

        # Закрываем соединение с Mattermost
        if self.driver:
            try:
                self.driver.logout()
            except Exception:
                pass

        logger.info("Бот остановлен")

    def run(self) -> None:
        """Запустить бота синхронно."""
        try:
            asyncio.run(self.start())
        except KeyboardInterrupt:
            logger.info("Бот остановлен пользователем")
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}", exc_info=True)
            sys.exit(1)

