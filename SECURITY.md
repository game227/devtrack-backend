# Security

## Reporting a vulnerability

Please report it privately through GitHub's **Report a vulnerability** button (Security → Advisories) on
this repository rather than in a public issue.

## Security model

**Tenancy: the workspace is the boundary.** Every read and write checks the caller's *current* membership
of the workspace the object lives in.

- A parent never changes after creation: an issue's project, a project's / label's / team's workspace,
  a cycle's / milestone's project are read-only in the API (the view sets them on create).
- Everything an object points at must be in the same workspace: an issue's assignee (an active member),
  labels (the workspace's, or the issue's own project's), cycle and milestone (the issue's project); a
  project's team. Ids from elsewhere get the same "does not exist" answer as ids that were never there.
- Joining a workspace takes the invitee's consent: an admin's "add member" creates an invitation, and
  the person becomes a member (and sees anything) only after accepting it. Admins can withdraw it.
- Only workspace members can be added to its projects and teams; deactivated accounts cannot be added.
- Managing members follows one table (`apps/workspaces/membership.py`): only the owner changes roles or
  invites admins, admins remove plain members only, nobody removes the owner, and the owner leaves only
  after handing the workspace over. Leaving or being removed ends that person's project and team
  memberships there and unassigns their open work.
- `/changes/` only answers members, and only with area names ("issues changed"); everything is still
  read through the permission-checked endpoints.
- Someone removed from a workspace loses every right that came from being in it — including over issues
  and projects they created — and stops receiving its notifications (in-app and Telegram).
- Issue edits: the creator may change anything, the assignee only `status` and `priority`; admins and
  owners may delete but not edit someone else's issue. The Telegram bot API applies the same rules.

**Authentication**

- JWT: 15-minute access tokens, 14-day refresh tokens rotated on use and blacklisted afterwards.
  Changing or resetting a password, and deleting the account, revoke every outstanding refresh token
  (a password change hands the current session a fresh pair).
- Optional two-factor authentication (TOTP, RFC 6238): the secret is encrypted at rest, each code works
  once (replays are refused), ten single-use recovery codes are stored hashed, turning it on ends every
  password-only session, and turning it off needs the password and a code. Attempts are rate-limited.
- Passwords: Argon2 (older PBKDF2 hashes upgrade on next login) and Django's validators. Reset and
  email-verification links expire after a day and are single-use.
- Usernames and emails are unique case-insensitively, enforced by the database (the migration stops
  with a list if existing accounts collide); new usernames are ASCII-only (no look-alike letters).
- Rate limits: per IP (`anon`, `register`), and per *target* where an IP limit can be dodged — login
  attempts per account, password-reset emails per address — plus member invitations and manual GitHub
  syncs per user.

**Input handling**

- Ids from query strings and bodies are validated (`apps/common/lookup.py`): malformed input is a 400,
  never a 500. Malformed body shapes (lists, strings) are handled the same way.
- Uploads: multipart requests above `MAX_UPLOAD_BYTES` are refused before the body is read. Avatars
  must be JPEG/PNG/WebP, ≤ 2 MB and ≤ 16 MP; they are decoded and re-encoded (dropping EXIF such as GPS
  data and anything that is not pixels) and stored under a random name.
- The API renders only JSON in production (no browsable API). Responses under `/api/` carry
  `Cache-Control: no-store` and `Content-Security-Policy: default-src 'none'`.

**GitHub**

- Connecting is bound to the browser that started it. The OAuth `state` is signed and lasts 5
  minutes. It carries the hash of a random nonce that only that browser keeps. The callback links
  nothing: it parks the result, and the SPA claims it with the same user's credentials and that nonce
  within 10 minutes. A forwarded authorization link therefore never puts the victim's GitHub token on
  someone else's account; the parked token is discarded and revoked.
- Access tokens are encrypted at rest (Fernet, rotatable), and are revoked at GitHub on disconnect,
  on account deletion, on reconnecting as another GitHub user, and when a parked authorization is
  abandoned. A repository link uses the token of the member who linked it only while they are still an
  active member; otherwise it uses the requester's own token.
- Activity from GitHub is credited by GitHub's numeric user id (logins can be renamed and re-registered),
  and only ever to members of the workspace.
- Webhooks are verified with HMAC-SHA256 and rejected outright if no secret is configured; no webhook is
  created without one. GitHub being unreachable or answering garbage is handled as an error, not a 500.
- Only GitHub's own `access_denied` error code is passed back to the UI; the UI shows known codes only.
- Linking or importing a repository is checked against GitHub with the caller's own token: the id and
  name in the request must belong to a repository that token can read; GitHub's own name is stored.
- `#<number>` references only ever match issues of the linked project.

**Telegram**

- The bot service authenticates with `BOT_SERVICE_API_KEY` (constant-time comparison) and acts only as a
  user who linked their chat. Link tokens are HMAC-signed with `TELEGRAM_LINK_SECRET`; the server refuses
  to mint one if that secret is empty (otherwise anyone could link their chat to any account and receive
  its password-reset links).

**Frontend** (devtrack-frontend, policy in `render.yaml`)

- Content-Security-Policy without `'unsafe-inline'` for scripts: the one inline script is allowed by its
  SHA-256 hash, and the frontend CI fails if the two drift apart. `frame-ancestors 'none'`,
  `object-src 'none'`, `nosniff`, a strict referrer policy.
- No HTML is rendered from user content (`dangerouslySetInnerHTML` is not used anywhere).

**Operations**

- `python manage.py check --deploy` (run in CI against the production settings) fails on a short or
  placeholder `SECRET_KEY`, a missing `FIELD_ENCRYPTION_KEY`, a configured bot or GitHub app without its
  secrets, `ALLOWED_HOSTS = *` or open CORS.
- `config/wsgi.py` and `asgi.py` default to the production settings, so a forgotten environment variable
  cannot mean `DEBUG=True`. `seed_demo` (demo accounts with published passwords) refuses to run with
  `DEBUG` off.
- The container runs as an unprivileged user; static files are collected at build time.
- `pip-audit` and `npm audit` run in CI; Dependabot watches pip, npm, Docker and Actions.

## Deployment checklist

1. Set every secret (`SECRET_KEY` ≥ 32 random characters, `FIELD_ENCRYPTION_KEY`, the bot secrets,
   `GITHUB_WEBHOOK_SECRET`). `check --deploy` refuses a configuration that misses one.
2. Set `ADMIN_URL` to a long random path.
3. Find out how many proxies sit in front of the app and set `NUM_PROXIES`; until then per-IP limits
   can be dodged by forging `X-Forwarded-For` (the per-account and per-address limits still hold).
4. Running more than one gunicorn worker or instance? Point `CACHE_URL` at a shared cache, or each one
   keeps its own rate-limit counters.
5. Once HTTPS and the domain are stable, ramp `SECURE_HSTS_SECONDS` up (3600 → 86400 → 31536000).
6. Give the `devtrack-db-backup` cron job its bucket credentials (docs/BACKUP.md) and rehearse a restore.

## Known limitations

- The refresh token is kept in `localStorage`, so a successful XSS could read it; the strict CSP is the
  mitigation. An httpOnly cookie is not used because the frontend and the API are on different sites
  (`onrender.com` is a public suffix), where browsers increasingly block such cookies.
- Inviting by username lets a workspace admin learn whether a username exists (rate-limited).
- Repository links are first come, first served among people who can read the repository.
- The Telegram bot service is a separate repository and was not part of this review.
