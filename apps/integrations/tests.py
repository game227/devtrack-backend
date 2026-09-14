import hashlib
import hmac
import json

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.activities.models import Activity
from apps.issues.models import Issue
from apps.projects.models import Project
from apps.workspaces.models import Membership, Workspace

from .models import GitHubAccount, GitHubCommit, GitHubRepositoryLink
from .parsing import extract_issue_ids

User = get_user_model()
WEBHOOK_SECRET = "test-webhook-secret"


def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()


class ExtractIssueIdsTests(TestCase):
    def test_extracts_bare_hash_reference(self):
        self.assertEqual(extract_issue_ids("fixes #42"), {42})

    def test_extracts_multiple_and_dedupes_across_texts(self):
        self.assertEqual(extract_issue_ids("closes #1 and #2", "also #1"), {1, 2})

    def test_no_references_returns_empty_set(self):
        self.assertEqual(extract_issue_ids("just a message", ""), set())

    def test_tolerates_none(self):
        self.assertEqual(extract_issue_ids(None, "fixes #5"), {5})


@override_settings(GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET)
class WebhookTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", email="owner@example.com", password="pw")
        self.workspace = Workspace.objects.create(name="WS", owner=self.user)
        Membership.objects.create(workspace=self.workspace, user=self.user, role="owner")
        self.project = Project.objects.create(workspace=self.workspace, name="P", owner=self.user)
        self.other_project = Project.objects.create(workspace=self.workspace, name="Other", owner=self.user)
        self.issue = Issue.objects.create(project=self.project, title="Bug", reporter=self.user)
        self.other_issue = Issue.objects.create(project=self.other_project, title="Other bug", reporter=self.user)
        GitHubRepositoryLink.objects.create(
            project=self.project,
            github_repo_id=111,
            full_name="acme/widgets",
            webhook_id=1,
            connected_by=self.user,
        )
        self.url = reverse("github-webhook")
        self.client = APIClient()

    def post_event(self, event, payload):
        body = json.dumps(payload).encode()
        return self.client.post(
            self.url,
            data=body,
            content_type="application/json",
            HTTP_X_GITHUB_EVENT=event,
            HTTP_X_HUB_SIGNATURE_256=sign(body),
        )

    def test_ping(self):
        response = self.post_event("ping", {"repository": {"id": 111}})
        self.assertEqual(response.status_code, 200)

    def test_bad_signature_rejected(self):
        body = json.dumps({"repository": {"id": 111}}).encode()
        response = self.client.post(
            self.url,
            data=body,
            content_type="application/json",
            HTTP_X_GITHUB_EVENT="ping",
            HTTP_X_HUB_SIGNATURE_256="sha256=deadbeef",
        )
        self.assertEqual(response.status_code, 403)

    def test_empty_secret_always_rejects(self):
        body = json.dumps({"repository": {"id": 111}}).encode()
        with override_settings(GITHUB_WEBHOOK_SECRET=""):
            response = self.client.post(
                self.url,
                data=body,
                content_type="application/json",
                HTTP_X_GITHUB_EVENT="ping",
                HTTP_X_HUB_SIGNATURE_256=sign(body),
            )
        self.assertEqual(response.status_code, 403)

    def test_unlinked_repo_is_a_noop_200(self):
        response = self.post_event("ping", {"repository": {"id": 999999999}})
        self.assertEqual(response.status_code, 200)

    def test_push_links_commit_to_issue(self):
        response = self.post_event(
            "push",
            {
                "repository": {"id": 111},
                "commits": [
                    {
                        "id": "abc123",
                        "message": f"fix it, fixes #{self.issue.id}",
                        "url": "https://x/commit/abc123",
                        "author": {"name": "Dev", "username": "dev"},
                    }
                ],
            },
        )
        self.assertEqual(response.status_code, 200)
        commit = GitHubCommit.objects.get(sha="abc123")
        self.assertEqual(list(commit.issues.values_list("id", flat=True)), [self.issue.id])

    def test_push_replay_is_idempotent(self):
        payload = {
            "repository": {"id": 111},
            "commits": [
                {
                    "id": "dup1",
                    "message": f"fixes #{self.issue.id}",
                    "url": "https://x/commit/dup1",
                    "author": {"name": "Dev", "username": "dev"},
                }
            ],
        }
        self.post_event("push", payload)
        self.post_event("push", payload)
        self.assertEqual(GitHubCommit.objects.filter(sha="dup1").count(), 1)

    def test_push_scopes_issue_matching_to_linked_project(self):
        response = self.post_event(
            "push",
            {
                "repository": {"id": 111},
                "commits": [
                    {
                        "id": "scoped1",
                        "message": f"fixes #{self.other_issue.id}",
                        "url": "https://x/commit/scoped1",
                        "author": {"name": "Dev", "username": "dev"},
                    }
                ],
            },
        )
        self.assertEqual(response.status_code, 200)
        commit = GitHubCommit.objects.get(sha="scoped1")
        self.assertEqual(commit.issues.count(), 0)

    def test_push_malformed_commit_does_not_500(self):
        response = self.post_event(
            "push", {"repository": {"id": 111}, "commits": [{"message": "missing the id key"}]}
        )
        self.assertEqual(response.status_code, 200)

    def test_pull_request_merge_marks_issue_done_and_logs_activity(self):
        self.assertNotEqual(self.issue.status, Issue.Status.DONE)
        response = self.post_event(
            "pull_request",
            {
                "action": "closed",
                "repository": {"id": 111},
                "pull_request": {
                    "id": 555,
                    "number": 7,
                    "title": f"Fix, closes #{self.issue.id}",
                    "body": "",
                    "state": "closed",
                    "merged": True,
                    "html_url": "https://x/pull/7",
                    "user": {"login": "someone-unmatched"},
                    "head": {"ref": "fix"},
                    "base": {"ref": "main"},
                },
            },
        )
        self.assertEqual(response.status_code, 200)
        self.issue.refresh_from_db()
        self.assertEqual(self.issue.status, Issue.Status.DONE)
        activity = Activity.objects.get(verb="pr_merged")
        self.assertEqual(activity.actor, self.user)  # no matching GitHubAccount -> falls back to connected_by
        self.assertEqual(activity.target, self.issue)

    def test_pull_request_open_does_not_close_issue(self):
        self.post_event(
            "pull_request",
            {
                "action": "opened",
                "repository": {"id": 111},
                "pull_request": {
                    "id": 556,
                    "number": 8,
                    "title": f"WIP #{self.issue.id}",
                    "body": "",
                    "state": "open",
                    "merged": False,
                    "html_url": "https://x/pull/8",
                    "user": {"login": "someone"},
                    "head": {"ref": "wip"},
                    "base": {"ref": "main"},
                },
            },
        )
        self.issue.refresh_from_db()
        self.assertNotEqual(self.issue.status, Issue.Status.DONE)

    def test_pr_actor_resolves_to_matched_github_account(self):
        author = User.objects.create_user(username="prauthor", email="prauthor@example.com", password="pw")
        GitHubAccount.objects.create(
            user=author, github_user_id=999, github_username="octocat", access_token="tok"
        )
        self.post_event(
            "pull_request",
            {
                "action": "closed",
                "repository": {"id": 111},
                "pull_request": {
                    "id": 557,
                    "number": 9,
                    "title": f"Fix, closes #{self.issue.id}",
                    "body": "",
                    "state": "closed",
                    "merged": True,
                    "html_url": "https://x/pull/9",
                    "user": {"login": "octocat"},
                    "head": {"ref": "fix"},
                    "base": {"ref": "main"},
                },
            },
        )
        activity = Activity.objects.get(verb="pr_merged", object_id=self.issue.id)
        self.assertEqual(activity.actor, author)


class ProjectGithubLinkPermissionTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner2", email="owner2@example.com", password="pw")
        self.member = User.objects.create_user(username="member2", email="member2@example.com", password="pw")
        self.workspace = Workspace.objects.create(name="WS2", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role="owner")
        Membership.objects.create(workspace=self.workspace, user=self.member, role="member")
        self.project = Project.objects.create(workspace=self.workspace, name="P2", owner=self.owner)
        self.url = reverse("project-github-link", kwargs={"project_id": self.project.id})

    def test_member_can_view_link_status(self):
        client = APIClient()
        client.force_authenticate(self.member)
        response = client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"linked": False})

    def test_member_cannot_link_a_repo(self):
        client = APIClient()
        client.force_authenticate(self.member)
        response = client.post(self.url, {"github_repo_id": 1, "full_name": "a/b"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_admin_without_github_account_gets_clear_error(self):
        client = APIClient()
        client.force_authenticate(self.owner)
        response = client.post(self.url, {"github_repo_id": 1, "full_name": "a/b"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_delete_when_not_linked_is_404(self):
        client = APIClient()
        client.force_authenticate(self.owner)
        response = client.delete(self.url)
        self.assertEqual(response.status_code, 404)
