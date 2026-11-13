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
pip install -r requirements-dev.txt   # the app plus test/lint tools (requirements.txt alone in production)
cp .env.example .env   # fill in SECRET_KEY / DATABASE_URL / FIELD_ENCRYPTION_KEY
python manage.py migrate
python manage.py seed_demo   # optional: realistic demo workspace, sign in as jane.dev / demo1234
python manage.py runserver
```

`seed_demo` is idempotent (`--reset` recreates it). Never run it against a database with real users
you care about.

## Tests and checks

```bash
python manage.py test --parallel --noinput   # ~5 s; serial runs work too
ruff check .                                 # lint, including flake8-bandit security rules
coverage run manage.py test --noinput && coverage report   # fails under 90 % (see .coveragerc)
```

`manage.py test` always uses `config/settings/test.py`: hermetic (nothing from your `.env` leaks in —
`PASSWORD_RESET_ASYNC=true` there used to make email assertions race), a fast password hasher, and no
outbound calls. `tblib` (in `requirements-dev.txt`) lets `--parallel` report a failing test instead of
crashing with `cannot pickle 'traceback' object`.

CI (`.github/workflows/ci.yml`) runs ruff, the suite with the coverage floor on PostgreSQL,
`makemigrations --check`, `pip-audit`, and `check --deploy` against the production settings, which fails
on a missing or weak secret (see `apps/common/checks.py`).

## Features

Auth (JWT with refresh rotation), workspaces and roles, projects, issues and kanban statuses, labels,
comments and @mentions, notes, teams, cycles, milestones, activity timeline, notifications, search,
rule-based project health (with structured, localizable risks), developer analytics, dashboard.

- **GitHub**: OAuth connect, per-project repository link, webhook (HMAC-SHA256). `#<number>` in a
  commit or pull request links it to that issue of the linked project; a merged PR moves the issue to
  Done and is logged once.
- **Issue numbers**: every issue has a number within its project (`#1`, `#2`, ...), shown in the UI and
  used for `#<number>` references. Numbers are never reused, even after a delete.
- **Workspace invitations**: adding someone (`POST /workspaces/<id>/members/`) invites them; they accept or
  decline at `/workspaces/invitations/` (the dashboard shows pending ones). Admins list or withdraw
  pending invitations at `/workspaces/<id>/invitations/`.
- **Two-factor authentication**: `/auth/2fa/setup|enable|disable/`; sign-in then needs `otp`.
- **Backups**: `manage.py backup_database` (scheduled on Render, see docs/BACKUP.md).
- **Who can edit an issue**: its creator (everything) and its assignee (status and priority only);
  workspace admins can delete it. Anyone who leaves a workspace loses these rights.
- **Telegram**: password-reset links go to Telegram first (if linked) and fall back to email; if the bot
  service is down the request still succeeds via email.
- **Password reset messages** are sent in the UI language (`lang`: `en` or `uz`) and delivered on a
  background thread in production.

## GitHub: connect, import, link

1. **Connect** (Settings → GitHub): needs a GitHub OAuth App whose *Authorization callback URL* is exactly
   `GITHUB_CALLBACK_URL` (locally `http://localhost:8000/api/v1/integrations/github/callback/`).
2. **Import a repository as a project** (Projects → Import from GitHub): creates the project, links the
   repo and imports its issues (up to 300, pull requests excluded). Imported issues keep GitHub's numbers, so
   `#12` in a commit or pull request means GitHub's issue 12 in such a project; issues created in DevTrack
   afterwards continue after the highest imported number.
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
| `NUM_PROXIES` | Reverse proxies in front of the app, so per-IP throttles read the real client address from `X-Forwarded-For`. Unset, DRF trusts the whole header (spoofable). Verify the hop count on your host before setting it |
| `ADMIN_URL` | Path of the Django admin (default `admin/`); set a long random one in production |
| `CACHE_URL` | Throttle counters' cache (default per-process memory); use a shared one (`dbcache://django_cache` + `createcachetable`, or Redis) with several workers |
| `MAX_UPLOAD_BYTES` | Largest multipart request accepted (default 3 MB) |
| `SECURE_SSL_REDIRECT` | Production default `True`; only `docker-compose.yml` (plain HTTP on localhost) turns it off |

### Rotating secrets

1. **Encryption key**: put the new key first — `FIELD_ENCRYPTION_KEY="<new>,<old>"` — deploy, run
   `python manage.py rotate_encryption_key`, then drop the old key.
2. **Bot secrets**: change `BOT_SERVICE_API_KEY` and `TELEGRAM_LINK_SECRET` on both services together.
3. **GitHub OAuth secret / webhook secret / Resend key**: replace in the environment and redeploy.

## Docker

```bash
export SECRET_KEY=$(openssl rand -hex 32)   # required: compose refuses to start without it
docker compose up --build
```

Runs Postgres and the API (gunicorn, production settings) on `127.0.0.1:8000`; migrations run on start.
The image collects static files at build time and runs the app as an unprivileged user (the entrypoint
only hands the media volume to that user, then drops root).

## Deployment

`render.yaml` is a Render Blueprint for the backend, the bot (persistent disk, so a paid plan) and the
frontend, with the shared bot secrets generated once and injected into both services.

## Security

See [SECURITY.md](SECURITY.md) for the security model (tenancy rules, authentication, uploads, GitHub and
Telegram trust boundaries), the deployment checklist and the known residual risks.

## Layout

- `config/` — settings (`config/settings/{base,dev,prod}.py`), root URLconf
- `apps/` — one Django app per domain area, namespaced `apps.<name>`
