#!/usr/bin/env python3
"""Тестовый скрипт для проверки JQL запросов к Jira worklogs."""

import os
import sys
import argparse

# Добавляем путь к src
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from dotenv import load_dotenv
load_dotenv()

from jira import JIRA

parser = argparse.ArgumentParser(description='Тест JQL запросов к Jira worklogs')
parser.add_argument('--user', '-u', required=True, help='Jira username для подключения')
parser.add_argument('--password', '-p', required=True, help='Jira пароль')
parser.add_argument('--test-user', '-t', default='OAAntonov', help='Username для поиска worklogs')
parser.add_argument('--date-from', '-f', default='2025-12-05', help='Дата начала (YYYY-MM-DD)')
parser.add_argument('--date-to', '-e', default='2025-12-05', help='Дата окончания (YYYY-MM-DD)')
args = parser.parse_args()

# Конфигурация
JIRA_URL = os.getenv("JIRA_URL", "https://jira.1solution.ru/")
USERNAME = args.user
PASSWORD = args.password

print(f"\nПодключение к {JIRA_URL}...")
jira = JIRA(server=JIRA_URL, basic_auth=(USERNAME, PASSWORD))
print("✅ Подключено!")

# Тестовые параметры
test_username = args.test_user
date_from = args.date_from
date_to = args.date_to

print(f"Тестируем worklogs для: {test_username}")
print(f"Период: {date_from} - {date_to}")

print(f"\n=== Тест 1: worklogAuthor + worklogDate ===")
jql1 = f'worklogAuthor = "{test_username}" AND worklogDate >= "{date_from}" AND worklogDate <= "{date_to}"'
print(f"JQL: {jql1}")
try:
    issues = jira.search_issues(jql1, maxResults=1000)
    print(f"✅ Найдено задач: {len(issues)}")
    for issue in issues[:5]:
        print(f"  - {issue.key}: {issue.fields.summary}")
except Exception as e:
    print(f"❌ Ошибка: {e}")

print(f"\n=== Тест 2: Только worklogDate (без автора) ===")
jql2 = f'worklogDate >= "{date_from}" AND worklogDate <= "{date_to}"'
print(f"JQL: {jql2}")
try:
    issues = jira.search_issues(jql2, maxResults=1000)
    print(f"✅ Найдено задач: {len(issues)}")
except Exception as e:
    print(f"❌ Ошибка: {e}")

print(f"\n=== Тест 3: Получение worklogs для задачи ===")
if issues:
    test_issue = issues[0].key
    print(f"Задача: {test_issue}")
    try:
        worklogs = jira.worklogs(test_issue)
        print(f"✅ Найдено worklogs: {len(worklogs)}")
        for wl in worklogs[:3]:
            author = wl.author.name if hasattr(wl.author, 'name') else wl.author.displayName
            print(f"  - Автор: {author}, Время: {wl.timeSpent}, Дата: {wl.started[:10]}")
    except Exception as e:
        print(f"❌ Ошибка: {e}")

print(f"\n=== Тест 4: Структура author в worklog ===")
if issues:
    test_issue = issues[0].key
    try:
        worklogs = jira.worklogs(test_issue)
        if worklogs:
            wl = worklogs[0]
            print(f"author объект: {wl.author.raw}")
    except Exception as e:
        print(f"❌ Ошибка: {e}")

print(f"\n=== Тест 5: Подсчёт worklogs пользователя за период ===")
jql5 = f'worklogDate >= "{date_from}" AND worklogDate <= "{date_to}"'
try:
    issues = jira.search_issues(jql5, maxResults=1000)
    print(f"Всего задач с worklogs за период: {len(issues)}")
    
    user_worklogs = []
    for issue in issues:
        try:
            worklogs = jira.worklogs(issue.key)
            for wl in worklogs:
                # Проверяем автора
                author_name = getattr(wl.author, 'name', None) or getattr(wl.author, 'key', None) or ''
                wl_date = wl.started[:10]
                
                if author_name.lower() == test_username.lower() and date_from <= wl_date <= date_to:
                    user_worklogs.append({
                        'issue': issue.key,
                        'author': author_name,
                        'time': wl.timeSpent,
                        'date': wl_date,
                        'comment': getattr(wl, 'comment', '')[:50] if hasattr(wl, 'comment') and wl.comment else ''
                    })
        except Exception as e:
            print(f"  Ошибка для {issue.key}: {e}")
    
    print(f"\n✅ Найдено worklogs пользователя {test_username}: {len(user_worklogs)}")
    total_seconds = 0
    for wl in user_worklogs:
        print(f"  - {wl['issue']}: {wl['time']} ({wl['date']}) - {wl['comment']}")
        # Подсчитаем общее время (примерно)
    
except Exception as e:
    print(f"❌ Ошибка: {e}")

print(f"\n=== Тест 6: REST API /worklog/updated ===")
try:
    from datetime import datetime, timedelta
    import time
    
    # Конвертируем дату в timestamp (миллисекунды)
    dt_from = datetime.strptime(date_from, "%Y-%m-%d")
    since_timestamp = int(dt_from.timestamp() * 1000)
    
    print(f"Запрос worklogs обновлённых с: {dt_from} (timestamp: {since_timestamp})")
    
    # Используем REST API напрямую
    url = f"rest/api/2/worklog/updated?since={since_timestamp}"
    response = jira._session.get(jira._options['server'] + '/' + url)
    
    if response.status_code == 200:
        data = response.json()
        print(f"✅ API ответил. Worklogs: {len(data.get('values', []))}")
        print(f"   lastPage: {data.get('lastPage', 'N/A')}")
        
        # Показываем первые несколько worklog IDs
        worklog_ids = [w.get('worklogId') for w in data.get('values', [])[:10]]
        print(f"   Первые worklog IDs: {worklog_ids}")
    else:
        print(f"❌ Ошибка: {response.status_code} - {response.text[:200]}")
        
except Exception as e:
    print(f"❌ Ошибка: {e}")

print("\n=== Готово ===")
