"""Populate a realistic demo workspace ("Nova Labs") for demos, screenshots and the presentation.

Idempotent: does nothing if the workspace already exists, unless --reset is given.
All accounts use the password ``demo1234``.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.activities.models import Activity
from apps.comments.models import Comment
from apps.cycles.models import Cycle
from apps.integrations.models import GitHubAccount, GitHubCommit, GitHubPullRequest, GitHubRepositoryLink
from apps.issues.models import Issue
from apps.milestones.models import Milestone
from apps.projects.models import Label, Note, Project, ProjectMember
from apps.teams.models import Team, TeamMembership
from apps.workspaces.models import Membership, Workspace

User = get_user_model()
WORKSPACE_NAME = "Nova Labs"
PASSWORD = "demo1234"

PEOPLE = [
    # username, first, last, title, workspace role
    ("jane.dev", "Jane", "Cooper", "Tech lead", "owner"),
    ("alex.k", "Alex", "Karimov", "Backend engineer", "admin"),
    ("priya.s", "Priya", "Sharma", "Frontend engineer", "member"),
    ("sam.m", "Sam", "Morgan", "QA & DevOps", "member"),
]

LABELS = [
    ("backend", "#baa7ff"),
    ("frontend", "#70b8ff"),
    ("urgent", "#ff9592"),
    ("docs", "#3ad389"),
    ("design", "#ffca16"),
]

# (title, type, status, priority, assignee, due offset in days, labels, description)
PAYMENTS = [
    ("Design idempotency keys for the charge endpoint", "feature", "done", "high", "alex.k", None, ["backend"], "Clients must be able to retry a charge safely without double billing."),
    ("Add webhook signature verification", "feature", "done", "high", "alex.k", None, ["backend"], "Verify HMAC signatures on every inbound provider webhook."),
    ("Fix rounding error in multi-currency refunds", "bug", "in_review", "urgent", "alex.k", 1, ["backend", "urgent"], "Refunds in JPY and KWD are off by one minor unit."),
    ("Rate limit /v2/charges per API key", "feature", "in_progress", "high", "alex.k", 4, ["backend"], "Token bucket per key, configurable per plan."),
    ("Migrate ledger table to a partitioned schema", "chore", "in_progress", "medium", "jane.dev", 9, ["backend"], "Monthly partitions; needs a zero-downtime backfill."),
    ("Refund endpoint returns 500 on expired card", "bug", "todo", "urgent", "alex.k", -2, ["backend", "urgent"], "Should return a 422 with a structured error code."),
    ("Add OpenAPI examples for payment intents", "improvement", "todo", "low", "priya.s", None, ["docs"], "Every response type needs a realistic example."),
    ("Load test the checkout flow at 1k rps", "task", "todo", "medium", "sam.m", 6, [], "Report p95 latency and error rate."),
    ("Audit PCI logging of card metadata", "task", "backlog", "high", "jane.dev", None, ["backend"], "Make sure no PAN fragments reach the logs."),
    ("Support SEPA direct debit", "feature", "backlog", "medium", None, None, ["backend"], "Second payment method after cards."),
    ("Reset the sandbox environment nightly", "chore", "done", "low", "sam.m", None, [], "Cron job plus fixtures."),
    ("Return structured error codes", "improvement", "done", "medium", "priya.s", None, ["docs"], "Machine-readable code next to the human message."),
    ("Stale 3DS sessions never expire", "bug", "in_progress", "high", "alex.k", 3, ["backend"], "Sessions older than 15 minutes must be rejected."),
    ("Document the rollback procedure", "task", "backlog", "low", "jane.dev", None, ["docs"], "Runbook for reverting a bad deploy."),
]

MOBILE = [
    ("Onboarding: biometric login", "feature", "in_review", "high", "priya.s", 2, ["frontend"], "Face ID / fingerprint with a passcode fallback."),
    ("Crash when rotating the issue list", "bug", "todo", "high", "priya.s", 2, ["frontend", "urgent"], "Reproduced on Android 14 only."),
    ("Offline cache for the project list", "feature", "in_progress", "medium", "priya.s", 11, ["frontend"], "Read-only cache, synced when the network returns."),
    ("Push notifications for assigned issues", "feature", "done", "high", "priya.s", None, ["frontend"], "Delivered through the existing notification service."),
    ("Dark theme contrast audit", "improvement", "done", "low", "sam.m", None, ["design"], "All text must reach WCAG AA."),
    ("App icon and splash screen", "task", "done", "low", "priya.s", None, ["design"], "Final artwork from the design team."),
    ("Localize the UI: Uzbek and English", "feature", "in_progress", "high", "jane.dev", 5, ["frontend"], "Language switcher in the header, Uzbek by default."),
    ("Set up the TestFlight beta", "chore", "todo", "medium", "sam.m", 3, [], "Internal testers first."),
    ("Deep links to issue #id", "feature", "backlog", "medium", None, None, ["frontend"], "devtrack://issue/42 opens the issue."),
    ("Reduce cold start below 1.5 seconds", "improvement", "backlog", "medium", "priya.s", None, ["frontend"], "Profile the startup path first."),
]

DOCS = [
    ("Choose a documentation framework", "task", "done", "medium", "jane.dev", None, ["docs"], "Compared three static site generators."),
    ("Draft the information architecture", "task", "in_progress", "medium", "priya.s", 8, ["docs", "design"], "Guides, API reference, changelog."),
    ("Write the quick-start guide", "task", "todo", "high", "jane.dev", 14, ["docs"], "From sign-up to the first project in five minutes."),
    ("Set up search", "feature", "backlog", "low", None, None, ["docs"], "Client-side index is enough to start."),
]

LEGACY = [
    ("Inventory the old cron jobs", "task", "done", "medium", "sam.m", None, ["backend"], "Found 23 jobs, 9 of them dead."),
    ("Port the report generator", "task", "todo", "low", "alex.k", None, ["backend"], "Blocked on the data warehouse decision."),
    ("Decommission the old admin panel", "chore", "backlog", "low", None, None, [], "After the last customer is migrated."),
]

SITE = [
    ("Landing page copy", "task", "done", "medium", "priya.s", None, ["design"], ""),
    ("Pricing page", "task", "done", "medium", "priya.s", None, ["design"], ""),
    ("Analytics and cookie consent", "chore", "done", "low", "sam.m", None, [], ""),
    ("Blog launch post", "task", "done", "low", "jane.dev", None, ["docs"], ""),
    ("SEO audit", "improvement", "done", "medium", "sam.m", None, [], ""),
]

COMMENTS = {
    "Fix rounding error in multi-currency refunds": [
        ("sam.m", "Reproduced with JPY 1,000 refunded in two halves — the second half is off by one."),
        ("alex.k", "Found it: we round each half instead of rounding the total. Fix is in review."),
        ("jane.dev", "Nice catch. @alex.k please add a regression test for KWD (3 decimals) too."),
    ],
    "Onboarding: biometric login": [
        ("jane.dev", "Looks good. Can we make sure the passcode fallback works when biometrics are locked out?"),
        ("priya.s", "Yes — covered by the new lockout test."),
    ],
    "Refund endpoint returns 500 on expired card": [
        ("sam.m", "This is blocking the sandbox demo tomorrow."),
    ],
    "Rate limit /v2/charges per API key": [
        ("alex.k", "Going with a token bucket; burst size will be configurable per plan."),
        ("jane.dev", "Agreed. Please document the headers we return (Retry-After, X-RateLimit-*)."),
    ],
}

NOTES = {
    "Payments API v2": [
        ("Architecture decisions", "jane.dev", "- Idempotency keys are stored for 24h\n- Ledger is append-only\n- Providers sit behind one interface"),
        ("Release checklist", "sam.m", "1. Run the load test\n2. Freeze schema changes\n3. Notify support\n4. Deploy behind a flag"),
    ],
    "DevTrack Mobile App": [
        ("Design review notes", "priya.s", "Contrast fixes agreed; the icon set stays as is."),
    ],
}


class Command(BaseCommand):
    help = "Create a realistic demo workspace with users, projects, issues, GitHub activity and comments."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete the demo workspace first and recreate it.")

    @transaction.atomic
    def handle(self, *args, **options):
        existing = Workspace.objects.filter(name=WORKSPACE_NAME).first()
        if existing and not options["reset"]:
            self.stdout.write(f'"{WORKSPACE_NAME}" already exists — nothing to do (use --reset to recreate).')
            return
        if existing:
            existing.delete()

        now = timezone.now()
        today = timezone.localdate()
        users = self._users()
        workspace = self._workspace(users)
        teams = self._teams(workspace, users)
        labels = {name: Label.objects.create(workspace=workspace, name=name, color=color) for name, color in LABELS}

        projects = {}
        for spec in [
            ("Payments API v2", "Second-generation payments platform with idempotency and ledger.", "active", "urgent", "Backend", -48, 19, PAYMENTS, "novalabs-demo/payments-api"),
            ("DevTrack Mobile App", "Companion app for iOS and Android.", "active", "high", "Frontend", -34, 40, MOBILE, "novalabs-demo/mobile-app"),
            ("Docs Portal", "Public documentation site.", "planned", "medium", "Frontend", 14, 86, DOCS, ""),
            ("Legacy Migration", "Retire the old monolith's batch jobs.", "paused", "low", "Backend", -90, 60, LEGACY, ""),
            ("Marketing Site", "Landing page, pricing and blog.", "completed", "medium", "Frontend", -110, -50, SITE, ""),
        ]:
            name, description, status, priority, team, start, target, issues, repo = spec
            project = Project.objects.create(
                workspace=workspace, name=name, description=description, status=status, priority=priority,
                owner=users["jane.dev"], team=teams[team], start_date=today + timedelta(days=start),
                target_date=today + timedelta(days=target),
                repository_url=f"https://github.com/{repo}" if repo else "",
            )
            for user in users.values():
                ProjectMember.objects.get_or_create(project=project, user=user, defaults={"role": "member"})
            projects[name] = (project, issues, repo)

        issue_by_title = {}
        for name, (project, specs, _repo) in projects.items():
            cycle_pair = self._cycles(project, today) if name == "Payments API v2" else None
            milestone_pair = self._milestones(project, today) if name == "Payments API v2" else None
            for index, (title, kind, status, priority, assignee, due, label_names, description) in enumerate(specs):
                reporter = users["jane.dev"] if index % 3 == 0 else users.get(assignee or "jane.dev", users["jane.dev"])
                issue = Issue.objects.create(
                    project=project, title=title, description=description, type=kind, priority=priority,
                    status="backlog" if status != "backlog" else status, reporter=reporter,
                    assignee=users[assignee] if assignee else None,
                    due_date=today + timedelta(days=due) if due is not None else None,
                )
                issue.labels.set([labels[label] for label in label_names])
                if cycle_pair:
                    issue.cycle = cycle_pair[0] if status in ("in_progress", "in_review", "todo") else cycle_pair[1]
                    issue.milestone = milestone_pair[index % 2]
                    issue.save(update_fields=["cycle", "milestone"])
                self._walk_status(issue, status, users)
                issue_by_title[title] = issue

        for title, entries in COMMENTS.items():
            for username, body in entries:
                Comment.objects.create(
                    content_type=ContentType.objects.get_for_model(Issue), object_id=issue_by_title[title].pk,
                    author=users[username], body=body,
                )
        for project_name, notes in NOTES.items():
            for title, username, body in notes:
                Note.objects.create(project=projects[project_name][0], title=title, author=users[username], body=body)

        self._github(projects, issue_by_title, users)
        self._spread_timestamps(workspace, now)
        self.stdout.write(self.style.SUCCESS(
            f'Seeded "{WORKSPACE_NAME}": {len(projects)} projects, {len(issue_by_title)} issues. '
            f"Sign in as jane.dev / {PASSWORD}."
        ))

    def _users(self):
        users = {}
        for username, first, last, title, _role in PEOPLE:
            user, created = User.objects.get_or_create(
                username=username, defaults={"email": f"{username}@devtrack.demo"}
            )
            if created:
                user.set_password(PASSWORD)
            user.first_name = user.first_name or first
            user.last_name = user.last_name or last
            user.title = user.title or title
            user.save()
            users[username] = user
        return users

    def _workspace(self, users):
        workspace = Workspace.objects.create(
            name=WORKSPACE_NAME, description="A small product team shipping a payments platform.", owner=users["jane.dev"]
        )
        for username, *_rest, role in PEOPLE:
            Membership.objects.get_or_create(workspace=workspace, user=users[username], defaults={"role": role})
        return workspace

    def _teams(self, workspace, users):
        teams = {}
        for name, members in {"Backend": ["alex.k", "jane.dev"], "Frontend": ["priya.s", "jane.dev"], "Quality": ["sam.m"]}.items():
            team = Team.objects.create(workspace=workspace, name=name, description=f"{name} engineers")
            for username in members:
                TeamMembership.objects.create(team=team, user=users[username])
            teams[name] = team
        return teams

    def _cycles(self, project, today):
        previous = Cycle.objects.create(
            project=project, name="Sprint 11", start_date=today - timedelta(days=24), end_date=today - timedelta(days=11)
        )
        current = Cycle.objects.create(
            project=project, name="Sprint 12", start_date=today - timedelta(days=10), end_date=today + timedelta(days=3)
        )
        Cycle.objects.create(
            project=project, name="Sprint 13", start_date=today + timedelta(days=4), end_date=today + timedelta(days=17)
        )
        return current, previous

    def _milestones(self, project, today):
        beta = Milestone.objects.create(
            project=project, name="Public beta", description="Invite-only beta for design partners.",
            target_date=today + timedelta(days=12),
        )
        ga = Milestone.objects.create(
            project=project, name="General availability", description="Open sign-up and pricing.",
            target_date=today + timedelta(days=40),
        )
        Milestone.objects.create(
            project=project, name="Sandbox ready", description="Test keys and nightly resets.",
            target_date=today - timedelta(days=6),
        )
        return beta, ga

    def _walk_status(self, issue, final, users):
        """Move an issue through realistic states so the timeline gets moved_issue events."""
        path = {
            "backlog": [], "todo": ["todo"], "in_progress": ["todo", "in_progress"],
            "in_review": ["todo", "in_progress", "in_review"], "done": ["todo", "in_progress", "in_review", "done"],
        }[final]
        actor = issue.assignee or issue.reporter
        for status in path:
            issue.status = status
            issue._actor = actor
            issue.save()

    def _github(self, projects, issue_by_title, users):
        # A placeholder connection so Settings shows the "connected" state. The id is far above any
        # real GitHub user id and the token is not a credential — it only exists in the demo database.
        GitHubAccount.objects.update_or_create(
            user=users["jane.dev"],
            defaults={"github_user_id": 9_999_999_999, "github_username": "jane-cooper", "access_token": "demo-placeholder-not-a-token", "scope": "repo"},
        )
        for name, (project, _specs, repo) in projects.items():
            if not repo:
                continue
            link = GitHubRepositoryLink.objects.create(
                project=project, github_repo_id=900000 + project.id, full_name=repo, webhook_id=1,
                connected_by=users["jane.dev"],
            )
            if name == "Payments API v2":
                prs = [
                    (142, "Add idempotency keys to POST /v2/charges", "closed", True, "alex.k", "feature/idempotency", "Design idempotency keys for the charge endpoint"),
                    (147, "Verify webhook signatures", "closed", True, "alex.k", "feature/webhook-signatures", "Add webhook signature verification"),
                    (151, "Fix refund rounding for zero-decimal currencies", "open", False, "alex.k", "fix/refund-rounding", "Fix rounding error in multi-currency refunds"),
                    (153, "Token-bucket rate limiter", "open", False, "alex.k", "feature/rate-limit", "Rate limit /v2/charges per API key"),
                ]
                commits = [
                    ("a1b2c3d", "Store idempotency keys for 24h", "alex.k", "Alex Karimov", "Design idempotency keys for the charge endpoint"),
                    ("b2c3d4e", "Round the refund total, not each part", "alex.k", "Alex Karimov", "Fix rounding error in multi-currency refunds"),
                    ("c3d4e5f", "Add regression tests for KWD refunds", "alex.k", "Alex Karimov", "Fix rounding error in multi-currency refunds"),
                    ("d4e5f6a", "Expire 3DS sessions after 15 minutes", "alex.k", "Alex Karimov", "Stale 3DS sessions never expire"),
                ]
            else:
                prs = [
                    (58, "Biometric login with passcode fallback", "open", False, "priya.s", "feature/biometric-login", "Onboarding: biometric login"),
                    (55, "Push notifications for assigned issues", "closed", True, "priya.s", "feature/push", "Push notifications for assigned issues"),
                ]
                commits = [
                    ("e5f6a7b", "Add lockout handling to biometric prompt", "priya.s", "Priya Sharma", "Onboarding: biometric login"),
                    ("f6a7b8c", "Cache the project list for offline use", "priya.s", "Priya Sharma", "Offline cache for the project list"),
                ]
            for number, title, state, merged, author, branch, issue_title in prs:
                pr = GitHubPullRequest.objects.create(
                    repo_link=link, github_pr_id=800000 + number, number=number, title=title, state=state, merged=merged,
                    author_username=author, url=f"https://github.com/{repo}/pull/{number}", head_ref=branch, base_ref="main",
                )
                pr.issues.set([issue_by_title[issue_title]])
                if merged:
                    Activity.objects.create(
                        workspace=project.workspace, actor=users[author], verb="pr_merged", target=issue_by_title[issue_title],
                        metadata={"from": "in_review", "to": "done", "pr_number": number,
                                  "pr_url": f"https://github.com/{repo}/pull/{number}"},
                    )
            for sha, message, username, full_name, issue_title in commits:
                commit = GitHubCommit.objects.create(
                    repo_link=link, sha=sha * 5 + sha[:5], message=message, author_username=username,
                    author_name=full_name, url=f"https://github.com/{repo}/commit/{sha}",
                )
                commit.issues.set([issue_by_title[issue_title]])

    def _spread_timestamps(self, workspace, now):
        """Everything was just created; spread it over the last three weeks so timelines look lived-in."""
        def spread(queryset, days):
            rows = list(queryset.order_by("id").values_list("id", flat=True))
            total = max(len(rows), 1)
            for position, pk in enumerate(rows):
                offset = timedelta(days=days) * (1 - (position + 1) / total)
                queryset.model.objects.filter(pk=pk).update(created_at=now - offset)

        spread(Activity.objects.filter(workspace=workspace), 18)
        spread(Issue.objects.filter(project__workspace=workspace), 21)
        spread(Comment.objects.filter(author__in=User.objects.filter(username__in=[p[0] for p in PEOPLE])), 6)
        # Keep "updated_at" of a couple of in-progress issues old so the health card can flag stale work.
        Issue.objects.filter(title="Stale 3DS sessions never expire").update(updated_at=now - timedelta(days=9))
        Issue.objects.filter(title="Migrate ledger table to a partitioned schema").update(updated_at=now - timedelta(days=8))
