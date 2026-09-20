from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.comments.models import Comment
from apps.issues.models import Issue
from apps.projects.models import Project
from apps.workspaces.models import Membership, Workspace

from .models import Activity

User = get_user_model()


class ActivitySignalTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="auser", email="auser@example.com", password="pw")
        self.workspace = Workspace.objects.create(name="AWS", owner=self.user)
        Membership.objects.create(workspace=self.workspace, user=self.user, role=Membership.Role.OWNER)

    def test_creating_a_project_logs_an_activity(self):
        project = Project.objects.create(workspace=self.workspace, name="P", owner=self.user)
        activity = Activity.objects.get(verb="created_project", object_id=project.id)
        self.assertEqual(activity.actor, self.user)

    def test_creating_an_issue_logs_an_activity(self):
        project = Project.objects.create(workspace=self.workspace, name="P", owner=self.user)
        issue = Issue.objects.create(project=project, title="Bug", reporter=self.user)
        activity = Activity.objects.get(verb="created_issue", object_id=issue.id)
        self.assertEqual(activity.actor, self.user)

    def test_moving_an_issue_status_logs_a_moved_activity(self):
        project = Project.objects.create(workspace=self.workspace, name="P", owner=self.user)
        issue = Issue.objects.create(project=project, title="Bug", reporter=self.user)
        issue.status = Issue.Status.IN_PROGRESS
        issue.save()
        activity = Activity.objects.get(verb="moved_issue", object_id=issue.id)
        self.assertEqual(activity.metadata, {"from": Issue.Status.BACKLOG, "to": Issue.Status.IN_PROGRESS})

    def test_updating_an_issue_without_status_change_does_not_log_a_move(self):
        project = Project.objects.create(workspace=self.workspace, name="P", owner=self.user)
        issue = Issue.objects.create(project=project, title="Bug", reporter=self.user)
        issue.title = "Renamed"
        issue.save()
        self.assertFalse(Activity.objects.filter(verb="moved_issue", object_id=issue.id).exists())

    def test_commenting_logs_an_activity(self):
        project = Project.objects.create(workspace=self.workspace, name="P", owner=self.user)
        issue = Issue.objects.create(project=project, title="Bug", reporter=self.user)
        comment = Comment.objects.create(
            content_type=ContentType.objects.get_for_model(Issue),
            object_id=issue.pk,
            author=self.user,
            body="Note",
        )
        activity = Activity.objects.get(verb="commented", object_id=comment.id)
        self.assertEqual(activity.workspace, self.workspace)


class ActivityListViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="alowner", email="alowner@example.com", password="pw")
        self.outsider = User.objects.create_user(
            username="aloutsider", email="aloutsider@example.com", password="pw"
        )
        self.workspace = Workspace.objects.create(name="ALWS", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role=Membership.Role.OWNER)
        self.project = Project.objects.create(workspace=self.workspace, name="P", owner=self.owner)
        self.issue = Issue.objects.create(project=self.project, title="Bug", reporter=self.owner)
        self.url = reverse("activity-list")
        self.client = APIClient()

    def test_requires_project_or_workspace(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 400)

    def test_outsider_cannot_view_workspace_activity(self):
        self.client.force_authenticate(self.outsider)
        response = self.client.get(self.url, {"workspace": self.workspace.id})
        self.assertEqual(response.status_code, 403)

    def test_workspace_scope_includes_project_and_issue_activity(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get(self.url, {"workspace": self.workspace.id})
        verbs = {row["verb"] for row in response.data["results"]}
        self.assertIn("created_project", verbs)
        self.assertIn("created_issue", verbs)

    def test_project_scope_only_includes_that_projects_issues(self):
        other_project = Project.objects.create(workspace=self.workspace, name="Other", owner=self.owner)
        Issue.objects.create(project=other_project, title="Other bug", reporter=self.owner)

        self.client.force_authenticate(self.owner)
        response = self.client.get(self.url, {"project": self.project.id})
        targets = [(row["target_type"], row["target_id"]) for row in response.data["results"]]
        self.assertIn(("issue", self.issue.id), targets)
        self.assertNotIn(
            ("issue", Issue.objects.get(title="Other bug").id), targets
        )
