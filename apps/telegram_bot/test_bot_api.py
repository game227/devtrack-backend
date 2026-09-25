import datetime as dt
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.activities.models import Activity
from apps.comments.models import Comment
from apps.issues.models import Issue
from apps.notifications.models import Notification
from apps.projects.models import Project
from apps.workspaces.models import Membership, Workspace

from . import notify, services

User = get_user_model()
KEY = "test-bot-key"


def bot_client(user, key=KEY):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {key}", HTTP_X_DEVTRACK_USER_ID=str(user.id))
    return client


@override_settings(BOT_SERVICE_API_KEY=KEY)
class BotApiBase(TestCase):
    def setUp(self):
        self.me = User.objects.create_user(username="botme", email="botme@example.com", password="pw")
        self.other = User.objects.create_user(username="botother", email="botother@example.com", password="pw")
        self.outsider = User.objects.create_user(username="botout", email="botout@example.com", password="pw")
        self.workspace = Workspace.objects.create(name="Bot WS", owner=self.me)
        Membership.objects.create(workspace=self.workspace, user=self.me, role="owner")
        Membership.objects.create(workspace=self.workspace, user=self.other, role="member")
        self.project = Project.objects.create(workspace=self.workspace, name="Proj", owner=self.me)
        self.today = timezone.localdate()
        self.client = bot_client(self.me)

    def issue(self, title="I", **kwargs):
        kwargs.setdefault("reporter", self.me)
        return Issue.objects.create(project=self.project, title=title, **kwargs)


