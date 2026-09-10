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

## Layout

- `config/` — settings (`config/settings/{base,dev,prod}.py`), root URLconf.
- `apps/` — one Django app per domain area (accounts, workspaces, projects,
  issues, comments, activities, analytics, teams, cycles, milestones,
  notifications, integrations). Namespaced as `apps.<name>` in
  `INSTALLED_APPS`.

## Status

Phase 1-2 scaffolding: project boots, all apps registered, `User` model
defined. No business logic yet beyond auth's user model — see
`/home/neo/.claude/plans/nifty-nibbling-alpaca.md` for the full roadmap.
