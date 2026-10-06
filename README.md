# Kvitto Payments API

Сервис приёма оплаты курса для онлайн-школы: тарифы, создание платежа с промокодом и рассрочкой,
уведомления банка о смене статуса.

Стек: Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.0, SQLite, pytest + httpx.

## Запуск

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

API на http://127.0.0.1:8000, Swagger на http://127.0.0.1:8000/docs.
Таблицы и тарифы создаются автоматически при старте (файл `kvitto.db`).

Через Docker:

```bash
docker compose up --build
```

## Тесты и линтер

```bash
pytest -q
ruff check .
```

Те же проверки запускает GitHub Actions на каждый push (`.github/workflows/ci.yml`).

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

# Список с фильтрами
curl "http://127.0.0.1:8000/payments?email=student@example.com&status=pending"

# Вебхук банка
curl -X POST http://127.0.0.1:8000/webhooks/bank \
  -H "Content-Type: application/json" \
  -d '{"payment_id": 1, "status": "succeeded"}'
# -> 200 {"result": "ok"}; запрещённый переход -> 409 {"error": "invalid_transition"}
```

### Подпись вебхука

Если задана переменная `WEBHOOK_SECRET`, вебхук требует заголовок `X-Signature` —
HMAC-SHA256 (hex) от сырого тела запроса. Без подписи или с неверной — 401.
Если переменная не задана, проверка выключена (удобно для локального запуска).

```bash
export WEBHOOK_SECRET=s3cret
BODY='{"payment_id": 1, "status": "succeeded"}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" | awk '{print $2}')
curl -X POST http://127.0.0.1:8000/webhooks/bank \
  -H "Content-Type: application/json" -H "X-Signature: $SIG" -d "$BODY"
```

## Структура

```
app/
  pricing.py   чистая логика: скидка, график рассрочки, допустимые переходы
  services.py  работа с БД: создание платежа, идемпотентность, смена статуса
  schemas.py   Pydantic-схемы и валидация входа
  models.py    ORM-модели
  db.py        подключение к БД
  main.py      роуты и маппинг доменных ошибок в HTTP-коды
tests/
  test_pricing.py  юнит-тесты логики
  test_api.py      интеграционные тесты через HTTP
```

## Решения, которых нет в задании

- **Деньги.** Только `int` в копейках. Скидка `price * 10 // 100` — округление вниз;
  на текущих ценах деление всегда точное. График — `divmod`, остаток по копейке в первые платежи.
- **Тот же `Idempotency-Key` с другим телом** → `409 {"error": "idempotency_key_reused"}`:
  молча вернуть старый платёж на другой запрос опаснее, чем явно отказать.
- **Гонка двух запросов с одним ключом.** На `idempotency_key` стоит уникальный индекс;
  если параллельный запрос вставил запись первым, ловим `IntegrityError` и возвращаем его платёж.
- **Гонка двух вебхуков.** Статус меняется условным `UPDATE ... WHERE status = <старый>`,
  поэтому два одновременных перехода из `pending` не пройдут оба.
- **Повтор того же статуса** (`succeeded → succeeded`) → 409: по заданию разрешены только три перехода.
- **`installment_months` для `card`/`sbp`** → 422, а не тихое игнорирование.
- **Несуществующий `tariff_id`** → 422 в стандартном формате FastAPI (это ошибка входных данных).
- **Неизвестный статус в вебхуке** → 422.
- Миграции не используются: таблицы создаются `create_all` при старте.
