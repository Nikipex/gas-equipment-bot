# Gas Equipment Bot 🔧

Telegram-бот для поиска и подбора газового оборудования.

## Стек

| Компонент | Технология |
|-----------|-----------|
| Runtime | Python 3.12+ |
| Bot framework | aiogram 3.x |
| ORM | SQLAlchemy 2.x (async) |
| Миграции | Alembic |
| БД | PostgreSQL 16 |
| Конфиг | pydantic-settings |
| Логирование | loguru |
| Контейнеризация | Docker / docker-compose |

## Быстрый старт

### 1. Клонировать и настроить окружение

```bash
cp .env.example .env
# Отредактируйте .env — укажите BOT_TOKEN от @BotFather
```

### 2. Запуск через Docker

```bash
docker compose up -d --build
```

Бот и PostgreSQL стартуют автоматически.

### 3. Запуск локально (для разработки)

```bash
# Создать venv
python -m venv .venv && source .venv/bin/activate

# Установить зависимости
pip install -e ".[dev]"

# Поднять только БД
docker compose up -d db

# Применить миграции
alembic upgrade head

# Запустить бота
python -m app.main
```

## Структура проекта

```
app/
├── bot/            # Telegram-слой: хендлеры, клавиатуры, роутеры
├── services/       # Бизнес-логика
├── repositories/   # Доступ к данным (CRUD)
├── db/             # SQLAlchemy модели, сессия, миграции
├── schemas/        # Pydantic-схемы (DTO)
├── core/           # Конфигурация и логирование
├── utils/          # Утилиты: нормализация, матчинг
└── main.py         # Точка входа
```

## Команды

| Команда | Описание |
|---------|----------|
| `docker compose up -d --build` | Запустить всё |
| `docker compose logs -f bot` | Логи бота |
| `docker compose down -v` | Остановить и удалить данные |
| `alembic revision --autogenerate -m "..."` | Создать миграцию |
| `alembic upgrade head` | Применить миграции |
| `pytest` | Запуск тестов |
| `ruff check app/` | Линтинг |

## Лицензия

MIT
