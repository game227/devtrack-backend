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


class ActivityActorTests(TestCase):
    def setUp(self):
        self.reporter = User.objects.create_user(username="actrep", email="actrep@example.com", password="pw")
        self.mover = User.objects.create_user(username="actmove", email="actmove@example.com", password="pw")
        self.workspace = Workspace.objects.create(name="ACTWS", owner=self.reporter)
        Membership.objects.create(workspace=self.workspace, user=self.reporter, role=Membership.Role.OWNER)
        Membership.objects.create(workspace=self.workspace, user=self.mover, role=Membership.Role.MEMBER)
        self.project = Project.objects.create(workspace=self.workspace, name="P", owner=self.reporter)
        self.issue = Issue.objects.create(project=self.project, title="Bug", reporter=self.reporter)
        self.client = APIClient()

    def test_a_status_change_is_attributed_to_the_user_who_made_it(self):
        # Only the reporter can PATCH an issue via the API now (IsIssueReporter) — but the
        # _actor mechanism is general-purpose (the GitHub PR-merge handler also sets it, to a
        # resolved GitHub author), so it's exercised directly at the model layer here rather
        # than through a view that would reject a non-reporter's PATCH.
        self.issue.status = Issue.Status.IN_PROGRESS
        self.issue._actor = self.mover
        self.issue.save()
        activity = Activity.objects.get(verb="moved_issue", object_id=self.issue.id)
        self.assertEqual(activity.actor, self.mover)  # not the reporter

    def test_the_view_attributes_the_reporters_own_change_via_the_api(self):
        self.client.force_authenticate(self.reporter)
        response = self.client.patch(
            reverse("issue-detail", kwargs={"pk": self.issue.pk}), {"status": "in_progress"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        activity = Activity.objects.get(verb="moved_issue", object_id=self.issue.id)
        self.assertEqual(activity.actor, self.reporter)

    def test_without_a_request_user_the_reporter_is_the_fallback(self):
        self.issue.status = Issue.Status.DONE
        self.issue.save()
        self.assertEqual(Activity.objects.get(verb="moved_issue", object_id=self.issue.id).actor, self.reporter)

    def test_callers_can_opt_out_of_the_generic_moved_activity(self):
        self.issue.status = Issue.Status.DONE
        self.issue._skip_move_activity = True
        self.issue.save()
        self.assertFalse(Activity.objects.filter(verb="moved_issue", object_id=self.issue.id).exists())


class ProjectTimelineQueryTests(TestCase):
    def test_includes_project_issue_and_comment_activity_but_not_other_projects(self):
        owner = User.objects.create_user(username="tlowner", email="tlowner@example.com", password="pw")
        workspace = Workspace.objects.create(name="TLWS", owner=owner)
        Membership.objects.create(workspace=workspace, user=owner, role=Membership.Role.OWNER)
        mine = Project.objects.create(workspace=workspace, name="Mine", owner=owner)
        other = Project.objects.create(workspace=workspace, name="Other", owner=owner)
        my_issue = Issue.objects.create(project=mine, title="Mine bug", reporter=owner)
        other_issue = Issue.objects.create(project=other, title="Other bug", reporter=owner)
        Comment.objects.create(
            content_type=ContentType.objects.get_for_model(Issue), object_id=my_issue.pk, author=owner, body="hi"
        )
        Comment.objects.create(
            content_type=ContentType.objects.get_for_model(Issue), object_id=other_issue.pk, author=owner, body="no"
        )

        from .queries import project_timeline_queryset

        verbs_and_ids = {(a.verb, a.object_id) for a in project_timeline_queryset(mine)}
        self.assertIn(("created_project", mine.id), verbs_and_ids)
        self.assertIn(("created_issue", my_issue.id), verbs_and_ids)
        self.assertNotIn(("created_project", other.id), verbs_and_ids)
        self.assertNotIn(("created_issue", other_issue.id), verbs_and_ids)
        self.assertEqual(sum(1 for verb, _ in verbs_and_ids if verb == "commented"), 1)

    def test_is_a_single_query_with_subqueries_not_materialized_id_lists(self):
        owner = User.objects.create_user(username="tlowner2", email="tlowner2@example.com", password="pw")
        workspace = Workspace.objects.create(name="TLWS2", owner=owner)
        project = Project.objects.create(workspace=workspace, name="P", owner=owner)
        for i in range(5):
            Issue.objects.create(project=project, title=f"I{i}", reporter=owner)

        from .queries import project_timeline_queryset

        with self.assertNumQueries(1):
            list(project_timeline_queryset(project))
