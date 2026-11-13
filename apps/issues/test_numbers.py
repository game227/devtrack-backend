import threading

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from apps.projects.models import Project
from apps.workspaces.models import Membership, Workspace

from .models import Issue

User = get_user_model()


def make_project(name="P", suffix=""):
    owner = User.objects.create_user(username=f"num-owner{suffix}", email=f"num-owner{suffix}@example.com", password="pw")
    workspace = Workspace.objects.create(name=f"W{suffix}", owner=owner)
    Membership.objects.create(workspace=workspace, user=owner, role="owner")
    return owner, Project.objects.create(workspace=workspace, name=name, owner=owner)


class IssueNumberTests(TestCase):
    def setUp(self):
        self.owner, self.project = make_project()

    def new_issue(self, project=None, **kwargs):
        return Issue.objects.create(project=project or self.project, title="t", reporter=self.owner, **kwargs)

    def test_numbers_count_up_from_one_in_each_project(self):
        other = Project.objects.create(workspace=self.project.workspace, name="Other", owner=self.owner)
        mine = [self.new_issue().number for _ in range(3)]
        theirs = [self.new_issue(other).number for _ in range(2)]
        self.assertEqual((mine, theirs), ([1, 2, 3], [1, 2]))

    def test_a_number_is_never_reused_after_its_issue_is_deleted(self):
        first, second = self.new_issue(), self.new_issue()
        second.delete()
        self.assertEqual(self.new_issue().number, first.number + 2)

    def test_updating_an_issue_never_renumbers_it(self):
        issue = self.new_issue()
        issue.title = "changed"
        issue.save()
        issue.refresh_from_db()
        self.assertEqual(issue.number, 1)

    def test_an_explicit_number_is_kept_and_the_counter_is_left_to_the_caller(self):
        imported = self.new_issue(number=12, github_number=12)
        self.assertEqual(imported.number, 12)

    def test_the_api_exposes_the_number_but_never_accepts_one(self):
        client = APIClient()
        client.force_authenticate(self.owner)
        created = client.post("/api/v1/issues/", {"project": self.project.id, "title": "x", "number": 99}, format="json")
        self.assertEqual((created.status_code, created.data["number"]), (201, 1))
        patched = client.patch(f"/api/v1/issues/{created.data['id']}/", {"number": 5}, format="json")
        self.assertEqual(patched.data["number"], 1)
        listed = client.get(f"/api/v1/issues/?project={self.project.id}")
        self.assertEqual([row["number"] for row in listed.data["results"]], [1])


class ConcurrentNumberingTests(TransactionTestCase):
    """Real threads with real connections: two requests creating issues at the same instant must not
    be handed the same number (the project row is locked while the number is allocated)."""

    def test_parallel_creation_never_duplicates_a_number(self):
        owner, project = make_project(suffix="-race")
        per_thread, threads, errors = 15, 4, []

        def worker():
            try:
                for _ in range(per_thread):
                    Issue.objects.create(project=project, title="race", reporter=owner)
            except Exception as exc:  # noqa: BLE001 — surfaced by the assertion below
                errors.append(exc)
            finally:
                connection.close()

        pool = [threading.Thread(target=worker) for _ in range(threads)]
        for thread in pool:
            thread.start()
        for thread in pool:
            thread.join()

        self.assertEqual(errors, [])
        numbers = sorted(Issue.objects.filter(project=project).values_list("number", flat=True))
        self.assertEqual(numbers, list(range(1, per_thread * threads + 1)))


class NumberBackfillMigrationTests(TransactionTestCase):
    """Runs the real migrations over existing data: this is what happens to the live database."""

    before = [("issues", "0004_issue_github_number_issue_github_url"), ("projects", "0005_projectmember_specialty")]
    after = [("issues", "0006_issue_number_required"), ("projects", "0006_project_issue_counter")]

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())  # leave the test database fully migrated
        super().tearDown()

    def test_existing_issues_are_numbered_oldest_first_and_github_numbers_are_kept(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        # The database already has every other app's latest tables, so build the historical models against
        # their latest state too (otherwise a NOT NULL column the old state does not know about breaks the insert).
        latest_others = [
            node for node in executor.loader.graph.leaf_nodes() if node[0] not in ("issues", "projects")
        ]
        old = executor.loader.project_state(self.before + latest_others).apps
        HistUser, HistWorkspace = old.get_model("accounts", "User"), old.get_model("workspaces", "Workspace")
        HistProject, HistIssue = old.get_model("projects", "Project"), old.get_model("issues", "Issue")

        user = HistUser.objects.create(username="mig", email="mig@example.com")
        workspace = HistWorkspace.objects.create(name="W", owner=user, slug="w")
        plain = HistProject.objects.create(workspace=workspace, name="plain", owner=user)
        imported = HistProject.objects.create(workspace=workspace, name="imported", owner=user)
        empty = HistProject.objects.create(workspace=workspace, name="empty", owner=user)

        def issue(project, title, **kw):
            return HistIssue.objects.create(project=project, title=title, reporter=user, **kw)

        a, b, c = issue(plain, "a"), issue(plain, "b"), issue(plain, "c")
        gh7 = issue(imported, "gh7", github_number=7)
        native = issue(imported, "native")
        gh3 = issue(imported, "gh3", github_number=3)
        dup = issue(imported, "dup", github_number=7)  # a repeated GitHub number must not break the constraint

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.after)
        new = executor.loader.project_state(self.after).apps
        Issue, Project = new.get_model("issues", "Issue"), new.get_model("projects", "Project")
        def number(i):
            return Issue.objects.get(pk=i.pk).number


        self.assertEqual([number(a), number(b), number(c)], [1, 2, 3])
        self.assertEqual((number(gh7), number(gh3)), (7, 3))  # GitHub's own numbers survive
        self.assertEqual((number(native), number(dup)), (8, 9))  # the rest continue after the highest, oldest first
        self.assertEqual(
            [Project.objects.get(pk=p.pk).issue_counter for p in (plain, imported, empty)], [3, 9, 0]
        )
