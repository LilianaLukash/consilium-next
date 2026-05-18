# Consilium

**Consilium** — веб-приложение «совет экспертов»: несколько LLM через [OpenRouter](https://openrouter.ai/) проходят волны анализа и дебатов, затем **один общий вердикт** (топ‑3 на русском). Есть **гостевая проба**, **регистрация** (email + Google), **баланс** и опционально **Stripe**.

Репозиторий: [github.com/LilianaLukash/consilium-next](https://github.com/LilianaLukash/consilium-next)

## Роли в совете

Внутренние id в коде/API остаются на английском; в UI показаны русские имена.

| Внутренний id | В интерфейсе | Задача |
|-----------------|--------------|--------|
| `diator` | **Генератор идей** | Рынок, много идей, отбор по спросу |
| `visionary` | **Визионер** | Креатив, бренд, viral-угол |
| `architect` | **Архитектор** | Как воплотить |
| `critic` | **Критик** | Риски и контраргументы |
| *(синтез)* | **Вердикт** | Итоговый текст (отдельная модель синтеза) |

Поток: волна 1 (идеи) → волна 2 (архитектор + критик) → дебаты → синтез.

### Как это выглядит в UI

На главной странице сверху — **шаги** (Старт → Вклад → Дебаты → …), блок **«Миссия»** (задача, вложения, раунды), сворачиваемые **«Настройки совета»** (пресет и модели по ролям), ниже **карточки ролей** с текущими slug моделей — как на локальном `http://127.0.0.1:8001`. Подпись **«Генератор идей»** — это роль `diator` в коде.

Оранжевые бейджи **MASTER** / **DEV** бывают в режиме разработки на localhost при `MASTER_MODE=true` и `ENVIRONMENT=development` (без лимитов баланса); на production их быть не должно.

## Стек

- **Backend:** Python 3.12+, FastAPI, SQLite (`data/consilium.db`), JWT + refresh, bcrypt  
- **LLM:** OpenRouter (chat completions)  
- **Биллинг:** списание с баланса ≈ **стоимость OpenRouter × 1.4** (настройка `BILLING_MARKUP_MULTIPLIER`)  
- **Оплата (опционально):** Stripe Checkout + webhook  
- **Frontend:** статика в `static/` (без отдельного Node-сборщика)

## Быстрый старт

```powershell
git clone https://github.com/LilianaLukash/consilium-next.git
cd consilium-next
copy .env.example .env
# Вставьте OPENROUTER_API_KEY в .env
.\run.ps1
```

- Главная: http://127.0.0.1:8001  
- Вход: http://127.0.0.1:8001/auth.html  
- Аккаунт / баланс: http://127.0.0.1:8001/account.html  

Без OpenRouter ключ совета не запустится (`503` на `/api/run/stream`).

### Минимальный `.env` для первого запуска

См. полный список в [`.env.example`](.env.example). Обязательно:

| Переменная | Описание |
|------------|----------|
| `OPENROUTER_API_KEY` | Ключ [OpenRouter](https://openrouter.ai/keys) |
| `OPENROUTER_APP_URL` | URL приложения (локально `http://127.0.0.1:8001`) |
| `APP_PUBLIC_URL` | Обычно то же |
| `JWT_SECRET` | В dev можно короткий; в **production** ≥ 32 символов |

Для продакшена дополнительно: `ENVIRONMENT=production`, `MASTER_MODE=false`, нормальный `JWT_SECRET`.

## Режимы пользователя

| Режим | Поведение |
|--------|-----------|
| **Guest** | `GUEST_FREE_RUNS` бесплатных запусков (по умолчанию 1), дальше нужна регистрация |
| **User** | Баланс, списание за вызовы моделей; вход после подтверждения email |
| **Master** | Только `MASTER_MODE=true` **и** `ENVIRONMENT` не production **и** запрос с localhost — без лимитов |

## Модели в UI

Список в выпадающих списках строится из OpenRouter, но **фильтруется** по файлу [`data/chat_models_verified.json`](data/chat_models_verified.json) — туда попадают id, которые прошли короткий тест `chat/completions` (чтобы не показывать аудио/image-only модели вроде Lyria). Обновить список:

```powershell
.\.venv\Scripts\python scripts\probe_chat_models.py
```

Префикс роли «Диатор» в env: `MODEL_DIATOR` — это **Генератор идей** (внутренний id `diator`).

**Важно:** slug в карточках (например `x-ai/grok-4.3`, `anthropic/claude-sonnet-4`) **не высечены в README** — они приходят из выбранного стека в UI, из `.env` (`MODEL_*`) и из пресета. Дефолты в коде и в [`.env.example`](.env.example): визионер обычно `nousresearch/hermes-4-70b`. Если у вас в списке выбран другой id (например другая редакция Hermes на OpenRouter), в интерфейсе будет он — это нормально.

## API и документация OpenAPI

После запуска сервера:

- **Swagger UI:** http://127.0.0.1:8001/docs  
- **ReDoc:** http://127.0.0.1:8001/redoc  
- **Health:** `GET /api/health`

Кратко по зонам:

- **Auth:** `/api/auth/register`, `login`, `refresh`, `logout`, `me`, Google OAuth, сброс пароля  
- **Billing:** `/api/billing/balance`, `usage`, `transactions`, `stripe/checkout`, `stripe/webhook`  
- **Совет:** `POST /api/run/stream` (multipart: `prompt`, `council_config`, файлы), ответ **SSE**  
- **Сессии:** `/api/sessions`, загрузка и ревизии — с проверкой владельца  

Типичные коды ответов: `401` (нужен вход), `402` (мало баланса), `403` (email не подтверждён / нет доступа к сессии).

## Тесты

```powershell
pip install -r requirements.txt
python -m pytest tests -q
```

## Деплой (Railway)

Коротко: подключить репозиторий, **Volume** на `/app/data`, в **Variables** — те же ключи, что в `.env.example`, с публичным URL.

| Переменная | production |
|------------|------------|
| `ENVIRONMENT` | `production` |
| `MASTER_MODE` | `false` |
| `OPENROUTER_API_KEY` | обязательно |
| `JWT_SECRET` | ≥ 32 символов, случайная строка |
| `OPENROUTER_APP_URL` / `APP_PUBLIC_URL` | `https://ваш-домен...` |
| `GOOGLE_REDIRECT_URI` | `https://ваш-домен.../api/auth/google/callback` |
| Stripe | если включены платежи: `STRIPE_SECRET_KEY` + `STRIPE_WEBHOOK_SECRET` |

1. [railway.app](https://railway.app) → **Deploy from GitHub**  
2. **Settings → Networking → Generate Domain**  
3. **Volume** → mount path `/app/data`  
4. Stripe webhook: `POST .../api/billing/stripe/webhook`, событие `checkout.session.completed`

Сборка: Dockerfile в корне репозитория.

### Docker локально

```bash
docker build -t consilium-next .
docker run -p 8001:8000 --env-file .env -v consilium-data:/app/data consilium-next
```

## Типичные проблемы

| Симптом | Что проверить |
|---------|----------------|
| **404** от OpenRouter на модель | Slug устарел; см. актуальные id на [openrouter.ai/models](https://openrouter.ai/models) и `MODEL_DIATOR` и др. |
| **502** Provider returned error | Часто неподходящая модель (например не текстовый chat) или перегрузка провайдера; смените модель в UI |
| После деплоя нет сессий / баланса | Нет Volume на `/app/data` — SQLite эфемерный |
| **Google OAuth не настроен** | В Railway пустые `GOOGLE_CLIENT_ID` / `SECRET` — см. раздел ниже |
| Google login не работает | `GOOGLE_REDIRECT_URI` должен **точно** совпадать с URI в Google Cloud Console |

### Google OAuth (вход через Google)

Сообщение `{"detail":"Google OAuth не настроен"}` значит: на сервере **не задан** `GOOGLE_CLIENT_ID` (или оба id и secret).

1. [Google Cloud Console](https://console.cloud.google.com/) → проект → **APIs & Services** → **Credentials** → **Create credentials** → **OAuth client ID** → тип **Web application**.
2. **Authorized redirect URIs** (обязательно, без слэша в конце):

   ```
   https://consilium-next-production.up.railway.app/api/auth/google/callback
   ```

   Замените домен на ваш Railway-домен, если другой.

3. В **Railway → Variables** добавьте:

   | Переменная | Значение |
   |------------|----------|
   | `GOOGLE_CLIENT_ID` | `....apps.googleusercontent.com` |
   | `GOOGLE_CLIENT_SECRET` | секрет из Google |
   | `GOOGLE_REDIRECT_URI` | тот же callback URL, что в п.2 |

4. Перезапуск деплоя → проверка: `GET https://ваш-домен/api/health` → `"google_oauth_configured": true`.

5. Кнопка **Google** на `/auth.html` появится только когда `google_oauth_configured` true.

Пока переменных нет — используйте **email + пароль** (регистрация на `/auth.html`).
| Регистрация без письма | В dev ссылки могут быть в логах сервера; для прода настройте SMTP в `.env` |

## Структура репозитория

```
consilium-next/
  app/           # FastAPI: auth, billing, orchestrator, OpenRouter client
  static/        # UI (HTML/JS/CSS)
  data/          # SQLite + verified models list (в git — json, db нет)
  tests/         # pytest
  scripts/       # утилиты (probe моделей и др.)
```

Файл `.env` в git не коммитится.

## Лицензия

Лицензия не указана — при использовании кода уточните у владельца репозитория.
