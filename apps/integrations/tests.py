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
        # The merge is recorded once, as pr_merged — not additionally as a generic moved_issue.
        self.assertFalse(Activity.objects.filter(verb="moved_issue", object_id=self.issue.id).exists())

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


class EncryptedFieldKeyRotationTests(TestCase):
    OLD = "ZmRzYWZkc2FmZHNhZmRzYWZkc2FmZHNhZmRzYWZkc2E="  # 32 url-safe base64 bytes
    NEW = "bmV3a2V5bmV3a2V5bmV3a2V5bmV3a2V5bmV3a2V5bmU="

    def test_values_encrypted_with_an_old_key_stay_readable_after_adding_a_new_first_key(self):
        from django.db import connection

        user = User.objects.create_user(username="rotuser", email="rotuser@example.com", password="pw")
        with override_settings(FIELD_ENCRYPTION_KEY=self.OLD):
            account = GitHubAccount.objects.create(
                user=user, github_user_id=4242, github_username="rot", access_token="secret-token"
            )
            with connection.cursor() as cursor:
                cursor.execute("SELECT access_token FROM integrations_githubaccount WHERE id = %s", [account.id])
                old_ciphertext = cursor.fetchone()[0]

        self.assertNotIn("secret-token", old_ciphertext)
        with override_settings(FIELD_ENCRYPTION_KEY=f"{self.NEW},{self.OLD}"):
            self.assertEqual(GitHubAccount.objects.get(pk=account.pk).access_token, "secret-token")

    def test_rotate_command_reencrypts_with_the_primary_key(self):
        from django.core.management import call_command
        from django.db import connection

        user = User.objects.create_user(username="rotuser2", email="rotuser2@example.com", password="pw")
        with override_settings(FIELD_ENCRYPTION_KEY=self.OLD):
            account = GitHubAccount.objects.create(
                user=user, github_user_id=4343, github_username="rot2", access_token="another-secret"
            )

        with override_settings(FIELD_ENCRYPTION_KEY=f"{self.NEW},{self.OLD}"):
            call_command("rotate_encryption_key", stdout=__import__("io").StringIO())

        # After rotation the OLD key is no longer needed.
        with override_settings(FIELD_ENCRYPTION_KEY=self.NEW):
            self.assertEqual(GitHubAccount.objects.get(pk=account.pk).access_token, "another-secret")
        with connection.cursor() as cursor:
            cursor.execute("SELECT access_token FROM integrations_githubaccount WHERE id = %s", [account.id])
            self.assertNotIn("another-secret", cursor.fetchone()[0])


class OAuthScopeTests(TestCase):
    @override_settings(GITHUB_CLIENT_ID="cid", GITHUB_OAUTH_SCOPE="public_repo admin:repo_hook")
    def test_authorize_url_uses_the_configured_scope(self):
        from urllib.parse import parse_qs, urlparse

        from .services import build_authorize_url

        query = parse_qs(urlparse(build_authorize_url("state123")).query)
        self.assertEqual(query["scope"], ["public_repo admin:repo_hook"])


from unittest.mock import patch  # noqa: E402

from apps.projects.models import Label, ProjectMember  # noqa: E402

from .models import GitHubPullRequest  # noqa: E402


class GitHubFlowBase(TestCase):
    """A workspace admin with a (fake) connected GitHub account."""

    def setUp(self):
        self.user = User.objects.create_user(username="gfadmin", email="gfadmin@example.com", password="pw")
        self.member = User.objects.create_user(username="gfmember", email="gfmember@example.com", password="pw")
        self.workspace = Workspace.objects.create(name="GFWS", owner=self.user)
        Membership.objects.create(workspace=self.workspace, user=self.user, role="owner")
        Membership.objects.create(workspace=self.workspace, user=self.member, role="member")
        GitHubAccount.objects.create(user=self.user, github_user_id=501, github_username="gfadmin-gh", access_token="tok")
        self.client = APIClient()
        self.client.force_authenticate(self.user)


