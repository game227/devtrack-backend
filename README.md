# DevTrack Backend

Django + Django REST Framework API for DevTrack, served under `/api/v1/`.
DevTrack is three separate repositories that only talk over HTTP:

| Repo | Role |
|---|---|
| **devtrack-backend** (this one) | REST API, PostgreSQL, GitHub integration |
| [devtrack-frontend](https://github.com/game227/devtrack-frontend) | React SPA (Uzbek + English) and landing page |
| [devtrack-telegram-bot](https://github.com/game227/devtrack-telegram-bot) | Telegram bot service (account linking, password-reset delivery) |

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in SECRET_KEY / DATABASE_URL / FIELD_ENCRYPTION_KEY
python manage.py migrate
python manage.py seed_demo   # optional: realistic demo workspace, sign in as jane.dev / demo1234
python manage.py runserver
```

`seed_demo` is idempotent (`--reset` recreates it). Never run it against a database with real users
you care about.

## Tests

```bash
python manage.py test --keepdb --noinput
```

CI (`.github/workflows/ci.yml`) runs the same suite on PostgreSQL and also fails if a model change is
missing its migration.

## Features

Auth (JWT with refresh rotation), workspaces and roles, projects, issues and kanban statuses, labels,
comments and @mentions, notes, teams, cycles, milestones, activity timeline, notifications, search,
rule-based project health (with structured, localizable risks), developer analytics, dashboard.

- **GitHub**: OAuth connect, per-project repository link, webhook (HMAC-SHA256). `#<issue id>` in a
  commit or pull request links it to the issue; a merged PR moves the issue to Done and is logged once.
- **Telegram**: password-reset links go to Telegram first (if linked) and fall back to email; if the bot
  service is down the request still succeeds via email.
- **Password reset messages** are sent in the UI language (`lang`: `en` or `uz`) and delivered on a
  background thread in production.

## GitHub: connect, import, link

1. **Connect** (Settings → GitHub): needs a GitHub OAuth App whose *Authorization callback URL* is exactly
   `GITHUB_CALLBACK_URL` (locally `http://localhost:8000/api/v1/integrations/github/callback/`).
2. **Import a repository as a project** (Projects → Import from GitHub): creates the project, links the
   repo and imports its issues (up to 300, pull requests excluded). Imported issues keep GitHub's numbers, so
   `#12` in a commit or pull request means GitHub's issue 12 in such a project.
3. **Link a repository to an existing project** (project page → GitHub).

**Live updates need a public URL.** GitHub cannot call `localhost`, so locally the link is created
*without* a webhook (the UI says so) and **Sync now** pulls recent pull requests and commits instead. To get
real webhooks in development, expose the backend with a tunnel and set the webhook URL before linking:

```bash
cloudflared tunnel --url http://localhost:8000     # or: ngrok http 8000
# .env
GITHUB_WEBHOOK_CALLBACK_URL=https://<tunnel-host>/api/v1/integrations/github/webhook/
GITHUB_WEBHOOK_SECRET=<any long random string>
```

Creating a webhook also needs admin rights on the repository; without them the repo is still linked and can
be synced manually.

## Configuration

See `.env.example`. Notable settings:

| Variable | Purpose |
|---|---|
| `FIELD_ENCRYPTION_KEY` | Fernet key(s) for GitHub tokens at rest; comma-separated for rotation |
| `GITHUB_OAUTH_SCOPE` | Scopes requested from GitHub (default `repo`) |
| `BOT_SERVICE_API_KEY`, `TELEGRAM_LINK_SECRET` | Must equal the same values in devtrack-telegram-bot |
| `SECURE_HSTS_SECONDS` | Production HSTS, off (`0`) by default |
| `PASSWORD_RESET_ASYNC` | Background reset delivery (on in production) |

### Rotating secrets

1. **Encryption key**: put the new key first — `FIELD_ENCRYPTION_KEY="<new>,<old>"` — deploy, run
   `python manage.py rotate_encryption_key`, then drop the old key.
2. **Bot secrets**: change `BOT_SERVICE_API_KEY` and `TELEGRAM_LINK_SECRET` on both services together.
3. **GitHub OAuth secret / webhook secret / Resend key**: replace in the environment and redeploy.

## Docker

```bash
cp .env.example .env
docker compose up --build
```

Runs Postgres and the API (gunicorn, `DEBUG=False`) on `localhost:8000`; migrations run on start.

## Deployment

`render.yaml` is a Render Blueprint for the backend, the bot (persistent disk, so a paid plan) and the
frontend, with the shared bot secrets generated once and injected into both services.

## Layout

- `config/` — settings (`config/settings/{base,dev,prod}.py`), root URLconf
- `apps/` — one Django app per domain area, namespaced `apps.<name>`