class BotAuthenticationTests(BotApiBase):
    url = "/api/v1/telegram/bot/me/"

    def test_a_valid_key_and_user_get_in(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["username"], "botme")
        self.assertIn("Bot WS", [w["name"] for w in response.data["workspaces"]])

    def test_no_credentials_is_rejected(self):
        self.assertIn(APIClient().get(self.url).status_code, (401, 403))

    def test_the_wrong_key_is_rejected(self):
        self.assertIn(bot_client(self.me, key="nope").get(self.url).status_code, (401, 403))

    def test_the_key_alone_is_not_enough(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {KEY}")
        self.assertEqual(client.get(self.url).status_code, 401)

    def test_an_unknown_or_inactive_user_is_rejected(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {KEY}", HTTP_X_DEVTRACK_USER_ID="999999")
        self.assertEqual(client.get(self.url).status_code, 401)
        self.outsider.is_active = False
        self.outsider.save()
        self.assertEqual(bot_client(self.outsider).get(self.url).status_code, 401)

    @override_settings(BOT_SERVICE_API_KEY="")
    def test_an_unconfigured_key_never_matches(self):
        self.assertIn(bot_client(self.me, key="").get(self.url).status_code, (401, 403))

    def test_a_normal_user_token_does_not_work_here_and_the_key_does_not_work_elsewhere(self):
        from rest_framework_simplejwt.tokens import RefreshToken

        user_client = APIClient()
        user_client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")
        self.assertIn(user_client.get(self.url).status_code, (401, 403))
        # The bot key must not open the regular API.
        self.assertIn(self.client.get("/api/v1/projects/", {"workspace": self.workspace.id}).status_code, (401, 403))


class BotIssuesTests(BotApiBase):
    url = "/api/v1/telegram/bot/issues/"

    def test_my_open_issues_most_urgent_first(self):
        later = self.issue("Later", assignee=self.me, due_date=self.today + dt.timedelta(days=20))
        soon = self.issue("Soon", assignee=self.me, due_date=self.today + dt.timedelta(days=1))
        late = self.issue("Late", assignee=self.me, due_date=self.today - dt.timedelta(days=4))
        undated = self.issue("Undated", assignee=self.me, priority=Issue.Priority.HIGH)
        self.issue("Done", assignee=self.me, status=Issue.Status.DONE)
        self.issue("Not mine", assignee=self.other)
        data = self.client.get(self.url).data
        self.assertEqual([i["id"] for i in data["issues"]], [late.id, soon.id, later.id, undated.id])
        self.assertEqual(data["total"], 4)
        self.assertTrue(data["issues"][0]["overdue"])
        self.assertEqual(data["issues"][0]["path"], f"/issues/{late.id}")

    def test_each_issue_says_whether_the_user_may_edit_it(self):
        mine = self.issue("Mine", assignee=self.me)
        theirs = self.issue("Theirs", assignee=self.me, reporter=self.other)
        flags = {i["id"]: i["can_edit"] for i in self.client.get(self.url).data["issues"]}
        self.assertEqual(flags, {mine.id: True, theirs.id: False})

    def test_scopes_narrow_the_list(self):
        late = self.issue("Late", assignee=self.me, due_date=self.today - dt.timedelta(days=1))
        soon = self.issue("Soon", assignee=self.me, due_date=self.today + dt.timedelta(days=2))
        self.issue("Far", assignee=self.me, due_date=self.today + dt.timedelta(days=30))
        ids = lambda scope: [i["id"] for i in self.client.get(self.url, {"scope": scope}).data["issues"]]  # noqa: E731
        self.assertEqual(ids("overdue"), [late.id])
        self.assertEqual(ids("soon"), [late.id, soon.id])
        self.assertEqual(len(ids("mine")), 3)
        self.assertEqual(self.client.get(self.url, {"scope": "bogus"}).status_code, 400)

    def test_the_list_is_capped_but_reports_the_total(self):
        for number in range(13):
            self.issue(f"I{number}", assignee=self.me)
        data = self.client.get(self.url).data
        self.assertEqual(len(data["issues"]), 10)
        self.assertEqual(data["total"], 13)

    def test_issues_in_a_workspace_the_user_left_are_not_listed(self):
        foreign_ws = Workspace.objects.create(name="Left", owner=self.other)
        Membership.objects.create(workspace=foreign_ws, user=self.other, role="owner")
        foreign_project = Project.objects.create(workspace=foreign_ws, name="F", owner=self.other)
        Issue.objects.create(project=foreign_project, title="Stale assignment", reporter=self.other, assignee=self.me)
        self.assertEqual(self.client.get(self.url).data["total"], 0)


class BotCreateIssueTests(BotApiBase):
    url = "/api/v1/telegram/bot/issues/"

    def test_creates_an_issue_reported_by_the_user_and_logs_it(self):
        response = self.client.post(self.url, {"title": "  From Telegram  ", "project": self.project.id}, format="json")
        self.assertEqual(response.status_code, 201)
        issue = Issue.objects.get(pk=response.data["id"])
        self.assertEqual((issue.title, issue.reporter), ("From Telegram", self.me))
        self.assertTrue(Activity.objects.filter(verb="created_issue", actor=self.me, object_id=issue.id).exists())

    def test_validation(self):
        self.assertEqual(self.client.post(self.url, {"title": "", "project": self.project.id}, format="json").status_code, 400)
        self.assertEqual(self.client.post(self.url, {"title": "x" * 201, "project": self.project.id}, format="json").status_code, 400)
        self.assertEqual(self.client.post(self.url, {"title": "x"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(self.url, {"title": "x", "project": "abc"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(self.url, {"title": "x", "project": 99999}, format="json").status_code, 404)

    def test_cannot_create_in_a_workspace_you_are_not_in(self):
        response = bot_client(self.outsider).post(self.url, {"title": "x", "project": self.project.id}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Issue.objects.filter(title="x").exists())


class BotIssueActionsTests(BotApiBase):
    def test_the_creator_can_change_status_and_it_is_credited_to_them(self):
        issue = self.issue("Mine")
        response = self.client.post(f"/api/v1/telegram/bot/issues/{issue.id}/status/", {"status": "done"}, format="json")
        self.assertEqual(response.status_code, 200)
        issue.refresh_from_db()
        self.assertEqual(issue.status, "done")
        self.assertEqual(Activity.objects.get(verb="moved_issue").actor, self.me)

    def test_only_the_creator_can_change_status_like_in_the_web_app(self):
        issue = self.issue("Theirs", reporter=self.other, assignee=self.me)
        response = self.client.post(f"/api/v1/telegram/bot/issues/{issue.id}/status/", {"status": "done"}, format="json")
        self.assertEqual(response.status_code, 403)
        issue.refresh_from_db()
        self.assertNotEqual(issue.status, "done")

    def test_status_must_be_a_real_one_and_the_user_must_be_a_member(self):
        issue = self.issue("Mine")
        self.assertEqual(self.client.post(f"/api/v1/telegram/bot/issues/{issue.id}/status/", {"status": "nope"}, format="json").status_code, 400)
        self.assertEqual(bot_client(self.outsider).post(f"/api/v1/telegram/bot/issues/{issue.id}/status/", {"status": "done"}, format="json").status_code, 403)

    def test_any_member_can_comment_and_the_owner_is_notified(self):
        issue = self.issue("Talk", reporter=self.me)
        response = bot_client(self.other).post(f"/api/v1/telegram/bot/issues/{issue.id}/comments/", {"body": "On it"}, format="json")
        self.assertEqual(response.status_code, 201)
        comment = Comment.objects.get()
        self.assertEqual((comment.author, comment.body, comment.content_object), (self.other, "On it", issue))
        self.assertTrue(Notification.objects.filter(recipient=self.me, verb="commented").exists())

    def test_empty_comments_and_outsiders_are_refused(self):
        issue = self.issue("Talk")
        self.assertEqual(self.client.post(f"/api/v1/telegram/bot/issues/{issue.id}/comments/", {"body": "  "}, format="json").status_code, 400)
        self.assertEqual(bot_client(self.outsider).post(f"/api/v1/telegram/bot/issues/{issue.id}/comments/", {"body": "hi"}, format="json").status_code, 403)

    def test_issue_detail(self):
        issue = self.issue("Detail", description="d" * 500)
        data = self.client.get(f"/api/v1/telegram/bot/issues/{issue.id}/").data
        self.assertEqual(data["title"], "Detail")
        self.assertEqual(len(data["description"]), 400)
        self.assertEqual(bot_client(self.outsider).get(f"/api/v1/telegram/bot/issues/{issue.id}/").status_code, 403)


class BotProjectsTests(BotApiBase):
    def test_lists_projects_with_progress_and_skips_archived_and_foreign_ones(self):
        self.issue("a", status=Issue.Status.DONE)
        self.issue("b")
        Project.objects.create(workspace=self.workspace, name="Old", owner=self.me, status=Project.Status.ARCHIVED)
        foreign = Workspace.objects.create(name="Foreign", owner=self.outsider)
        Project.objects.create(workspace=foreign, name="Secret", owner=self.outsider)
        rows = self.client.get("/api/v1/telegram/bot/projects/").data["projects"]
        self.assertEqual([r["name"] for r in rows], ["Proj"])
        self.assertEqual((rows[0]["open"], rows[0]["done"], rows[0]["progress"]), (1, 1, 50))

    def test_project_health_for_members_only(self):
        self.issue("a")
        data = self.client.get(f"/api/v1/telegram/bot/projects/{self.project.id}/health/").data
        self.assertEqual(data["project"]["name"], "Proj")
        self.assertIn("score", data)
        self.assertEqual(data["formula_version"], 2)
        self.assertEqual(bot_client(self.outsider).get(f"/api/v1/telegram/bot/projects/{self.project.id}/health/").status_code, 403)


class NotifyServiceTests(TestCase):
    def response(self, status):
        return type("R", (), {"status_code": status, "json": lambda self: {"detail": "x"}})()

    @patch("apps.telegram_bot.services.requests.request")
    def test_maps_the_bots_answers(self, mock_request):
        for status, expected in ((200, True), (202, False), (404, False)):
            mock_request.return_value = self.response(status)
            self.assertIs(services.notify({"user_id": 1}), expected)
        mock_request.return_value = self.response(500)
        with self.assertRaises(services.BotServiceError):
            services.notify({"user_id": 1})


@override_settings(TELEGRAM_NOTIFICATIONS_ENABLED=True, TELEGRAM_NOTIFICATIONS_ASYNC=False)
class NotificationPushTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="pushowner", email="pushowner@example.com", password="pw")
        self.dev = User.objects.create_user(username="pushdev", email="pushdev@example.com", password="pw")
        self.workspace = Workspace.objects.create(name="Push WS", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role="owner")
        self.project = Project.objects.create(workspace=self.workspace, name="Push Project", owner=self.owner)

    @patch("apps.telegram_bot.notify.services.notify")
    def test_an_assignment_is_pushed_with_a_structured_payload(self, mock_notify):
        issue = Issue.objects.create(project=self.project, title="Ship it", reporter=self.owner, assignee=self.dev)
        mock_notify.assert_called_once_with(
            {"user_id": self.dev.id, "kind": "issue_assigned", "actor": "pushowner", "title": "Ship it", "excerpt": "", "path": f"/issues/{issue.id}"}
        )

    @patch("apps.telegram_bot.notify.services.notify")
    def test_a_comment_carries_an_excerpt_and_points_at_the_issue(self, mock_notify):
        issue = Issue.objects.create(project=self.project, title="Talk", reporter=self.dev)
        Comment.objects.create(author=self.owner, body="Looks good " * 40, content_object=issue)
        payload = mock_notify.call_args.args[0]
        self.assertEqual((payload["kind"], payload["actor"], payload["title"], payload["path"]), ("commented", "pushowner", "Talk", f"/issues/{issue.id}"))
        self.assertEqual(len(payload["excerpt"]), notify.EXCERPT_CHARS)

    @patch("apps.telegram_bot.notify.services.notify")
    def test_workspace_and_project_invitations(self, mock_notify):
        Membership.objects.create(workspace=self.workspace, user=self.dev, role="member")
        self.assertEqual(mock_notify.call_args.args[0]["path"], "/dashboard")
        self.assertEqual(mock_notify.call_args.args[0]["title"], "Push WS")
        from apps.projects.models import ProjectMember
        ProjectMember.objects.create(project=self.project, user=self.dev, role="member")
        self.assertEqual(mock_notify.call_args.args[0]["kind"], "project_member_added")
        self.assertEqual(mock_notify.call_args.args[0]["path"], f"/projects/{self.project.id}")

    @patch("apps.telegram_bot.notify.services.notify")
    def test_you_are_not_notified_about_your_own_actions(self, mock_notify):
        Issue.objects.create(project=self.project, title="Self", reporter=self.owner, assignee=self.owner)
        mock_notify.assert_not_called()

    @patch("apps.telegram_bot.notify.services.notify", side_effect=services.BotServiceError("down"))
    def test_a_dead_bot_service_never_breaks_the_action_that_caused_the_notification(self, mock_notify):
        issue = Issue.objects.create(project=self.project, title="Fine", reporter=self.owner, assignee=self.dev)
        self.assertTrue(Issue.objects.filter(pk=issue.pk).exists())
        self.assertTrue(Notification.objects.filter(recipient=self.dev).exists())

    @override_settings(TELEGRAM_NOTIFICATIONS_ENABLED=False)
    @patch("apps.telegram_bot.notify.services.notify")
    def test_off_by_default_means_no_calls_at_all(self, mock_notify):
        Issue.objects.create(project=self.project, title="Quiet", reporter=self.owner, assignee=self.dev)
        mock_notify.assert_not_called()
        self.assertTrue(Notification.objects.filter(recipient=self.dev).exists())

    @override_settings(TELEGRAM_NOTIFICATIONS_ASYNC=True)
    @patch("apps.telegram_bot.notify.threading.Thread")
    def test_by_default_delivery_leaves_the_request_thread(self, mock_thread):
        Issue.objects.create(project=self.project, title="Async", reporter=self.owner, assignee=self.dev)
        mock_thread.assert_called_once()
        self.assertTrue(mock_thread.call_args.kwargs["daemon"])
        mock_thread.return_value.start.assert_called_once()


class DigestCommandTests(BotApiBase):
    def run_digest(self):
        out = StringIO()
        with patch("apps.telegram_bot.management.commands.send_telegram_digest.services.notify", return_value=True) as mock_notify:
            call_command("send_telegram_digest", stdout=out)
        return mock_notify, out.getvalue()

    def test_sends_overdue_and_due_today_most_urgent_first(self):
        late = self.issue("Late", assignee=self.me, due_date=self.today - dt.timedelta(days=3))
        due = self.issue("Today", assignee=self.me, due_date=self.today)
        self.issue("Tomorrow", assignee=self.me, due_date=self.today + dt.timedelta(days=1))
        self.issue("Finished", assignee=self.me, due_date=self.today - dt.timedelta(days=9), status=Issue.Status.DONE)
        mock_notify, output = self.run_digest()
        mock_notify.assert_called_once()
        payload = mock_notify.call_args.args[0]
        self.assertEqual((payload["user_id"], payload["kind"], payload["overdue"], payload["today"]), (self.me.id, "digest", 1, 1))
        self.assertEqual([i["id"] for i in payload["items"]], [late.id, due.id])
        self.assertIn("1 sent", output)

    def test_nothing_due_means_no_message(self):
        self.issue("Later", assignee=self.me, due_date=self.today + dt.timedelta(days=5))
        mock_notify, output = self.run_digest()
        mock_notify.assert_not_called()
        self.assertIn("0 sent", output)

    def test_failures_are_counted_not_raised(self):
        self.issue("Late", assignee=self.me, due_date=self.today - dt.timedelta(days=1))
        out, err = StringIO(), StringIO()
        with patch("apps.telegram_bot.management.commands.send_telegram_digest.services.notify", side_effect=services.BotServiceError("down")):
            call_command("send_telegram_digest", stdout=out, stderr=err)
        self.assertIn("1 failed", out.getvalue())
