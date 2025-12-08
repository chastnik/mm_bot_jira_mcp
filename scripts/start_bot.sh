#!/bin/bash
# Скрипт запуска Mattermost бота

set -e

# Проверяем наличие .env файла
if [ ! -f .env ]; then
    echo "Ошибка: файл .env не найден"
    echo "Скопируйте .env.example в .env и заполните необходимые переменные"
    exit 1
fi

# Запускаем бота
echo "Запуск Mattermost бота..."
uv run mattermost-bot

