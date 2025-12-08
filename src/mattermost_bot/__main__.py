"""Точка входа для запуска бота."""

import logging
import sys

from .bot import MattermostBot
from .config import BotConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


def main() -> None:
    """Главная функция для запуска бота."""
    try:
        config = BotConfig.from_env()
    except ValueError as e:
        logger.error(f"Ошибка конфигурации: {e}")
        sys.exit(1)

    bot = MattermostBot(config)
    bot.run()


if __name__ == "__main__":
    main()

