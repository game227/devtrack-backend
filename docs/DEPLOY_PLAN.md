# Deploy plan for the `security-hardening` branches

**Status:** planned, not executed. Nothing has been pushed or deployed. Both repositories have a local
`security-hardening` branch (backend and frontend). This page is the checklist for when the time comes.

## 1. Before anything leaves this machine

1. **Back up the production database** by hand, even if the scheduled backup is already running:
   `DATABASE_URL=<production> ./scripts/backup.sh` (or `python manage.py backup_database --local-dir ./backups`).
2. **Check production data for case-variant duplicates.** Migration `accounts.0006` adds case-insensitive
   uniqueness and stops the deploy with a list if two accounts collide:

   ```sql
   select lower(username), count(*) from accounts_user group by 1 having count(*) > 1;
   select lower(email), count(*) from accounts_user where email <> '' group by 1 having count(*) > 1;
   ```

   Merge or rename any rows these return before deploying.
3. Confirm `FIELD_ENCRYPTION_KEY` is set on the web service. Two-factor secrets are now encrypted with it,
   as well as GitHub tokens.
4. **GitHub OAuth app.**
   - The client secret was shared in a chat on 2026-11-13. Generate a new client secret before
     production use, and keep it only in the Render environment (`GITHUB_CLIENT_SECRET`).
   - An OAuth app has a single callback URL, so use one app for local development (callback
     `http://localhost:8000/api/v1/integrations/github/callback/`) and another for production (callback
     = `GITHUB_CALLBACK_URL` in `render.yaml`).
   - `GITHUB_WEBHOOK_SECRET` must be set too: `check --deploy` fails without it once
     `GITHUB_CLIENT_ID` is set.

## 2. Order

1. Push the **backend** branch first, then the frontend one. The frontend CI checks out the backend
   branch with the same name, so its end-to-end job tests the pair together.
2. When both CIs are green, merge the **backend** into `master` first. Render deploys it, and the
   `preDeployCommand` runs the migrations below. Then merge the **frontend**.
   - An older frontend keeps working against the new backend, except "Connect GitHub". The backend now
     requires the browser nonce, so connecting fails until the frontend is deployed. Deploy the two close
     together.
   - The new frontend's board needs the new `exclude_status`/`completed_at` API. Do not ship the
     frontend first.

### Migrations that run on deploy

| Migration | What it does | Risk |
|---|---|---|
| `accounts.0005` | Random avatar file names (code-only change) | none |
| `accounts.0006` | Case-insensitive unique username/email | stops if duplicates exist (step 1.2) |
| `accounts.0007` | Two-factor fields | additive |
| `projects.0006` | `issue_counter` | additive |
| `issues.0005` | `number`, backfilled per project (GitHub numbers kept) | time grows with the issue count |
| `issues.0006` | `number` required + unique per project | none after 0005 |
| `issues.0007` | `completed_at`, backfilled from `updated_at` for done issues | additive |
| `workspaces.0003` | Invitations table | additive |
| `integrations.0004` | Parked GitHub authorizations (OAuth flow bound to the browser) | additive |
| `live.0001` | Per-workspace change clock for live updates | additive |
| `activities.0002`, `integrations.0005` | Admin display names only (no schema change) | none |
| `issues.0008` | Saved views (named issue-list filters) | additive |

The data migrations were tested against real data (see `apps/issues/test_numbers.py`) and applied to
the development database. Several of them add required columns (`issues.number`,
`projects.issue_counter`, the two-factor fields), so the **previous** code cannot insert rows into the new
schema. That is why rolling back needs the steps in section 6, not just a redeploy.

## 3. Render settings to add or change

