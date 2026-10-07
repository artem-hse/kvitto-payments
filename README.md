# Kvitto Payments API

[![CI](https://github.com/artem-hse/kvitto-payments/actions/workflows/ci.yml/badge.svg)](https://github.com/artem-hse/kvitto-payments/actions/workflows/ci.yml)

Сервис приёма оплаты курса для онлайн-школы: тарифы, создание платежа с промокодом и рассрочкой,
уведомления банка о смене статуса.

Стек: Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.0, Alembic, SQLite, pytest + httpx.

## Запуск

Нужен Python **3.11 или новее** (`python3 --version`).

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

API — http://127.0.0.1:8000, Swagger — http://127.0.0.1:8000/docs.
При старте приложение само применяет миграции Alembic и создаёт тарифы (файл `kvitto.db`).

Через Docker:

```bash
docker compose up --build
```

## Тесты и линтер

```bash
pytest -q
ruff check .
```

Те же проверки (плюс `ruff format --check`, `alembic check` и сборка Docker-образа)
запускает GitHub Actions на каждый push — `.github/workflows/ci.yml`.

## Примеры запросов

```bash
# Тарифы
curl http://127.0.0.1:8000/tariffs

# Рассрочка на 3 месяца, standard без промокода
curl -X POST http://127.0.0.1:8000/payments \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: order-1" \
  -d '{"tariff_id": 2, "email": "student@example.com", "method": "installment", "installment_months": 3}'
# -> 201, amount 1990000, schedule [663334, 663333, 663333]
# Повтор с тем же ключом -> 200 и тот же платёж

# Оплата по СБП с промокодом (регистр не важен)
curl -X POST http://127.0.0.1:8000/payments \
  -H "Content-Type: application/json" \
  -d '{"tariff_id": 3, "email": "student@example.com", "method": "sbp", "promo_code": "kvitto10"}'
# -> 201, discount 299000, amount 2691000

# Платёж
curl http://127.0.0.1:8000/payments/1

# Список с фильтрами и пагинацией
curl "http://127.0.0.1:8000/payments?email=student@example.com&status=pending&limit=20&offset=0"

# Вебхук банка
curl -X POST http://127.0.0.1:8000/webhooks/bank \
  -H "Content-Type: application/json" \
  -d '{"payment_id": 1, "status": "succeeded"}'
# -> 200 {"result": "ok"}; запрещённый переход -> 409 {"error": "invalid_transition"}
```

### Подпись вебхука

Если задана переменная `WEBHOOK_SECRET`, вебхук требует заголовок `X-Signature` —
HMAC-SHA256 (hex) от **сырого** тела запроса. Без подписи или с неверной — 401.
Если переменная не задана, проверка выключена (удобно для локального запуска).

```bash
WEBHOOK_SECRET=s3cret uvicorn app.main:app      # в другом терминале:

BODY='{"payment_id": 1, "status": "succeeded"}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac s3cret | awk '{print $NF}')
curl -X POST http://127.0.0.1:8000/webhooks/bank \
  -H "Content-Type: application/json" -H "X-Signature: $SIG" -d "$BODY"
```

### Миграции

```bash
alembic upgrade head                       # применить (приложение делает это само при старте)
alembic revision --autogenerate -m "..."   # новая миграция после изменения моделей
alembic check                              # модели и миграции не разошлись
```

## Структура

```
app/
  pricing.py   чистая логика: скидка, график рассрочки, допустимые переходы
  services.py  работа с БД: создание платежа, идемпотентность, смена статуса
  schemas.py   Pydantic-схемы и валидация входа
  models.py    ORM-модели и CHECK-ограничения
  db.py        подключение к БД, запуск миграций
  main.py      роуты и маппинг доменных ошибок в HTTP-коды
migrations/    Alembic
tests/
  test_pricing.py     юнит-тесты логики без БД и HTTP
  test_api.py         обязательные сценарии через HTTP
  test_edge_cases.py  краевые случаи, найденные на ревью
  test_migrations.py  схема после миграций совпадает с моделями
```

## Решения, которых нет в задании

**Деньги**
- Только `int` в копейках, в БД — `BigInteger`. Скидка `price * 10 // 100` — округление вниз
  в пользу покупателя; на текущих ценах деление и так точное.
- График — `divmod`: остаток по копейке уходит в первые платежи, сумма графика ровно равна сумме.
- CHECK-ограничения в БД: `amount >= 0`, `discount >= 0`, статус и способ оплаты — из списка.
  Если в коде появится баг, база не примет некорректную строку.

**Повторы и статусы**
- **Тот же `Idempotency-Key` с другим телом** → `409 {"error": "idempotency_key_reused"}`:
  молча вернуть старый платёж на другой запрос опаснее, чем явно отказать.
  Промокод сравнивается без учёта регистра, поэтому `KVITTO10` и `kvitto10` — один запрос.
- **Гонка двух запросов с одним ключом.** На `idempotency_key` уникальный индекс;
  если параллельный запрос вставил запись первым, ловим `IntegrityError` и возвращаем его платёж.
- **Гонка двух вебхуков.** Статус меняется условным `UPDATE ... WHERE status = <старый>`,
  поэтому два одновременных перехода из `pending` не пройдут оба.
- **Повтор того же статуса** (`succeeded → succeeded`) → 409: по заданию разрешены только три перехода.

**Валидация** (всё — стандартная 422 FastAPI)
- `installment_months` для `card`/`sbp` → 422, а не тихое игнорирование.
- Несуществующий `tariff_id` → 422: это ошибка входных данных, а не «ресурс не найден».
- Лишние поля в теле (`"amount": 1`) → 422: сумму считает сервер.
- `tariff_id: true` или `2.0` → 422 (строгий `int`), иначе Pydantic молча сделал бы из `true` единицу.
- Пустой или длиннее 255 символов `Idempotency-Key` → 422.
- Email хранится в нижнем регистре, фильтр `GET /payments?email=` не зависит от регистра.

**404 вместо 500**
- `id` больше, чем помещается в колонку (`/payments/99999999999999999999`), — 404:
  такого платежа не может быть. Раньше драйвер БД падал с `OverflowError` → 500.

## Бонусы

| Бонус | Где |
|---|---|
| `docker compose up` | `Dockerfile`, `docker-compose.yml` (не от root, healthcheck) |
| Подпись вебхука HMAC-SHA256 | `app/main.py: verify_signature`, `hmac.compare_digest` |
| Миграции Alembic | `migrations/`, применяются при старте; тест на расхождение с моделями |
| `GET /payments` с фильтрами | `email`, `status` + пагинация `limit`/`offset` |
| GitHub Actions | ruff, pytest на 3.11 и 3.12, `alembic check`, сборка образа; бейдж в README и таблица тестов на странице запуска |
| Правила для ассистента | `CLAUDE.md` |
