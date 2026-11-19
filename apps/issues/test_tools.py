import datetime as dt

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.activities.models import Activity
from apps.cycles.models import Cycle
from apps.projects.models import Project
from apps.workspaces.models import Membership, Workspace

from .models import ChecklistItem, Issue, IssueShareLink, RecurringIssue, TimeEntry
from .tools import run_recurring

User = get_user_model()


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user(username="t-own", email="town@example.com", password="pw")
        self.dev = User.objects.create_user(username="t-dev", email="tdev@example.com", password="pw")
        self.other = User.objects.create_user(username="t-oth", email="toth@example.com", password="pw")
        self.outsider = User.objects.create_user(username="t-out", email="tout@example.com", password="pw")
        self.workspace = Workspace.objects.create(name="TW", owner=self.owner)
        for user, role in [(self.owner, "owner"), (self.dev, "member"), (self.other, "member")]:
            Membership.objects.create(workspace=self.workspace, user=user, role=role)
        self.project = Project.objects.create(workspace=self.workspace, name="Shop", owner=self.owner)
        self.issue = Issue.objects.create(project=self.project, title="Fix cart", reporter=self.dev, description="Steps", priority="low")
        self.client = APIClient()


class ShareTests(Base):
    def test_share_and_read_publicly_without_private_parts(self):
        ChecklistItem.objects.create(issue=self.issue, text="Repro", done=True, position=1)
        self.client.force_authenticate(self.dev)
        link = self.client.post(reverse("issue-share", args=[self.issue.id]), {"days": 7}, format="json").data
        self.assertEqual(len(link["token"]), 43)
        public = APIClient().get(reverse("issue-public", args=[link["token"]]))
        self.assertEqual(public.status_code, 200)
        self.assertEqual(public.data["title"], "Fix cart")
        self.assertEqual(public.data["project"], "Shop")
        self.assertEqual(public.data["checklist"], [{"text": "Repro", "done": True}])
        self.assertNotIn("reporter", public.data)
        self.assertNotIn("comments", public.data)

    def test_only_people_responsible_can_share_and_links_end(self):
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(reverse("issue-share", args=[self.issue.id]), {"days": 7}, format="json").status_code, 403)
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.post(reverse("issue-share", args=[self.issue.id]), {"days": 7}, format="json").status_code, 404)
        self.client.force_authenticate(self.owner)  # a workspace owner may
        self.assertEqual(self.client.post(reverse("issue-share", args=[self.issue.id]), {"days": 5}, format="json").status_code, 400)
        link = self.client.post(reverse("issue-share", args=[self.issue.id]), {"days": 1}, format="json").data
        self.assertEqual(self.client.delete(reverse("issue-share-link", args=[link["id"]])).status_code, 204)
        self.assertEqual(APIClient().get(reverse("issue-public", args=[link["token"]])).status_code, 404)
        expired = IssueShareLink.objects.create(issue=self.issue, token="x" * 40, expires_at=timezone.now() - dt.timedelta(minutes=1))
        self.assertEqual(APIClient().get(reverse("issue-public", args=[expired.token])).status_code, 404)
        self.assertEqual(APIClient().get(reverse("issue-public", args=["nope"])).status_code, 404)


class RecurringTests(Base):
    def test_managers_create_rules_and_the_command_opens_issues(self):
        url = reverse("recurring-list", args=[self.project.id])
        self.client.force_authenticate(self.dev)
        body = {"title": "Weekly report", "frequency": "weekly", "next_run": timezone.localdate().isoformat(), "assignee_id": self.dev.id}
        self.assertEqual(self.client.post(url, body, format="json").status_code, 403)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.post(url, {**body, "assignee_id": self.outsider.id}, format="json").status_code, 400)
        self.assertEqual(self.client.post(url, {**body, "next_run": "2020-01-01"}, format="json").status_code, 400)
        rule = self.client.post(url, body, format="json")
        self.assertEqual(rule.status_code, 201, rule.data)

        self.assertEqual(run_recurring(), 1)
        created = Issue.objects.get(title="Weekly report")
        self.assertEqual((created.assignee, created.reporter), (self.dev, self.owner))
        self.assertEqual(RecurringIssue.objects.get().next_run, timezone.localdate() + dt.timedelta(days=7))
        self.assertEqual(run_recurring(), 0)  # nothing twice on the same day

    def test_monthly_keeps_the_day_or_the_months_end(self):
        rule = RecurringIssue(frequency="monthly", next_run=dt.date(2026, 1, 31))
        self.assertEqual(rule.advance(), dt.date(2026, 2, 28))
        rule.next_run = dt.date(2026, 12, 15)
        self.assertEqual(rule.advance(), dt.date(2027, 1, 15))

    def test_a_rule_of_someone_who_left_stops(self):
        RecurringIssue.objects.create(project=self.project, title="r", frequency="daily", next_run=timezone.localdate(), created_by=self.other)
        Membership.objects.filter(user=self.other).delete()
        self.assertEqual(run_recurring(), 0)
        self.assertFalse(RecurringIssue.objects.get().active)


