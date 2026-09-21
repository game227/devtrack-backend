from django.core.management import call_command
from django.test import TestCase

from apps.integrations.models import GitHubPullRequest
from apps.issues.models import Issue
from apps.projects.models import Project
from apps.workspaces.models import Workspace


class SeedDemoTests(TestCase):
    def run_seed(self, *args):
        from io import StringIO

        out = StringIO()
        call_command("seed_demo", *args, stdout=out)
        return out.getvalue()

    def test_creates_a_populated_workspace(self):
        self.run_seed()
        workspace = Workspace.objects.get(name="Nova Labs")
        self.assertEqual(Project.objects.filter(workspace=workspace).count(), 5)
        self.assertGreater(Issue.objects.filter(project__workspace=workspace).count(), 30)
        self.assertTrue(GitHubPullRequest.objects.filter(merged=True).exists())
        statuses = set(Issue.objects.filter(project__workspace=workspace).values_list("status", flat=True))
        self.assertEqual(statuses, {"backlog", "todo", "in_progress", "in_review", "done"})

    def test_is_idempotent_and_reset_recreates(self):
        self.run_seed()
        issues_before = Issue.objects.count()
        self.assertIn("already exists", self.run_seed())
        self.assertEqual(Issue.objects.count(), issues_before)

        self.run_seed("--reset")
        self.assertEqual(Workspace.objects.filter(name="Nova Labs").count(), 1)
        self.assertEqual(Issue.objects.count(), issues_before)
