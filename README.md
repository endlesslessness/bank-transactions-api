# Bank Transactions API

REST API для банковских транзакций: аутентификация по JWT, счета, переводы
с идемпотентностью и атомарностью.

## Стек

- Python 3.11, FastAPI, Uvicorn
- SQLAlchemy 2.0 (async), Alembic, asyncpg
- PostgreSQL 16, Redis 7
- Pydantic v2, pydantic-settings
- python-jose (JWT), passlib[bcrypt], slowapi (rate limiting)
- pytest, httpx, ruff, mypy
- Docker, Docker Compose, Nginx

## Структура

```
bank-transactions-api/
├── backend/
│   ├── app/
│   │   ├── api/v1/endpoints/   # HTTP-эндпоинты (тонкие)
│   │   ├── core/               # конфиг, безопасность, Redis
│   │   ├── db/                 # подключение и сессии
│   │   ├── models/             # SQLAlchemy-модели
│   │   ├── schemas/            # Pydantic-схемы
│   │   ├── services/           # бизнес-логика
│   │   └── main.py             # точка входа
│   ├── alembic/                # миграции
│   ├── tests/                  # тесты
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── js/
│   └── css/
├── nginx/
│   └── nginx.conf
├── docker-compose.yml
└── README.md
```

## Запуск

```bash
cp backend/.env.example backend/.env
docker compose up --build -d
```

- Фронтенд и прокси: http://localhost
- API напрямую: http://localhost:8000
- Swagger: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

Логи: `docker compose logs -f backend`

## Локальная разработка

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cd backend && uvicorn app.main:app --reload
```

Линтер и типизация:

```bash
ruff check backend
mypy backend/app
```

Тесты:

```bash
pytest backend/tests
```

## API

### Auth

| Метод | Путь                        | Описание                  |
| ----- | --------------------------- | ------------------------- |
| POST  | `/api/v1/auth/register`     | Регистрация               |
| POST  | `/api/v1/auth/login`        | Логин, выдача JWT         |
| POST  | `/api/v1/auth/refresh`      | Обновить токен            |
| GET   | `/api/v1/auth/me`           | Текущий пользователь      |

### Accounts

| Метод | Путь                              | Описание       |
| ----- | --------------------------------- | -------------- |
| GET   | `/api/v1/accounts`                | Список счетов  |
| POST  | `/api/v1/accounts`                | Создать счёт   |
| GET   | `/api/v1/accounts/{id}`           | Детали счёта   |
| GET   | `/api/v1/accounts/{id}/balance`   | Баланс счёта   |

### Transactions

| Метод | Путь                          | Описание                |
| ----- | ----------------------------- | ----------------------- |
| POST  | `/api/v1/transactions`        | Создать перевод          |
| GET   | `/api/v1/transactions`        | История транзакций       |
| GET   | `/api/v1/transactions/{id}`   | Детали транзакции        |

## Статус

Структура проекта развёрнута, бизнес-логика не реализована.

Скриншоты интерфейса будут добавлены после разработки фронтенда.