@override_settings(GITHUB_WEBHOOK_CALLBACK_URL="http://localhost:8000/api/v1/integrations/github/webhook/")
class LinkWithoutPublicWebhookTests(GitHubFlowBase):
    def test_linking_works_when_the_server_is_not_publicly_reachable(self):
        project = Project.objects.create(workspace=self.workspace, name="P", owner=self.user)
        with patch("apps.integrations.views.services.create_webhook") as create_webhook:
            response = self.client.post(
                reverse("project-github-link", kwargs={"project_id": project.id}),
                {"github_repo_id": 77, "full_name": "me/repo"},
                format="json",
            )
        self.assertEqual(response.status_code, 201)
        create_webhook.assert_not_called()  # GitHub would reject a localhost hook anyway
        self.assertFalse(response.data["webhook_installed"])
        self.assertEqual(response.data["webhook_warning"]["code"], "not_public_url")
        self.assertTrue(GitHubRepositoryLink.objects.filter(project=project, webhook_id__isnull=True).exists())

    @override_settings(GITHUB_WEBHOOK_CALLBACK_URL="https://devtrack.example.com/api/v1/integrations/github/webhook/")
    def test_a_rejected_webhook_still_links_and_reports_githubs_reason(self):
        from .services import GitHubAPIError

        project = Project.objects.create(workspace=self.workspace, name="P2", owner=self.user)
        with patch("apps.integrations.views.services.create_webhook", side_effect=GitHubAPIError("GitHub refused: Not Found")):
            response = self.client.post(
                reverse("project-github-link", kwargs={"project_id": project.id}),
                {"github_repo_id": 78, "full_name": "me/other"},
                format="json",
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["webhook_warning"], {"code": "github_rejected", "detail": "GitHub refused: Not Found"})

    @override_settings(GITHUB_WEBHOOK_CALLBACK_URL="https://devtrack.example.com/api/v1/integrations/github/webhook/")
    def test_a_public_server_installs_the_webhook(self):
        project = Project.objects.create(workspace=self.workspace, name="P3", owner=self.user)
        with patch("apps.integrations.views.services.create_webhook", return_value={"id": 4242}):
            response = self.client.post(
                reverse("project-github-link", kwargs={"project_id": project.id}),
                {"github_repo_id": 79, "full_name": "me/third"},
                format="json",
            )
        self.assertTrue(response.data["webhook_installed"])
        self.assertIsNone(response.data["webhook_warning"])


class IsPublicUrlTests(TestCase):
    def test_classifies_hosts(self):
        from .services import is_public_url

        self.assertFalse(is_public_url("http://localhost:8000/x"))
        self.assertFalse(is_public_url("http://127.0.0.1:8000/x"))
        self.assertFalse(is_public_url("http://printer.local/x"))
        self.assertTrue(is_public_url("https://devtrack.onrender.com/x"))


GITHUB_ISSUES = [
    {"number": 1, "title": "Crash on start", "body": "Steps…", "state": "open", "html_url": "https://github.com/me/repo/issues/1",
     "labels": [{"name": "bug", "color": "d73a4a"}], "assignee": {"login": "gfmember-gh"}},
    {"number": 2, "title": "Add dark mode", "body": None, "state": "closed", "html_url": "https://github.com/me/repo/issues/2",
     "labels": [{"name": "enhancement", "color": "a2eeef"}, {"name": "ui", "color": "ffffff"}], "assignee": None},
]


