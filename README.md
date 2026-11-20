# DevTrack Backend

Django + Django REST Framework API for DevTrack, served under `/api/v1/`.
DevTrack is three separate repositories that only talk over HTTP:

| Repo | Role |
|---|---|
| **devtrack-backend** (this one) | REST API, PostgreSQL, GitHub integration |
| [devtrack-frontend](https://github.com/game227/devtrack-frontend) | React SPA (Uzbek, Russian, English) and landing page |
| [devtrack-telegram-bot](https://github.com/game227/devtrack-telegram-bot) | Telegram bot service (account linking, password-reset delivery) |

## Setup

New here? [QUICKSTART.md](QUICKSTART.md) walks through the database, the API and the web app together.


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
- **Managing members** (owner/admin): change roles (`PATCH /workspaces/<id>/members/<user>/`, owner only),
  remove (`DELETE`, admins remove members only), `POST /workspaces/<id>/leave/`, and
  `POST /workspaces/<id>/transfer-ownership/`. Removing or leaving drops that person's project and team
  memberships there and unassigns their open issues. Every change appears in the activity feed. The rules
  are in `apps/workspaces/membership.py`.
- **Live updates**: `GET /changes/?workspace=<id>&since=<cursor>` names what changed (issues, projects,
  members, and the caller's notifications/invitations), never the data itself. The SPA asks every 10 s
  while visible and refetches only those parts (`apps/live`).
  With an ASGI server, `POST /changes/ticket/` hands out a 60-second single-use ticket that opens
  `GET /changes/stream/?ticket=` (server-sent events, a check every 2 s, membership rechecked each time,
  5 minutes per connection). `POST /changes/presence/ {issue}` is a heartbeat that answers who else has
  the issue open (kept in the cache).
- **Two-factor authentication**: `/auth/2fa/setup|enable|disable/`; sign-in then needs `otp`.
- **CSV export**: `GET /issues/export/?project=<id>` (or `workspace=<id>`) takes the issue list's filters and
  `lang` (`en`/`uz`/`ru`) and streams up to 10,000 rows. Cells that a spreadsheet would run as a formula
  are prefixed with `'`; 30 exports per user per hour (`issue_export`).
- **Checklists**: `GET|POST /issues/<id>/checklist/`, `PATCH|DELETE /issues/checklist/<item>/` (up to 100
  steps). Every issue carries `checklist: {done, total}` (null when empty) for list rows and cards.
- **Links between issues**: `GET|POST /issues/<id>/relations/` with `kind` (`blocks`, `duplicates`,
  `relates`) and `target_id` (same workspace), `DELETE /issues/relations/<id>/`. A link is stored once and
  listed from both ends with `direction` (`out`/`in`); a mirror of an existing link is refused, so two
  issues can never block each other.
- Checklist and links are read by any workspace member and changed by the issue's creator or assignee.
- **Estimates and burndown**: issues take an optional `estimate` (story points, 0-100).
  `GET /cycles/<id>/burndown/` returns the work left at the end of each cycle day (points, or issues when
  nothing is estimated) next to the ideal line; future days are `null`.
- **Attachments**: `GET|POST /issues/<id>/attachments/` (multipart `file`), `DELETE /issues/attachments/<id>/`,
  `GET /issues/attachments/<id>/download/`. Images (PNG, JPEG, GIF, WebP), PDF and plain text only, decided
  from the file's bytes and matched against its extension; up to `ATTACHMENT_MAX_BYTES` (10 MB) each and
  20 per issue; 60 uploads per user per hour. Stored under random names and only ever sent through the
  API to workspace members, as a download (`nosniff`, sandbox CSP). Any member may attach; the uploader,
  the issue's creator or an admin may remove.
- **Demo mode** (off unless `DEMO_ENABLED=true`): `POST /demo/` (5 per IP per hour) creates a throwaway
  account with two sample teammates and a seeded workspace, and returns its tokens. Demo accounts cannot
  invite, use GitHub or Telegram, change email/password/2FA or their profile, or upload files
  (`apps/demo/authentication.py`). They expire after `DEMO_TTL_HOURS` (24); `manage.py cleanup_demo`
  deletes them with everything they own, and at most `DEMO_MAX_ACTIVE` (200) run at once.
- **Web Push**: `GET /notifications/push/`, `POST /notifications/push/subscribe/|unsubscribe/`. Every in-app
  notification also goes to the user's subscribed browsers, worded in the language chosen when
  subscribing. Off until `WEB_PUSH_VAPID_PUBLIC_KEY`/`WEB_PUSH_VAPID_PRIVATE_KEY` are set
  (`manage.py generate_vapid_keys`); only the browser vendors' push services are accepted as endpoints,
  and subscriptions the service reports gone are deleted.
- **Share links**: `GET|POST /issues/<id>/share/` (`days`: 1, 7 or 30) by the creator, assignee or an admin;
  `DELETE /issues/share-links/<id>/` revokes. `GET /issues/shared/<token>/` (no sign-in, 60/min per IP) shows
  title, status, description, assignee's username and checklist only. The links people copy go through
  `GET /s/<token>?lang=uz|en|ru` (outside `/api`): Open Graph tags for chat apps such as Telegram, a
  1200x630 card at `/s/<token>/card.png` drawn with Pillow (Geist, bundled under
  `apps/issues/share_fonts/`, SIL OFL), and an immediate redirect to the app's `/share/<token>`. Both
  answer only while the link is live, with the same throttle.
- **Favorites**: `PUT|DELETE /projects/<id>/favorite/` stars or unstars a project for the signed-in user
  (any workspace member); project rows carry `is_favorite`, and the list also `weekly_done` (issues
  finished in each of the last 8 weeks, oldest first).
- **Emails** (password reset, email verification, weekly digest) are sent as plain text with a branded
  HTML part (`apps/common/mail.py`: tables and inline styles, no images; every name is escaped).
- **Recurring issues**: `GET|POST /issues/recurring/project/<id>/`, `PATCH|DELETE /issues/recurring/<id>/`
  (project owner or admin to change). `manage.py create_recurring_issues` (daily) opens the due ones.
- **Bulk changes**: `POST /issues/bulk/ {ids, changes}` with status, priority, assignee_id, cycle or
  milestone; each issue is checked like a single edit and the rest are reported as skipped.
- **Time tracking**: `GET|POST /issues/<id>/time/` (minutes, note, spent_on), `DELETE /issues/time/<id>/` (own).
- **History**: field changes (title, priority, type, assignee, due date, estimate, cycle, milestone) are
  logged as `changed_issue`; `GET /activities/?issue=<id>` lists an issue's history with its comments.
- **WIP limits**: `wip_limits` on a project, e.g. `{"in_progress": 5}`; the board warns past it.
- **Weekly digest**: `manage.py send_weekly_digest` (Monday) emails owners and admins who keep
  `weekly_digest` on; language from `DIGEST_LANGUAGE` (default `uz`).
- **Saved views**: `GET|POST /issues/views/?project=<id>|workspace=<id>`, `PATCH|DELETE /issues/views/<id>/`.
  A named set of list filters (`status`, `type`, `priority`, `assignee`, `label`), private to its owner,
  up to 30 per list. The SPA keeps the current filters in the URL, so a filtered list can be shared.
- **Backups**: `manage.py backup_database` (scheduled on Render, see docs/BACKUP.md).
- **Who can edit an issue**: its creator (everything) and its assignee (status and priority only);
  workspace admins can delete it. Anyone who leaves a workspace loses these rights.
- **Telegram**: password-reset links go to Telegram first (if linked) and fall back to email; if the bot
  service is down the request still succeeds via email.
- **Password reset messages** are sent in the UI language (`lang`: `en`, `uz` or `ru`) and delivered on a
  background thread in production.

## GitHub: connect, import, link

1. **Connect** (Settings → GitHub): needs a GitHub OAuth App whose *Authorization callback URL* is exactly
   `GITHUB_CALLBACK_URL` (locally `http://localhost:8000/api/v1/integrations/github/callback/`; use separate
   apps for development and production). The flow is bound to the browser that starts it (a nonce it
   keeps), and the callback only parks the result until that browser claims it via
   `POST /integrations/github/complete/`. Disconnecting revokes the token at GitHub.
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


## Django admin

The admin (at `ADMIN_URL`) wears the web app's design: `apps/adminui` overrides the admin's base, sign-in
and front-page templates and adds `static/devtrack_admin/admin.css` (the app's tokens mapped onto the
admin's CSS variables, with self-hosted Geist fonts). The front page shows the headline figures and every
issue on the line, one station per status, each linking to its filtered list. The ModelAdmins show status
and priority as chips, with filters, search and raw-id inputs; the activity and notification logs are
read-only, and two-factor secrets and GitHub tokens are never shown. Create the first account with
`python manage.py createsuperuser`.

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
