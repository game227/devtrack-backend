from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from apps.integrations.models import GitHubPullRequest
from apps.issues.models import Issue
from apps.projects.models import Project
from apps.workspaces.models import Workspace


@override_settings(DEBUG=True)  # the command is for local development only
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


class SeedDemoProductionGuardTests(TestCase):
    """The demo accounts have passwords printed in the README; they must never appear on a real database."""

    @override_settings(DEBUG=False)
    def test_refuses_to_run_with_debug_off(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo")
        self.assertFalse(Workspace.objects.filter(name="Nova Labs").exists())

    @override_settings(DEBUG=False)
    def test_can_be_forced_explicitly(self):
        call_command("seed_demo", "--allow-production")
        self.assertTrue(Workspace.objects.filter(name="Nova Labs").exists())