class BulkTests(Base):
    def test_changes_what_is_allowed_and_reports_the_rest(self):
        mine = Issue.objects.create(project=self.project, title="mine", reporter=self.dev)
        assigned = Issue.objects.create(project=self.project, title="assigned", reporter=self.owner, assignee=self.dev)
        foreign = Issue.objects.create(project=self.project, title="foreign", reporter=self.owner)
        self.client.force_authenticate(self.dev)
        response = self.client.post(reverse("issue-bulk"), {"ids": [mine.id, assigned.id, foreign.id, 999999], "changes": {"status": "in_progress"}}, format="json")
        self.assertEqual(response.data["updated"], [mine.id, assigned.id])
        self.assertEqual({s["id"]: s["reason"] for s in response.data["skipped"]}, {foreign.id: "not_allowed", 999999: "not_found"})
        # An assignee may not reassign someone else's issue.
        response = self.client.post(reverse("issue-bulk"), {"ids": [assigned.id], "changes": {"assignee_id": self.other.id}}, format="json")
        self.assertEqual(response.data["skipped"][0]["reason"], "not_allowed")
        cycle = Cycle.objects.create(project=self.project, name="S1", start_date=dt.date(2026, 11, 1), end_date=dt.date(2026, 11, 14))
        response = self.client.post(reverse("issue-bulk"), {"ids": [mine.id], "changes": {"cycle": cycle.id, "assignee_id": self.outsider.id}}, format="json")
        self.assertEqual(response.data["skipped"][0]["reason"], "invalid")

    def test_rejects_bad_requests(self):
        self.client.force_authenticate(self.dev)
        for body in [{"ids": [], "changes": {"status": "done"}}, {"ids": [1], "changes": {"title": "x"}}, {"ids": list(range(1, 300)), "changes": {"status": "done"}}]:
            self.assertEqual(self.client.post(reverse("issue-bulk"), body, format="json").status_code, 400)


class TimeTests(Base):
    def test_members_log_their_own_time(self):
        self.client.force_authenticate(self.other)
        url = reverse("issue-time", args=[self.issue.id])
        today = timezone.localdate().isoformat()
        created = self.client.post(url, {"minutes": 90, "note": "debugging", "spent_on": today}, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(self.client.post(url, {"minutes": 0, "spent_on": today}, format="json").status_code, 400)
        tomorrow = (timezone.localdate() + dt.timedelta(days=1)).isoformat()
        self.assertEqual(self.client.post(url, {"minutes": 10, "spent_on": tomorrow}, format="json").status_code, 400)
        self.client.force_authenticate(self.dev)
        self.assertEqual(len(self.client.get(url).data), 1)
        self.assertEqual(self.client.delete(reverse("issue-time-entry", args=[created.data["id"]])).status_code, 403)
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.delete(reverse("issue-time-entry", args=[created.data["id"]])).status_code, 204)
        self.assertFalse(TimeEntry.objects.exists())


class HistoryTests(Base):
    def test_field_changes_are_recorded_readably_and_listed_per_issue(self):
        self.client.force_authenticate(self.dev)
        self.client.patch(reverse("issue-detail", args=[self.issue.id]), {"priority": "high", "assignee_id": self.other.id}, format="json")
        entry = Activity.objects.get(verb="changed_issue")
        self.assertEqual(entry.actor, self.dev)
        changes = {c["field"]: (c["from"], c["to"]) for c in entry.metadata["changes"]}
        self.assertEqual(changes, {"priority": ("low", "high"), "assignee": (None, "t-oth")})
        history = self.client.get(reverse("activity-list"), {"issue": self.issue.id}).data
        verbs = [row["verb"] for row in history["results"]]
        self.assertEqual(verbs, ["changed_issue", "created_issue"])
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get(reverse("activity-list"), {"issue": self.issue.id}).status_code, 403)


class WipTests(Base):
    def test_limits_are_validated(self):
        self.client.force_authenticate(self.owner)
        url = reverse("project-detail", args=[self.project.id])
        response = self.client.patch(url, {"wip_limits": {"in_progress": 3, "in_review": 0}}, format="json")
        self.assertEqual(response.data["wip_limits"], {"in_progress": 3})
        for bad in [{"done": 3}, {"in_progress": 0.5}, {"in_progress": 500}, ["x"]]:
            self.assertEqual(self.client.patch(url, {"wip_limits": bad}, format="json").status_code, 400, bad)


@override_settings(FRONTEND_URL="https://app.test", SUPPORT_EMAIL="")
class DigestTests(Base):
    def test_owners_and_admins_get_a_summary_unless_they_opt_out(self):
        from apps.accounts.digest import send_weekly_digests

        Issue.objects.create(project=self.project, title="Late one", reporter=self.owner, due_date=timezone.localdate() - dt.timedelta(days=2))
        admin = User.objects.create_user(username="t-adm", email="tadm@example.com", password="pw", weekly_digest=False)
        Membership.objects.create(workspace=self.workspace, user=admin, role="admin")
        self.assertEqual(send_weekly_digests("en"), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["town@example.com"])
        self.assertEqual(message.subject, "DevTrack weekly: TW")
        self.assertIn("- Shop: health", message.body)
        self.assertIn("Late one (Shop)", message.body)
        self.assertIn("https://app.test", message.body)
