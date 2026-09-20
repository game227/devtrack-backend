from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.comments.models import Comment
from apps.issues.models import Issue
from apps.projects.models import Project, ProjectMember
from apps.workspaces.models import Membership, Workspace

from .models import Notification

User = get_user_model()


class NotificationSignalTests(TestCase):
    def setUp(self):
        self.reporter = User.objects.create_user(
            username="nreporter", email="nreporter@example.com", password="pw"
        )
        self.assignee = User.objects.create_user(
            username="nassignee", email="nassignee@example.com", password="pw"
        )
        self.workspace = Workspace.objects.create(name="NWS", owner=self.reporter)
        Membership.objects.create(workspace=self.workspace, user=self.reporter, role=Membership.Role.OWNER)
        self.project = Project.objects.create(workspace=self.workspace, name="P", owner=self.reporter)

    def test_assigning_an_issue_notifies_the_assignee(self):
        issue = Issue.objects.create(
            project=self.project, title="Bug", reporter=self.reporter, assignee=self.assignee
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.assignee, verb="issue_assigned", object_id=issue.id
            ).exists()
        )

    def test_self_assigning_does_not_notify(self):
        issue = Issue.objects.create(
            project=self.project, title="Bug", reporter=self.reporter, assignee=self.reporter
        )
        self.assertFalse(
            Notification.objects.filter(recipient=self.reporter, object_id=issue.id).exists()
        )

    def test_reassigning_notifies_the_new_assignee_only(self):
        issue = Issue.objects.create(project=self.project, title="Bug", reporter=self.reporter)
        issue.assignee = self.assignee
        issue.save()
        self.assertEqual(
            Notification.objects.filter(recipient=self.assignee, verb="issue_assigned", object_id=issue.id).count(),
            1,
        )

    def test_commenting_notifies_assignee_and_reporter_but_not_the_commenter(self):
        issue = Issue.objects.create(
            project=self.project, title="Bug", reporter=self.reporter, assignee=self.assignee
        )
        Comment.objects.create(
            content_type=ContentType.objects.get_for_model(Issue),
            object_id=issue.pk,
            author=self.assignee,
            body="Working on it",
        )
        self.assertTrue(
            Notification.objects.filter(recipient=self.reporter, verb="commented", object_id__isnull=False).exists()
        )
        self.assertFalse(Notification.objects.filter(recipient=self.assignee, verb="commented").exists())

    def test_being_added_to_a_workspace_notifies_the_new_member(self):
        newcomer = User.objects.create_user(username="ncomer", email="ncomer@example.com", password="pw")
        Membership.objects.create(workspace=self.workspace, user=newcomer, role=Membership.Role.MEMBER)
        self.assertTrue(
            Notification.objects.filter(recipient=newcomer, verb="workspace_invited").exists()
        )

    def test_workspace_owner_membership_does_not_notify(self):
        # The owner's own Membership row is created at workspace-creation time;
        # notify_on_workspace_invite explicitly skips the OWNER role.
        self.assertFalse(Notification.objects.filter(recipient=self.reporter).exists())

    def test_being_added_to_a_project_notifies_the_new_member(self):
        newcomer = User.objects.create_user(username="pncomer", email="pncomer@example.com", password="pw")
        ProjectMember.objects.create(project=self.project, user=newcomer, role="member")
        self.assertTrue(
            Notification.objects.filter(recipient=newcomer, verb="project_member_added").exists()
        )


class NotificationViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="nvuser", email="nvuser@example.com", password="pw")
        self.other = User.objects.create_user(username="nvother", email="nvother@example.com", password="pw")
        ct = ContentType.objects.get_for_model(User)
        self.n1 = Notification.objects.create(recipient=self.user, verb="issue_assigned", content_type=ct, object_id=1)
        self.n2 = Notification.objects.create(recipient=self.user, verb="commented", content_type=ct, object_id=2)
        Notification.objects.create(recipient=self.other, verb="commented", content_type=ct, object_id=3)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_list_only_returns_own_notifications(self):
        response = self.client.get(reverse("notification-list"))
        self.assertEqual(response.data["count"], 2)

    def test_mark_read(self):
        response = self.client.patch(reverse("notification-mark-read", kwargs={"pk": self.n1.pk}))
        self.assertEqual(response.status_code, 200)
        self.n1.refresh_from_db()
        self.assertTrue(self.n1.is_read)

    def test_cannot_mark_someone_elses_notification_read(self):
        other_notification = Notification.objects.filter(recipient=self.other).first()
        response = self.client.patch(reverse("notification-mark-read", kwargs={"pk": other_notification.pk}))
        self.assertEqual(response.status_code, 404)

    def test_mark_all_read(self):
        response = self.client.post(reverse("notification-mark-all-read"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["updated"], 2)
        self.assertEqual(Notification.objects.filter(recipient=self.user, is_read=False).count(), 0)


class NotificationActorTests(TestCase):
    def test_reassigning_to_the_reporter_by_someone_else_still_notifies_them(self):
        reporter = User.objects.create_user(username="nar", email="nar@example.com", password="pw")
        other = User.objects.create_user(username="nao", email="nao@example.com", password="pw")
        workspace = Workspace.objects.create(name="NAWS", owner=reporter)
        Membership.objects.create(workspace=workspace, user=reporter, role=Membership.Role.OWNER)
        Membership.objects.create(workspace=workspace, user=other, role=Membership.Role.MEMBER)
        project = Project.objects.create(workspace=workspace, name="P", owner=reporter)
        issue = Issue.objects.create(project=project, title="Bug", reporter=reporter, assignee=other)
        Notification.objects.all().delete()

        client = APIClient()
        client.force_authenticate(other)
        response = client.patch(
            reverse("issue-detail", kwargs={"pk": issue.pk}), {"assignee_id": reporter.pk}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Notification.objects.filter(recipient=reporter, verb="issue_assigned").exists())
