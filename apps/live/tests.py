from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.comments.models import Comment
from apps.issues.models import Issue
from apps.notifications.models import Notification
from apps.projects.models import Label, Project
from apps.workspaces.models import Invitation, Membership, Workspace

from .models import WorkspaceClock

User = get_user_model()


class ChangesEndpointTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="lowner", email="lowner@example.com", password="pw")
        self.mate = User.objects.create_user(username="lmate", email="lmate@example.com", password="pw")
        self.workspace = Workspace.objects.create(name="Live", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role="owner")
        self.mate_membership = Membership.objects.create(workspace=self.workspace, user=self.mate, role="member")
        self.project = Project.objects.create(workspace=self.workspace, name="P", owner=self.owner)
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def changes(self, since=None, user=None, workspace=None):
        client = self.client
        if user is not None:
            client = APIClient()
            client.force_authenticate(user)
        params = {"workspace": (workspace or self.workspace).id}
        if since is not None:
            params["since"] = since.isoformat()
        return client.get("/api/v1/changes/", params)

    def later(self):
        return timezone.now() + timedelta(seconds=10)  # a cursor taken after everything so far

    def earlier(self):
        return timezone.now() - timedelta(minutes=1)

    def test_the_first_call_only_hands_out_a_cursor(self):
        response = self.changes()
        self.assertEqual((response.status_code, response.data["changed"]), (200, []))
        self.assertTrue(response.data["cursor"])

    def test_each_area_is_reported_after_it_changes_and_not_after_a_newer_cursor(self):
        cases = {
            "issues": lambda: Issue.objects.create(project=self.project, title="t", reporter=self.owner),
            "projects": lambda: Project.objects.create(workspace=self.workspace, name="Q", owner=self.owner),
            "members": lambda: Membership.objects.filter(pk=self.mate_membership.pk).first().save(),
        }
        for area, change in cases.items():
            WorkspaceClock.objects.all().delete()
            before = self.earlier()
            change()
            self.assertIn(area, self.changes(before).data["changed"], area)
            self.assertNotIn(area, self.changes(self.later()).data["changed"], area)

    def test_comments_and_label_changes_count_as_issue_changes(self):
        issue = Issue.objects.create(project=self.project, title="t", reporter=self.owner)
        WorkspaceClock.objects.all().delete()
        Comment.objects.create(author=self.owner, body="hi", content_object=issue)
        self.assertEqual(self.changes(self.earlier()).data["changed"], ["issues"])
        WorkspaceClock.objects.all().delete()
        issue.labels.add(Label.objects.create(workspace=self.workspace, name="bug"))
        self.assertIn("issues", self.changes(self.earlier()).data["changed"])

    def test_notifications_and_invitations_are_personal(self):
        stranger = User.objects.create_user(username="lstranger", email="lstranger@example.com", password="pw")
        Notification.objects.create(recipient=self.mate, verb="commented", target=self.project)
        Invitation.objects.create(workspace=Workspace.objects.create(name="Other", owner=stranger), user=self.mate, invited_by=stranger)
        mine = self.changes(self.earlier()).data["changed"]
        theirs = self.changes(self.earlier(), user=self.mate).data["changed"]
        self.assertNotIn("notifications", mine)
        self.assertNotIn("invitations", mine)
        self.assertIn("notifications", theirs)
        self.assertIn("invitations", theirs)

    def test_a_change_stamped_just_before_the_cursor_is_still_reported_once(self):
        Issue.objects.create(project=self.project, title="t", reporter=self.owner)
        just_after = timezone.now() + timedelta(seconds=1)  # the cursor of a check that raced the write
        self.assertIn("issues", self.changes(just_after).data["changed"])

    def test_only_members_may_ask_and_ids_are_validated(self):
        outsider = User.objects.create_user(username="lout", email="lout@example.com", password="pw")
        self.assertEqual(self.changes(user=outsider).status_code, 403)
        self.assertEqual(APIClient(raise_request_exception=False).get("/api/v1/changes/", {"workspace": self.workspace.id}).status_code, 401)
        client = APIClient(raise_request_exception=False)
        client.force_authenticate(self.owner)
        self.assertEqual(client.get("/api/v1/changes/", {"workspace": "abc"}).status_code, 400)
        self.assertEqual(client.get("/api/v1/changes/", {"workspace": self.workspace.id, "since": "garbage"}).data["changed"], [])

    def test_deleting_a_whole_workspace_or_project_still_works(self):
        issue = Issue.objects.create(project=self.project, title="t", reporter=self.owner)
        Comment.objects.create(author=self.owner, body="hi", content_object=issue)
        other = Project.objects.create(workspace=self.workspace, name="Gone", owner=self.owner)
        Issue.objects.create(project=other, title="gone too", reporter=self.owner)
        other.delete()
        self.assertIn("projects", self.changes(self.earlier()).data["changed"])
        workspace_id = self.workspace.id
        self.workspace.delete()
        self.assertFalse(WorkspaceClock.objects.filter(workspace_id=workspace_id).exists())
        self.assertFalse(Issue.objects.exists())
        # Foreign keys are only checked at commit, which a TestCase never reaches: check them now, so a
        # clock row recreated for the deleted workspace (which would fail the real deletion) is caught.
        connection.check_constraints()

    def test_removing_a_member_marks_the_issues_they_were_unassigned_from(self):
        Issue.objects.create(project=self.project, title="theirs", reporter=self.owner, assignee=self.mate)
        WorkspaceClock.objects.all().delete()
        before = self.earlier()
        self.client.delete(f"/api/v1/workspaces/{self.workspace.id}/members/{self.mate.id}/")
        changed = self.changes(before).data["changed"]
        self.assertIn("issues", changed)
        self.assertIn("members", changed)
