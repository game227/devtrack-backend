from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.projects.models import Project
from apps.workspaces.models import Membership, Workspace

from .models import Issue

User = get_user_model()


class AssigneeEditRightsTests(TestCase):
    """The creator may change anything; the person it is assigned to may report progress (status and
    priority) but not rewrite the issue; everyone else may only read."""

    def setUp(self):
        def mk(name):
            return User.objects.create_user(username=name, email=f"{name}@example.com", password="pw")

        self.creator, self.assignee, self.other, self.admin = mk("creator"), mk("assignee"), mk("other"), mk("adm")
        self.workspace = Workspace.objects.create(name="W", owner=self.creator)
        for user, role in (
            (self.creator, "owner"),
            (self.assignee, "member"),
            (self.other, "member"),
            (self.admin, "admin"),
        ):
            Membership.objects.create(workspace=self.workspace, user=user, role=role)
        self.project = Project.objects.create(workspace=self.workspace, name="P", owner=self.creator)
        self.issue = Issue.objects.create(
            project=self.project, title="Ship it", reporter=self.creator, assignee=self.assignee
        )
        self.url = f"/api/v1/issues/{self.issue.id}/"

    def as_user(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def test_the_assignee_can_move_the_issue_and_change_its_priority(self):
        client = self.as_user(self.assignee)
        response = client.patch(self.url, {"status": "in_progress", "priority": "high"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.issue.refresh_from_db()
        self.assertEqual((self.issue.status, self.issue.priority), ("in_progress", "high"))

    def test_the_assignee_cannot_rewrite_or_reassign_the_issue(self):
        client = self.as_user(self.assignee)
        for payload in (
            {"title": "hijacked"},
            {"description": "x"},
            {"assignee_id": self.other.id},
            {"status": "done", "title": "sneaky"},  # one allowed field does not excuse a forbidden one
            {"due_date": "2030-01-01"},
            {},
        ):
            self.assertEqual(client.patch(self.url, payload, format="json").status_code, 403, payload)
        full = {"title": "Ship it", "status": "done"}
        self.assertEqual(client.put(self.url, full, format="json").status_code, 403)  # PUT replaces everything
        self.issue.refresh_from_db()
        self.assertEqual((self.issue.title, self.issue.status), ("Ship it", Issue.Status.BACKLOG))

    def test_the_creator_can_change_anything(self):
        response = self.as_user(self.creator).patch(self.url, {"title": "Renamed", "assignee_id": self.other.id}, format="json")
        self.assertEqual(response.status_code, 200, response.data)

    def test_other_members_and_even_admins_cannot_edit(self):
        for user in (self.other, self.admin):
            self.assertEqual(self.as_user(user).patch(self.url, {"status": "done"}, format="json").status_code, 403, user.username)

    def test_an_assignee_who_left_the_workspace_loses_the_right(self):
        Membership.objects.filter(workspace=self.workspace, user=self.assignee).delete()
        self.assertEqual(self.as_user(self.assignee).patch(self.url, {"status": "done"}, format="json").status_code, 403)

    def test_admins_can_still_delete_and_everyone_in_the_workspace_can_read(self):
        self.assertEqual(self.as_user(self.other).get(self.url).status_code, 200)
        self.assertEqual(self.as_user(self.other).delete(self.url).status_code, 403)
        self.assertEqual(self.as_user(self.admin).delete(self.url).status_code, 204)
