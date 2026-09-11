# DevTrack Backend

Django + Django REST Framework API for DevTrack. Serves `/api/v1/`. See the
frontend at `../devtrack-frontend` (separate repo — they only talk over REST).

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in SECRET_KEY / DATABASE_URL
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Docker

```bash
cp .env.example .env   # SECRET_KEY at minimum; DATABASE_URL is overridden by compose
docker compose up --build
```

Runs Postgres + the API (via gunicorn, `DEBUG=False`) on `localhost:8000`.
Migrations run automatically on container start. Media file serving under
`DEBUG=False` isn't wired up yet (needs whitenoise/nginx/object storage) —
that's Deployment-phase work, not this one.

## Layout

- `config/` — settings (`config/settings/{base,dev,prod}.py`), root URLconf.
- `apps/` — one Django app per domain area (accounts, workspaces, projects,
  issues, comments, activities, analytics, teams, cycles, milestones,
  notifications, integrations). Namespaced as `apps.<name>` in
  `INSTALLED_APPS`.

## Status

MVP (Phase 1-10) and most of V1 (Phase 11-15, GitHub integration excepted)
are done: auth, workspaces, projects, issues/kanban, labels, comments,
notes, teams, cycles, milestones, activity feed, notifications, search,
rule-based project health, developer analytics, dashboard, Docker. GitHub
integration and Deployment are intentionally not built — both need
credentials/decisions only the project owner can provide (a GitHub OAuth
App, a hosting choice). See `/home/neo/.claude/plans/nifty-nibbling-alpaca.md`
for the original roadmap.
