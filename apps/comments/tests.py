from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.issues.models import Issue
from apps.projects.models import Project
from apps.workspaces.models import Membership, Workspace

from .models import Comment

User = get_user_model()


class IssueCommentsViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="cowner", email="cowner@example.com", password="pw")
        self.member = User.objects.create_user(username="cmember", email="cmember@example.com", password="pw")
        self.outsider = User.objects.create_user(
            username="coutsider", email="coutsider@example.com", password="pw"
        )
        self.workspace = Workspace.objects.create(name="CWS", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role=Membership.Role.OWNER)
        Membership.objects.create(workspace=self.workspace, user=self.member, role=Membership.Role.MEMBER)
        self.project = Project.objects.create(workspace=self.workspace, name="P", owner=self.owner)
        self.issue = Issue.objects.create(project=self.project, title="Bug", reporter=self.owner)
        self.url = reverse("issue-comments", kwargs={"pk": self.issue.pk})
        self.client = APIClient()

    def test_outsider_cannot_view_comments(self):
        self.client.force_authenticate(self.outsider)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_member_can_add_a_comment(self):
        self.client.force_authenticate(self.member)
        response = self.client.post(self.url, {"body": "Looks good"}, format="json")
        self.assertEqual(response.status_code, 201)
        ct = ContentType.objects.get_for_model(Issue)
        self.assertTrue(Comment.objects.filter(content_type=ct, object_id=self.issue.pk, body="Looks good").exists())

    def test_member_can_list_comments(self):
        Comment.objects.create(
            content_type=ContentType.objects.get_for_model(Issue),
            object_id=self.issue.pk,
            author=self.owner,
            body="First",
        )
        self.client.force_authenticate(self.member)
        response = self.client.get(self.url)
        self.assertEqual(response.data["count"], 1)


class ProjectCommentsViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="pcowner", email="pcowner@example.com", password="pw")
        self.member = User.objects.create_user(username="pcmember", email="pcmember@example.com", password="pw")
        self.workspace = Workspace.objects.create(name="PCWS", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role=Membership.Role.OWNER)
        Membership.objects.create(workspace=self.workspace, user=self.member, role=Membership.Role.MEMBER)
        self.project = Project.objects.create(workspace=self.workspace, name="P", owner=self.owner)
        self.url = reverse("project-comments", kwargs={"pk": self.project.pk})
        self.client = APIClient()

    def test_member_can_comment_on_a_project(self):
        self.client.force_authenticate(self.member)
        response = self.client.post(self.url, {"body": "Kickoff notes"}, format="json")
        self.assertEqual(response.status_code, 201)


class CommentDetailViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="cdowner", email="cdowner@example.com", password="pw")
        self.author = User.objects.create_user(username="cdauthor", email="cdauthor@example.com", password="pw")
        self.member = User.objects.create_user(username="cdmember", email="cdmember@example.com", password="pw")
        self.workspace = Workspace.objects.create(name="CDWS", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role=Membership.Role.OWNER)
        Membership.objects.create(workspace=self.workspace, user=self.author, role=Membership.Role.MEMBER)
        Membership.objects.create(workspace=self.workspace, user=self.member, role=Membership.Role.MEMBER)
        self.project = Project.objects.create(workspace=self.workspace, name="P", owner=self.owner)
        self.issue = Issue.objects.create(project=self.project, title="Bug", reporter=self.owner)
        self.comment = Comment.objects.create(
            content_type=ContentType.objects.get_for_model(Issue),
            object_id=self.issue.pk,
            author=self.author,
            body="Original",
        )
        self.url = reverse("comment-detail", kwargs={"pk": self.comment.pk})
        self.client = APIClient()

    def test_author_can_edit_their_own_comment(self):
        self.client.force_authenticate(self.author)
        response = self.client.patch(self.url, {"body": "Edited"}, format="json")
        self.assertEqual(response.status_code, 200)

    def test_other_member_cannot_edit(self):
        self.client.force_authenticate(self.member)
        response = self.client.patch(self.url, {"body": "Hijack"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_workspace_admin_can_edit_someone_elses_comment(self):
        self.client.force_authenticate(self.owner)
        response = self.client.patch(self.url, {"body": "Moderated"}, format="json")
        self.assertEqual(response.status_code, 200)

    def test_author_can_delete_their_own_comment(self):
        self.client.force_authenticate(self.author)
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, 204)

    def test_workspace_member_can_view(self):
        self.client.force_authenticate(self.member)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_outsider_cannot_view_a_single_comment(self):
        # Regression check: the queryset backing this view is unscoped (Comment.objects.all()),
        # so without an object-level membership check GET would leak comments across workspaces.
        outsider = User.objects.create_user(username="cdoutsider", email="cdoutsider@example.com", password="pw")
        self.client.force_authenticate(outsider)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)
