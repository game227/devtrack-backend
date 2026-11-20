# DevTrack quick start

From nothing to a running DevTrack on your machine in about ten minutes. DevTrack is two repositories,
cloned side by side:

```
devtrack/
├── devtrack-backend/    Django + DRF API (this repository)
└── devtrack-frontend/   React + Vite web app
```

## 1. What you need

| Tool | Version | Check |
|---|---|---|
| Git | any recent | `git --version` |
| Python | 3.14 | `python3 --version` |
| Node.js | 24 | `node --version` |
| Docker | any recent (for PostgreSQL) | `docker --version` |

## 2. Get the code

```bash
mkdir devtrack && cd devtrack
git clone https://github.com/game227/devtrack-backend.git
git clone https://github.com/game227/devtrack-frontend.git
```

## 3. Start the database

PostgreSQL in Docker, published on this machine only:

```bash
docker run -d --name devtrack-db \
  -e POSTGRES_DB=devtrack -e POSTGRES_USER=devtrack -e POSTGRES_PASSWORD=devtrack \
  -p 127.0.0.1:5432:5432 -v devtrack_pg:/var/lib/postgresql/data \
  postgres:18-alpine
```

Next time, `docker start devtrack-db` is enough; the data stays in the `devtrack_pg` volume.

## 4. Backend (API on http://localhost:8000)

```bash
cd devtrack-backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

Fill in these lines of `.env` (everything else can stay empty for local work):

```bash
SECRET_KEY=          # python -c "import secrets; print(secrets.token_urlsafe(50))"
DEBUG=True
DATABASE_URL=postgres://devtrack:devtrack@localhost:5432/devtrack
CORS_ALLOWED_ORIGINS=http://localhost:5173
FIELD_ENCRYPTION_KEY=  # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Then create the tables, an account, and start the server:

```bash
python manage.py migrate
python manage.py createsuperuser      # your own account (also opens the Django admin)
python manage.py runserver
```

Want something to look at first? `python manage.py seed_demo` fills the database with a demo workspace
(sign in as `jane.dev` / `demo1234`). Use it only on a database you can throw away, never next to real
users.

## 5. Frontend (app on http://localhost:5173)

In a second terminal:

```bash
cd devtrack-frontend
npm install
cp .env.example .env     # VITE_API_BASE_URL=http://localhost:8000/api/v1 already points at step 4
npm run dev
```

Open http://localhost:5173, choose **Sign in**, and use the account from step 4. The interface speaks
Uzbek, Russian and English (switch on the landing page, or later in Settings).

## 6. First steps in the app

The home page shows **getting-started steps**, ticked off as you go:

1. **Create a project**: Projects → New project.
2. **Add an issue**: the **New issue** button (or press `C`).
3. **Invite your team**: Members → invite by username (shared workspaces only).
4. **Connect GitHub** (optional, needs the `GITHUB_*` values in `.env`): link a repository on the
   project page; write `fixes #12` in a commit and issue #12 moves to Done by itself.

Handy keys: `Ctrl K` search and commands, `?` all shortcuts, `G` then `P` projects.

## 7. Check that everything works

```bash
# backend
cd devtrack-backend && python manage.py test --noinput && ruff check .
# frontend
cd devtrack-frontend && npm test && npm run lint && npm run build
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `connection refused` on port 5432 | The database is not running: `docker start devtrack-db` |
| `SECRET_KEY` / `ImproperlyConfigured` on start | `.env` is missing or a value from step 4 is empty |
| The app loads but every request fails (CORS) | `CORS_ALLOWED_ORIGINS` must contain `http://localhost:5173` exactly |
| `manage.py test` stops at a question | Add `--noinput` (an old test database is left over) |
| Port 8000 or 5173 already in use | `runserver 8001` / `npm run dev -- --port 5174`, and update `VITE_API_BASE_URL` and CORS |

## Where to read more

- `README.md` (both repositories): features, API, design system, conventions.
- `SECURITY.md`: what is protected and how.
- `docs/DEPLOY_PLAN.md`: going to production (Render), migrations, settings, rollback.