| Where | Variable | Value / how |
|---|---|---|
| web | `ADMIN_URL` | a long random path, e.g. `python -c "import secrets;print(secrets.token_urlsafe(24))"` + `/` |
| web | `NUM_PROXIES` | **Verify first.** Render appends to `X-Forwarded-For` rather than replacing it. Log `REMOTE_ADDR` and `X-Forwarded-For` for a request from a known IP, count the hops added after the client's address, and set that number |
| web | `CACHE_URL` | only if running more than one worker/instance (`dbcache://django_cache` + `manage.py createcachetable` in `preDeployCommand`) |
| web | `SECURE_HSTS_SECONDS` | once the domain is stable: 3600, then 86400 a week later, then 31536000 |
| cron `devtrack-db-backup` | `BACKUP_BUCKET`, `BACKUP_ENDPOINT_URL`, `BACKUP_ACCESS_KEY`, `BACKUP_SECRET_KEY`, `SECRET_KEY` | a dedicated bucket (versioning/object lock on), with keys limited to it — see docs/BACKUP.md |

The backup cron job is new in `render.yaml`. It is built from `Dockerfile.backup` and runs on a paid
plan (`starter`), like the digest job.

## 4. Telegram bot service (separate repository, not reviewed here)

Check these against the bot before or with the backend deploy:

- `can_edit` in the bot API now means "creator **or assignee**" (the "Done" button may appear more often).
- Issues have a per-project `number`. The bot can show `#number`, while links still use the global `id`.
- Adding someone to a workspace now creates an **invitation**. If the bot adds members, it must handle the
  `201` invitation response (the invitee accepts in the web app).
- The backend refuses to mint link tokens without `TELEGRAM_LINK_SECRET`. The bot's copy must match.

## 5. After the deploy

- `GET /api/v1/health/` returns 200 with `Cache-Control: no-store` and `Content-Security-Policy`.
- The admin opens at the new `ADMIN_URL`, and `/admin/` returns 404.
- In the browser: sign in, turn two-factor on and off, accept an invitation, move a card, expand Done.
  The console shows no CSP violations.
- `python manage.py check --deploy` on the service shell shows no errors.
- The day after: the backup job's log shows an upload. Rehearse a restore into a scratch database
  (docs/BACKUP.md).

## 6. Rolling back

The previous code does not know the new migrations, so reverse them **while the new code is still
deployed** (from its shell), then redeploy the previous release:

```bash
python manage.py migrate issues 0004  # also drops saved views (0008)
python manage.py migrate projects 0005
python manage.py migrate workspaces 0002
python manage.py migrate accounts 0004
python manage.py migrate integrations 0003
python manage.py migrate live zero
python manage.py migrate activities 0001
```

This was rehearsed on a seeded copy: all eight migrations reverse cleanly, and the `master` code then
creates users and issues normally. Reversing drops the new data: issue numbers, completion times,
invitations and two-factor settings. If that matters, restore the backup from step 1.1 instead.

## 7. Live updates, stage 2 (planned)

Today the SPA asks `/changes/` every 10 s while the tab is visible. To get ~1 s updates:

1. Serve Django under ASGI (gunicorn with uvicorn workers, or daphne). A long-lived stream would tie up a
   sync gunicorn worker per open tab.
2. Add `GET /api/v1/events/` as a server-sent-events stream. A post-commit hook on `touch()` publishes
   `NOTIFY workspace_<id>, '<area>'`; the stream `LISTEN`s with an async psycopg connection. This is
   PostgreSQL only, with no Redis.
3. Authenticate the stream with a single-use, short-lived ticket from an authenticated `POST`, because
   `EventSource` cannot send an `Authorization` header. Membership is checked when the stream opens and
   rechecked on every event.
4. Keep `/changes/` as the fallback while the stream is down, so nothing regresses if it fails.

Render: the web service's start command changes. Measure memory per open stream before raising the plan.

## 8. Deliberately left for later

- A custom domain shared by the frontend and the API would allow an httpOnly refresh cookie (instead of
  `localStorage`) and a simpler CSP `connect-src`.
- A CSP `report-to` endpoint, so production violations are seen.
- `SENTRY_DSN` / `VITE_SENTRY_DSN` once an account exists.
