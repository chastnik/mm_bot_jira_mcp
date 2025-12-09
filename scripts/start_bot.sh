#!/bin/bash
# Скрипт запуска Mattermost бота

set -e

# Проверяем наличие .env файла
if [ ! -f .env ]; then
    echo "Ошибка: файл .env не найден"
    echo "Скопируйте .env.example в .env и заполните необходимые переменные"
    exit 1
fi

# Загружаем переменные окружения из .env
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Получаем порт MCP сервера из переменной окружения PORT (по умолчанию 8000)
PORT=${PORT:-8000}

# Очистка старых/зависших процессов
cleanup_old_processes() {
    echo "Проверка старых процессов..."
    
    # Завершаем процессы на порту MCP сервера
    if lsof -ti:${PORT} >/dev/null 2>&1; then
        echo "Найден процесс на порту ${PORT}, завершаем..."
        lsof -ti:${PORT} | xargs -r kill -9 2>/dev/null || true
        sleep 1
    fi
    
    # Завершаем старые процессы mcp-atlassian
    if pgrep -f "mcp-atlassian" >/dev/null 2>&1; then
        echo "Найдены старые процессы mcp-atlassian, завершаем..."
        pkill -9 -f "mcp-atlassian" 2>/dev/null || true
        sleep 1
    fi
    
    # Завершаем старые процессы mattermost-bot
    if pgrep -f "mattermost-bot" >/dev/null 2>&1; then
        echo "Найдены старые процессы mattermost-bot, завершаем..."
        pkill -9 -f "mattermost-bot" 2>/dev/null || true
        sleep 1
    fi
    
    echo "Очистка завершена"
}

cleanup_old_processes

# Запускаем бота
echo "Запуск Mattermost бота..."
uv run mattermost-bot

