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


class CompletedAtTests(TestCase):
    def setUp(self):
        self.owner, self.project = make_project(suffix="-done")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def test_set_when_done_and_cleared_when_reopened_by_any_path(self):
        from apps.integrations.workflow import advance_issue

        issue = Issue.objects.create(project=self.project, title="t", reporter=self.owner)
        self.assertIsNone(issue.completed_at)
        advance_issue(issue, Issue.Status.DONE, self.owner)  # save(update_fields=[...]) path
        issue.refresh_from_db()
        self.assertIsNotNone(issue.completed_at)
        self.client.patch(f"/api/v1/issues/{issue.id}/", {"status": "todo"}, format="json")
        issue.refresh_from_db()
        self.assertIsNone(issue.completed_at)
        created_done = Issue.objects.create(project=self.project, title="d", reporter=self.owner, status="done")
        self.assertIsNotNone(created_done.completed_at)

    def test_the_board_can_load_open_work_and_the_latest_finished_work_separately(self):
        import datetime

        from django.utils import timezone

        for i in range(3):
            Issue.objects.create(project=self.project, title=f"open {i}", reporter=self.owner)
        finished = [Issue.objects.create(project=self.project, title=f"done {i}", reporter=self.owner, status="done") for i in range(3)]
        for offset, issue in enumerate(finished):
            Issue.objects.filter(pk=issue.pk).update(completed_at=timezone.now() - datetime.timedelta(days=offset))
        base = f"/api/v1/issues/?project={self.project.id}"
        open_rows = self.client.get(base + "&exclude_status=done").data
        done_rows = self.client.get(base + "&status=done&ordering=-completed_at").data
        self.assertEqual(open_rows["count"], 3)
        self.assertEqual([r["title"] for r in done_rows["results"]], ["done 0", "done 1", "done 2"])
        self.assertEqual(self.client.get(base + "&ordering=password").status_code, 200)  # unknown fields are ignored


class StableOrderingTests(TestCase):
    """Paging through a client-chosen order must neither repeat nor skip issues."""

    def setUp(self):
        self.owner, self.project = make_project(suffix="-order")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def collect(self, ordering):
        seen, page = [], 1
        while True:
            data = self.client.get(f"/api/v1/issues/?project={self.project.id}&ordering={ordering}&page={page}").data
            seen += [row["id"] for row in data["results"]]
            if not data["next"]:
                return seen
            page += 1

    def test_ties_and_empty_values_page_deterministically_with_empty_values_last(self):
        import datetime

        dated = [
            Issue.objects.create(project=self.project, title=f"d{i}", reporter=self.owner, due_date=datetime.date(2026, 1, 1 + i % 3))
            for i in range(9)
        ]
        undated = [Issue.objects.create(project=self.project, title=f"u{i}", reporter=self.owner) for i in range(45)]
        for ordering in ("due_date", "-due_date", "-completed_at"):
            ids = self.collect(ordering)
            self.assertEqual(len(ids), len(set(ids)), ordering)  # nothing twice
            self.assertEqual(set(ids), {i.id for i in dated + undated}, ordering)  # nothing missed
        ids = self.collect("due_date")
        self.assertEqual(set(ids[: len(dated)]), {i.id for i in dated})  # issues without a date come last