@override_settings(GITHUB_WEBHOOK_CALLBACK_URL="http://localhost:8000/x/")
class ImportFromGitHubTests(GitHubFlowBase):
    url = property(lambda self: reverse("github-import"))

    def post(self, **overrides):
        payload = {"workspace": self.workspace.id, "github_repo_id": 900, "full_name": "me/repo", **overrides}
        with patch("apps.integrations.views.services.get_repo", return_value={"name": "repo", "description": "A repo", "html_url": "https://github.com/me/repo"}), \
             patch("apps.integrations.views.services.list_repo_issues", return_value=GITHUB_ISSUES):
            return self.client.post(self.url, payload, format="json")

    def test_creates_a_project_links_the_repo_and_imports_issues(self):
        gh_member = User.objects.get(username="gfmember")
        GitHubAccount.objects.create(user=gh_member, github_user_id=502, github_username="gfmember-gh", access_token="t2")

        response = self.post()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["issues_imported"], 2)
        project = Project.objects.get(pk=response.data["project"]["id"])
        self.assertEqual((project.name, project.description, project.status), ("repo", "A repo", "active"))
        self.assertEqual(project.repository_url, "https://github.com/me/repo")
        self.assertTrue(ProjectMember.objects.filter(project=project, user=self.user, role="owner").exists())
        self.assertEqual(project.github_link.full_name, "me/repo")

        crash, dark = Issue.objects.get(project=project, github_number=1), Issue.objects.get(project=project, github_number=2)
        self.assertEqual((crash.type, crash.status, crash.assignee), ("bug", "todo", gh_member))
        self.assertEqual((dark.type, dark.status), ("feature", "done"))
        self.assertEqual(dark.github_url, "https://github.com/me/repo/issues/2")
        self.assertEqual({label.name for label in dark.labels.all()}, {"enhancement", "ui"})
        self.assertTrue(Label.objects.filter(workspace=self.workspace, name="bug", color="#d73a4a").exists())

    def test_issues_can_be_skipped(self):
        response = self.post(import_issues=False)
        self.assertEqual(response.status_code, 201)
        # get_repo is still patched; list_repo_issues must not have been used to create issues
        self.assertEqual(Issue.objects.filter(project_id=response.data["project"]["id"]).count(), 0)

    def test_only_workspace_admins_can_import(self):
        self.client.force_authenticate(self.member)
        self.assertEqual(self.post().status_code, 403)

    def test_requires_a_connected_github_account(self):
        GitHubAccount.objects.filter(user=self.user).delete()
        # a fresh instance: the reverse one-to-one is cached on the original object
        self.client.force_authenticate(User.objects.get(pk=self.user.pk))
        response = self.post()
        self.assertEqual(response.status_code, 400)
        self.assertIn("Connect your GitHub account", str(response.data))

    def test_a_repository_can_only_be_imported_once(self):
        self.assertEqual(self.post().status_code, 201)
        self.assertEqual(self.post().status_code, 400)

    def test_a_github_failure_leaves_nothing_behind(self):
        from .services import GitHubAPIError

        with patch("apps.integrations.views.services.get_repo", side_effect=GitHubAPIError("Could not read that repository: Not Found")):
            response = self.client.post(
                self.url, {"workspace": self.workspace.id, "github_repo_id": 901, "full_name": "me/missing"}, format="json"
            )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Project.objects.filter(workspace=self.workspace).exists())


class GitHubNumberMatchingTests(GitHubFlowBase):
    def test_hash_references_use_githubs_numbering_in_imported_projects(self):
        project = Project.objects.create(workspace=self.workspace, name="Imported", owner=self.user)
        imported = Issue.objects.create(project=project, title="From GH", reporter=self.user, github_number=12)
        native = Issue.objects.create(project=project, title="Native", reporter=self.user)  # its DevTrack id may be anything
        link = GitHubRepositoryLink.objects.create(
            project=project, github_repo_id=1, full_name="me/imp", webhook_id=None, connected_by=self.user
        )
        from .views import _match_issues

        self.assertEqual(_match_issues(project, {12}), [imported])
        self.assertEqual(_match_issues(project, {native.id}), [native])  # falls back to the DevTrack id
        self.assertEqual(_match_issues(project, set()), [])
        self.assertIsNotNone(link)


