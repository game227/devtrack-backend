from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.issues.models import Issue
from apps.telegram_bot import services
from apps.telegram_bot.bot_api import _issue_brief, _workspace_ids, urgency_key

User = get_user_model()
DIGEST_ITEMS = 5


class Command(BaseCommand):
    help = (
        "Send every linked user a Telegram digest of their overdue issues and those due today. "
        "Meant to run once a morning from a scheduler (cron)."
    )

    def handle(self, *args, **options):
        today = timezone.localdate()
        users = User.objects.filter(
            assigned_issues__due_date__lte=today, assigned_issues__status__in=[
                s for s in Issue.Status.values if s != Issue.Status.DONE
            ],
        ).distinct()
        sent = skipped = failed = 0
        for user in users:
            issues = list(
                Issue.objects.filter(
                    assignee=user, due_date__lte=today, project__workspace_id__in=_workspace_ids(user)
                )
                .exclude(status=Issue.Status.DONE)
                .select_related("project", "assignee")
            )
            if not issues:
                continue
            issues.sort(key=lambda issue: urgency_key(issue, today))
            briefs = [_issue_brief(issue, today) for issue in issues]
            payload = {
                "user_id": user.id,
                "kind": "digest",
                "overdue": sum(1 for b in briefs if b["overdue"]),
                "today": sum(1 for b in briefs if not b["overdue"]),
                "items": [
                    {"id": b["id"], "title": b["title"], "overdue": b["overdue"], "path": b["path"]}
                    for b in briefs[:DIGEST_ITEMS]
                ],
            }
            try:
                if services.notify(payload):
                    sent += 1
                else:
                    skipped += 1  # not linked to Telegram, or muted
            except services.BotServiceError as exc:
                failed += 1
                self.stderr.write(f"user {user.id}: {exc}")
        self.stdout.write(f"Telegram digest: {sent} sent, {skipped} skipped, {failed} failed.")
