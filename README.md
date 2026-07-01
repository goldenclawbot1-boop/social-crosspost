# Social CrossPost — Multi-Platform Social Media Publisher

Publish to Telegram, Twitter/X, Facebook, Instagram, TikTok, LinkedIn, YouTube, and Pinterest from one dashboard.

## Quick Start

```bash
# Clone and setup
cd social-crosspost
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your platform credentials

# Run
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000

## Supported Platforms

| Platform | Auth | Status |
|----------|------|--------|
| Telegram | Bot Token | ✅ Ready |
| Twitter/X | OAuth 2.0 PKCE | ✅ Ready |
| Facebook | OAuth 2.0 | ✅ Ready |
| Instagram | OAuth 2.0 (via FB) | ✅ Ready |
| TikTok | OAuth 2.0 | 🔜 Planned |
| LinkedIn | OAuth 2.0 | 🔜 Planned |
| YouTube | OAuth 2.0 | 🔜 Planned |
| Pinterest | OAuth 2.0 | 🔜 Planned |

## Features

- **Multi-platform publishing** — Compose once, publish everywhere
- **Media support** — Images, videos, carousels (platform-dependent)
- **Scheduling** — One-time and recurring posts with cron expressions
- **Multi-user** — Each user connects their own accounts
- **Enterprise UI** — Clean, professional dashboard with Tailwind CSS
- **HTMX + Alpine.js** — Reactive UI without heavy JS frameworks
- **Audit logging** — Track all actions

## Tech Stack

- **Backend:** FastAPI (Python 3.12)
- **Database:** SQLite (WAL mode)
- **Frontend:** Tailwind CSS + HTMX + Alpine.js
- **Auth:** JWT (access + refresh tokens)
- **Deploy:** Render / Docker

## Environment Variables

See `.env.example` for all configuration options.

### Required for each platform:

- **Telegram:** `TELEGRAM_BOT_TOKEN` (from @BotFather)
- **Twitter/X:** `TWITTER_CLIENT_ID` + `TWITTER_CLIENT_SECRET` (X Developer Portal)
- **Facebook/Instagram:** `META_APP_ID` + `META_APP_SECRET` (Meta Developer)

## Project Structure

```
social-crosspost/
├── app/
│   ├── main.py              # FastAPI app
│   ├── config.py            # Settings
│   ├── database.py          # SQLite + migrations
│   ├── auth.py              # JWT auth
│   ├── templates.py         # Jinja2 setup
│   ├── adapters/            # Platform adapters
│   │   ├── base.py          # Abstract adapter
│   │   ├── telegram.py      # Telegram Bot API
│   │   ├── twitter.py       # X API v2
│   │   ├── facebook.py      # Facebook Graph API
│   │   └── instagram.py     # Instagram Graph API
│   ├── routers/             # API routes
│   │   ├── auth.py          # Login/register
│   │   ├── platforms.py     # Platform connections
│   │   ├── posts.py         # Post CRUD + publish
│   │   ├── media.py         # Media upload
│   │   └── schedules.py     # Scheduling
│   ├── services/
│   │   └── publisher.py     # Multi-platform publish engine
│   └── templates/           # Jinja2 HTML templates
├── static/                  # CSS/JS
├── uploads/                 # Local media storage
├── requirements.txt
├── Dockerfile
├── render.yaml
└── .env.example
```
