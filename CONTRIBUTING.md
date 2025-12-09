# Вклад в MCP Atlassian

Спасибо за ваш интерес к участию в проекте MCP Atlassian! Этот документ содержит руководящие принципы и инструкции для внесения вклада в этот проект.

## Настройка окружения разработки

1. Убедитесь, что у вас установлен Python 3.10+
1. Установите [uv](https://docs.astral.sh/uv/getting-started/installation/)
1. Сделайте форк репозитория
1. Клонируйте ваш форк: `git clone https://github.com/YOUR-USERNAME/mcp-atlassian.git`
1. Добавьте upstream remote: `git remote add upstream https://github.com/sooperset/mcp-atlassian.git`
1. Установите зависимости:

    ```sh
    uv sync
    uv sync --frozen --all-extras --dev
    ```

1. Активируйте виртуальное окружение:

    __macOS и Linux__:

    ```sh
    source .venv/bin/activate
    ```

    __Windows__:

    ```powershell
    .venv\Scripts\activate.ps1
    ```

1. Настройте pre-commit хуки:

    ```sh
    pre-commit install
    ```

1. Настройте переменные окружения (скопируйте из .env.example):

    ```bash
    cp .env.example .env
    ```

## Настройка окружения разработки с локальным VSCode devcontainer

1. Клонируйте ваш форк: `git clone https://github.com/YOUR-USERNAME/mcp-atlassian.git`
1. Добавьте upstream remote: `git remote add upstream https://github.com/sooperset/mcp-atlassian.git`
1. Откройте проект в VSCode и откройте с devcontainer
1. Добавьте эту конфигурацию в ваш `.vscode/settings.json`:

    ```json
    {
        "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",
        "[python]": {
        "editor.defaultFormatter": "charliermarsh.ruff",
        "editor.formatOnSave": true
        }
    }
    ```

## Рабочий процесс разработки

1. Создайте ветку для функции или исправления:

    ```sh
    git checkout -b feature/your-feature-name
    # или
    git checkout -b fix/issue-description
    ```

1. Внесите ваши изменения

1. Убедитесь, что тесты проходят:

    ```sh
    uv run pytest

    # С покрытием
    uv run pytest --cov=mcp_atlassian
    ```

1. Запустите проверки качества кода с помощью pre-commit:

    ```bash
    pre-commit run --all-files
    ```

1. Закоммитьте ваши изменения с четкими, краткими сообщениями коммита, ссылаясь на issues, когда это применимо

1. Отправьте pull request в основную ветку

## Стиль кода

- Запускайте `pre-commit run --all-files` перед коммитом
- Инструменты качества кода (управляемые pre-commit):
  - `ruff` для форматирования и линтинга (лимит строки 88 символов)
  - `pyright` для проверки типов (предпочтительнее mypy)
  - `prettier` для форматирования YAML/JSON
  - Дополнительные проверки на завершающие пробелы, окончания файлов, валидность YAML/TOML
- Следуйте паттернам аннотаций типов:
  - `type[T]` для типов классов
  - Типы Union с синтаксисом pipe: `str | None`
  - Стандартные типы коллекций с подстрочными индексами: `list[str]`, `dict[str, Any]`
- Добавляйте docstrings ко всем публичным модулям, функциям, классам и методам, используя формат Google-style:

        ```python
        def function_name(param1: str, param2: int) -> bool:
            """Краткое описание назначения функции.

            Более подробное описание при необходимости.

            Args:
                param1: Описание param1
                param2: Описание param2

            Returns:
                Описание возвращаемого значения

            Raises:
                ValueError: Когда и почему возникает это исключение
            """
        ```

## Процесс Pull Request

1. Заполните шаблон PR с описанием ваших изменений
2. Убедитесь, что все проверки CI проходят
3. Запросите ревью у сопровождающих
4. Учтите отзывы ревьюеров, если они запрошены

## Процесс релиза

Релизы следуют семантическому версионированию:
- **MAJOR** версия для несовместимых изменений API
- **MINOR** версия для обратно совместимых добавлений функциональности
- **PATCH** версия для обратно совместимых исправлений багов

---

Спасибо за вклад в MCP Atlassian!