class ManualSyncTests(GitHubFlowBase):
    def setUp(self):
        super().setUp()
        self.project = Project.objects.create(workspace=self.workspace, name="Sync", owner=self.user)
        self.issue = Issue.objects.create(project=self.project, title="Fix me", reporter=self.user, github_number=7)
        GitHubRepositoryLink.objects.create(
            project=self.project, github_repo_id=321, full_name="me/sync", webhook_id=None, connected_by=self.user
        )
        self.url = reverse("project-github-sync", kwargs={"project_id": self.project.id})

    def sync(self, pulls, commits):
        with patch("apps.integrations.views.services.list_repo_pulls", return_value=pulls), \
             patch("apps.integrations.views.services.list_repo_commits", return_value=commits):
            return self.client.post(self.url)

    def test_pulls_commits_and_merges_are_processed_like_webhooks(self):
        pulls = [{
            "id": 9001, "number": 30, "title": "Fixes #7", "body": "", "state": "closed", "merged_at": "2026-09-20T10:00:00Z",
            "html_url": "https://github.com/me/sync/pull/30", "user": {"login": "someone"}, "head": {"ref": "fix"}, "base": {"ref": "main"},
        }]
        commits = [{"sha": "abc1234" * 5 + "abcde", "commit": {"message": "Work on #7", "author": {"name": "Dev"}},
                    "author": {"login": "dev"}, "html_url": "https://github.com/me/sync/commit/abc"}]

        response = self.sync(pulls, commits)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"pull_requests": 1, "commits": 1})
        self.issue.refresh_from_db()
        self.assertEqual(self.issue.status, Issue.Status.DONE)  # merged PR closes it
        pr = GitHubPullRequest.objects.get(number=30)
        self.assertTrue(pr.merged)
        self.assertEqual(list(pr.issues.all()), [self.issue])
        self.assertEqual(GitHubCommit.objects.get().issues.get(), self.issue)
        self.assertEqual(Activity.objects.filter(verb="pr_merged").count(), 1)

    def test_syncing_twice_is_idempotent(self):
        pulls = [{"id": 9002, "number": 31, "title": "WIP #7", "body": "", "state": "open", "merged_at": None,
                  "html_url": "https://x/31", "user": {"login": "a"}, "head": {"ref": "h"}, "base": {"ref": "main"}}]
        self.sync(pulls, [])
        self.sync(pulls, [])
        self.assertEqual(GitHubPullRequest.objects.filter(number=31).count(), 1)
        self.issue.refresh_from_db()
        self.assertNotEqual(self.issue.status, Issue.Status.DONE)  # an open PR does not close it

    def test_github_errors_are_reported(self):
        from .services import GitHubAPIError

        with patch("apps.integrations.views.services.list_repo_pulls", side_effect=GitHubAPIError("Could not read the repository's pull requests: Not Found")):
            response = self.client.post(self.url)
        self.assertEqual(response.status_code, 400)

    def test_unlinked_projects_and_outsiders(self):
        other = Project.objects.create(workspace=self.workspace, name="Unlinked", owner=self.user)
        self.assertEqual(self.client.post(reverse("project-github-sync", kwargs={"project_id": other.id})).status_code, 404)
        outsider = User.objects.create_user(username="gfout", email="gfout@example.com", password="pw")
        self.client.force_authenticate(outsider)
        self.assertEqual(self.client.post(self.url).status_code, 403)


class RepoListFlagsTests(TestCase):
    def test_repos_without_admin_rights_are_listed_with_a_flag(self):
        from .services import list_repo_issues, list_user_repos  # noqa: F401

        payload = [
            {"id": 1, "full_name": "me/mine", "private": False, "html_url": "https://github.com/me/mine", "permissions": {"admin": True}},
            {"id": 2, "full_name": "org/theirs", "private": True, "html_url": "https://github.com/org/theirs", "permissions": {"admin": False}},
        ]
        with patch("apps.integrations.services.requests.get") as get:
            get.return_value.status_code = 200
            get.return_value.json.return_value = payload
            repos = list_user_repos("tok")
        self.assertEqual([(r["full_name"], r["admin"]) for r in repos], [("me/mine", True), ("org/theirs", False)])

    def test_issue_listing_skips_pull_requests(self):
        from .services import list_repo_issues

        with patch("apps.integrations.services.requests.get") as get:
            get.return_value.status_code = 200
            get.return_value.json.return_value = [{"number": 1, "title": "issue"}, {"number": 2, "title": "pr", "pull_request": {}}]
            self.assertEqual([i["number"] for i in list_repo_issues("tok", "me/repo")], [1])
