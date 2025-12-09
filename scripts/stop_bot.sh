#!/bin/bash
# Скрипт остановки Mattermost бота

set -e

# Загружаем переменные окружения из .env, если файл существует
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

# Получаем порт MCP сервера из переменной окружения PORT (по умолчанию 8000)
PORT=${PORT:-8000}

# Функция для мягкого завершения процесса
soft_kill() {
    local signal=$1
    local pattern=$2
    local description=$3
    
    local pids=$(pgrep -f "$pattern" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        echo "Завершаем $description (PID: $pids)..."
        echo "$pids" | xargs -r kill $signal 2>/dev/null || true
        return 0
    fi
    return 1
}

# Функция для жесткого завершения процесса
hard_kill() {
    local pattern=$1
    local description=$2
    
    local pids=$(pgrep -f "$pattern" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        echo "Принудительно завершаем $description (PID: $pids)..."
        echo "$pids" | xargs -r kill -9 2>/dev/null || true
        return 0
    fi
    return 1
}

# Функция для завершения процесса на порту
kill_port() {
    local port=$1
    local signal=$2
    
    if command -v lsof >/dev/null 2>&1; then
        local pids=$(lsof -ti:${port} 2>/dev/null || true)
        if [ -n "$pids" ]; then
            echo "Завершаем процесс на порту ${port} (PID: $pids)..."
            echo "$pids" | xargs -r kill $signal 2>/dev/null || true
            return 0
        fi
    fi
    return 1
}

echo "Остановка Mattermost бота..."

# Сначала пытаемся мягко завершить процессы
echo "Попытка мягкого завершения процессов..."

# Завершаем mattermost-bot
if soft_kill "-TERM" "mattermost-bot" "процессы mattermost-bot"; then
    sleep 2
    # Проверяем, завершились ли процессы
    if pgrep -f "mattermost-bot" >/dev/null 2>&1; then
        echo "Процессы mattermost-bot не завершились, применяем принудительное завершение..."
        hard_kill "mattermost-bot" "процессы mattermost-bot"
    else
        echo "✓ Процессы mattermost-bot успешно завершены"
    fi
fi

# Завершаем mcp-atlassian
if soft_kill "-TERM" "mcp-atlassian" "процессы mcp-atlassian"; then
    sleep 2
    # Проверяем, завершились ли процессы
    if pgrep -f "mcp-atlassian" >/dev/null 2>&1; then
        echo "Процессы mcp-atlassian не завершились, применяем принудительное завершение..."
        hard_kill "mcp-atlassian" "процессы mcp-atlassian"
    else
        echo "✓ Процессы mcp-atlassian успешно завершены"
    fi
fi

# Завершаем процесс на порту MCP сервера
if kill_port "$PORT" "-TERM"; then
    sleep 2
    # Проверяем, освободился ли порт
    if lsof -ti:${PORT} >/dev/null 2>&1; then
        echo "Процесс на порту ${PORT} не завершился, применяем принудительное завершение..."
        kill_port "$PORT" "-9"
    else
        echo "✓ Порт ${PORT} освобожден"
    fi
fi

# Финальная проверка и принудительное завершение оставшихся процессов
echo ""
echo "Финальная проверка..."

found_any=false

# Проверяем mattermost-bot
if pgrep -f "mattermost-bot" >/dev/null 2>&1; then
    hard_kill "mattermost-bot" "оставшиеся процессы mattermost-bot"
    found_any=true
fi

# Проверяем mcp-atlassian
if pgrep -f "mcp-atlassian" >/dev/null 2>&1; then
    hard_kill "mcp-atlassian" "оставшиеся процессы mcp-atlassian"
    found_any=true
fi

# Проверяем порт
if command -v lsof >/dev/null 2>&1; then
    if lsof -ti:${PORT} >/dev/null 2>&1; then
        kill_port "$PORT" "-9"
        found_any=true
    fi
fi

if [ "$found_any" = false ]; then
    echo "✓ Все процессы успешно завершены"
else
    echo "✓ Принудительно завершены оставшиеся процессы"
fi

echo ""
echo "Остановка завершена"
