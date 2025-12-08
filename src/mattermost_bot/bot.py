"""Главный класс Mattermost бота."""

import asyncio
import json
import logging
import os
import signal
import ssl
import sys
import time
from typing import Optional
from urllib.parse import urlparse

import websockets
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

        # Настройка SSL проверки (по умолчанию True, можно отключить через переменную окружения)
        verify_ssl = os.getenv("MATTERMOST_SSL_VERIFY", "true").lower() in ("true", "1", "yes")
        
        self.driver = Driver(
            {
                "url": url,
                "token": self.config.mattermost_token,
                "scheme": scheme,
                "port": port,
                "verify": verify_ssl,
                "timeout": 30,
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

    async def _connect_websocket(self) -> None:
        """Подключение к WebSocket Mattermost."""
        # Парсим URL для WebSocket
        parsed_url = urlparse(self.config.mattermost_url)
        
        # Определяем схему WebSocket
        ws_scheme = "wss" if parsed_url.scheme == "https" else "ws"
        ws_port = parsed_url.port or (443 if parsed_url.scheme == "https" else 80)
        
        ws_url = f"{ws_scheme}://{parsed_url.hostname}:{ws_port}/api/v4/websocket"
        
        logger.info(f"Подключение к WebSocket: {ws_url}")
        
        # Настройка SSL контекста
        verify_ssl = os.getenv("MATTERMOST_SSL_VERIFY", "true").lower() in ("true", "1", "yes")
        ssl_context = None
        if ws_scheme == "wss":
            ssl_context = ssl.create_default_context()
            if not verify_ssl:
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
        
        # Основной цикл переподключения
        while self.running:
            try:
                async with websockets.connect(
                    ws_url,
                    ssl=ssl_context,
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=10,
                ) as websocket:
                    logger.info("WebSocket подключен")
                    
                    # Аутентификация
                    await self._authenticate_websocket(websocket)
                    
                    logger.info("WebSocket аутентифицирован")
                    
                    # Основной цикл обработки сообщений
                    async for message in websocket:
                        if not self.running:
                            break
                        await self._handle_websocket_message(message)
                        
            except websockets.exceptions.ConnectionClosed:
                if self.running:
                    logger.warning("WebSocket соединение закрыто, переподключение через 5 секунд...")
                    await asyncio.sleep(5)
            except Exception as e:
                if self.running:
                    logger.error(f"Ошибка WebSocket: {e}, переподключение через 5 секунд...")
                    await asyncio.sleep(5)

    async def _authenticate_websocket(self, websocket) -> None:
        """Аутентификация WebSocket соединения."""
        auth_message = {
            "seq": 1,
            "action": "authentication_challenge",
            "data": {
                "token": self.config.mattermost_token,
            },
        }
        
        await websocket.send(json.dumps(auth_message))
        
        # Ждем подтверждения аутентификации
        auth_timeout = 10
        start_time = time.time()
        
        while time.time() - start_time < auth_timeout:
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                event = json.loads(message)
                
                if event.get("event") == "hello":
                    logger.info("WebSocket аутентификация успешна")
                    return
                    
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Ошибка аутентификации WebSocket: {e}")
                raise
        
        raise Exception("Таймаут аутентификации WebSocket")

    async def _handle_websocket_message(self, message: str | bytes) -> None:
        """Обработка сообщения от WebSocket."""
        try:
            if isinstance(message, bytes):
                message_str = message.decode()
            else:
                message_str = str(message)
                
            event = json.loads(message_str)
            event_type = event.get("event")
            
            if event_type == "posted":
                await self._handle_post_event(event)
            elif event_type == "hello":
                logger.debug("Получен hello от WebSocket")
            else:
                logger.debug(f"Событие WebSocket: {event_type}")
                
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON от WebSocket: {e}")
        except Exception as e:
            logger.error(f"Ошибка обработки WebSocket сообщения: {e}")

    async def _handle_post_event(self, event: dict) -> None:
        """Обработка события нового поста."""
        try:
            # Извлекаем данные поста
            post_data = event.get("data", {}).get("post")
            if not post_data:
                return
            
            # Парсим пост (может быть строкой JSON)
            if isinstance(post_data, str):
                post = json.loads(post_data)
            else:
                post = post_data
            
            # Получаем информацию о боте
            me = self.driver.users.get_user("me")
            bot_user_id = me["id"]
            
            # Игнорируем сообщения от самого бота
            if post.get("user_id") == bot_user_id:
                return
            
            # Вызываем обработчик поста
            self.handle_post(post)
                
        except Exception as e:
            logger.error(f"Ошибка обработки события поста: {e}")

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

        # Подписываемся на события через WebSocket
        try:
            # Запускаем WebSocket соединение в отдельной задаче
            asyncio.create_task(self._connect_websocket())

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

