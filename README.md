# Consilium-Next

Мульти-агентный «совет» с auth, гостевой пробой, биллингом (OpenRouter × 1.4) и Stripe.

Стабильная копия без auth — в репозитории [consilium](../) (локально `../`).

## Локально

```powershell
cd consilium-next
.\run.ps1
```

- UI: http://127.0.0.1:8001  
- Вход: http://127.0.0.1:8001/auth.html  
- Аккаунт: http://127.0.0.1:8001/account.html  

Скопируйте `.env.example` → `.env`, вставьте `OPENROUTER_API_KEY`.

## Тесты

```powershell
pip install -r requirements.txt
python -m pytest tests -q
```

## Деплой (проще всего — Railway)

**Почему Railway:** один клик из GitHub, Docker уже есть, **Volume** для SQLite (`data/`), не нужен отдельный Postgres на старте.

| Платформа | Плюсы | Минусы |
|-----------|--------|--------|
| **[Railway](https://railway.app)** | GitHub → Deploy, volume, env в UI | ~$5/мес после trial |
| [Render](https://render.com) | Похожий UI | Persistent disk только на платных планах |
| Fly.io | Быстро, volume | Нужен CLI `flyctl` |
| VPS | Полный контроль | Настройка nginx, SSL, бэкапы сами |

### Railway — по шагам

1. Запушьте этот репозиторий на GitHub (см. ниже).
2. [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub** → выберите `consilium-next`.
3. **Variables** (Settings → Variables):

   | Переменная | Значение |
   |------------|----------|
   | `ENVIRONMENT` | `production` |
   | `MASTER_MODE` | `false` |
   | `OPENROUTER_API_KEY` | ваш ключ |
   | `OPENROUTER_APP_URL` | `https://ВАШ-домен.up.railway.app` |
   | `APP_PUBLIC_URL` | тот же URL |
   | `JWT_SECRET` | `openssl rand -hex 32` |
   | `GOOGLE_CLIENT_ID` / `SECRET` | при OAuth |
   | `GOOGLE_REDIRECT_URI` | `https://ВАШ-домен.../api/auth/google/callback` |
   | `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` | при оплате |

4. **Volume** → Mount path: `/app/data` (иначе SQLite и загрузки пропадут при рестарте).
5. **Stripe webhook:** URL `https://ВАШ-домен/api/billing/stripe/webhook`, событие `checkout.session.completed`.
6. **Networking** → сгенерировать домен → проверить `https://.../api/health`.

`PORT` Railway подставляет сам; Dockerfile уже слушает `0.0.0.0`.

### Docker локально

```bash
docker build -t consilium-next .
docker run -p 8001:8000 --env-file .env -v consilium-data:/app/data consilium-next
```

## GitHub

```powershell
cd consilium-next
git add .
git commit -m "Consilium-Next: auth, billing, security, tests"
git branch -M main
git remote add origin https://github.com/ВАШ_ЛОГИН/consilium-next.git
git push -u origin main
```

Не коммитьте `.env` — он в `.gitignore`.

## API (кратко)

- Auth: `/api/auth/register`, `login`, `refresh`, `me`, Google OAuth  
- Billing: `/api/billing/balance`, `stripe/checkout`, `stripe/webhook`  
- Совет: `POST /api/run/stream` (multipart), SSE  
