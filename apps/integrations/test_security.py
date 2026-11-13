"""GitHub integration security tests. Each case was reproduced against the previous code first."""

import datetime
import hashlib
import hmac
import json
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.activities.models import Activity
from apps.issues.models import Issue
from apps.projects.models import Project
from apps.workspaces.models import Membership, Workspace

from . import services
from .models import GitHubAccount, GitHubPendingConnection, GitHubRepositoryLink

User = get_user_model()
NONCE = "n" * 40
VIEWS = "apps.integrations.views.services"


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def github_answers(gh_id=4242, login="someone-gh", token="GH-TOKEN"):
    """GitHub's side of the OAuth exchange, mocked."""
    return (
        patch(f"{VIEWS}.exchange_code_for_token", return_value={"access_token": token, "scope": "repo"}),
        patch(f"{VIEWS}.fetch_github_user", return_value={"id": gh_id, "login": login}),
    )


@override_settings(GITHUB_CLIENT_ID="cid", GITHUB_CLIENT_SECRET="csecret", FRONTEND_URL="http://front.example")
class OAuthFlowTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", email="alice@example.com", password="pw")
        self.mallory = User.objects.create_user(username="mallory", email="mallory@example.com", password="pw")

    def start(self, user, nonce=NONCE):
        url = client_for(user).get(f"/api/v1/integrations/github/connect/?nonce={nonce}").data["authorize_url"]
        return parse_qs(urlparse(url).query)["state"][0]

    def callback(self, state, **github):
        exchange, fetch = github_answers(**github)
        with exchange, fetch:
            response = APIClient().get(f"/api/v1/integrations/github/callback/?code=c0de&state={state}")
        self.assertEqual(response.status_code, 302)
        return parse_qs(urlparse(response["Location"]).query)

    def complete(self, user, pending, nonce=NONCE):
        with patch(f"{VIEWS}.revoke_quietly") as revoke:
            response = client_for(user).post(
                "/api/v1/integrations/github/complete/", {"pending": pending, "nonce": nonce}, format="json"
            )
        return response, revoke

    def test_the_normal_flow_links_the_account_of_the_user_who_started_it(self):
        params = self.callback(self.start(self.alice), gh_id=1, login="alice-gh")
        self.assertFalse(GitHubAccount.objects.exists())  # nothing is linked by the callback itself
        response, _ = self.complete(self.alice, params["github_pending"][0])
        self.assertEqual(response.status_code, 200, response.data)
        account = GitHubAccount.objects.get(user=self.alice)
        self.assertEqual((account.github_username, account.access_token), ("alice-gh", "GH-TOKEN"))
        self.assertFalse(GitHubPendingConnection.objects.exists())

    def test_a_forwarded_authorization_link_never_links_the_victims_github_account(self):
        # Mallory starts the flow and gets Alice to open the authorization link; GitHub sends Alice's
        # browser back with a code for *Alice's* GitHub account.
        params = self.callback(self.start(self.mallory), gh_id=4242, login="alice-gh", token="ALICE-TOKEN")
        pending = params["github_pending"][0]
        self.assertFalse(GitHubAccount.objects.exists())
        # Alice's browser, signed in as Alice, tries to finish it: refused, discarded, token revoked.
        response, revoke = self.complete(self.alice, pending)
        self.assertEqual(response.status_code, 400)
        revoke.assert_called_once_with("ALICE-TOKEN")
        self.assertFalse(GitHubPendingConnection.objects.exists())
        # And Mallory can no longer claim it either.
        self.assertEqual(self.complete(self.mallory, pending)[0].status_code, 400)
        self.assertFalse(GitHubAccount.objects.exists())

    def test_the_nonce_from_the_starting_browser_is_required(self):
        pending = self.callback(self.start(self.alice))["github_pending"][0]
        response, revoke = self.complete(self.alice, pending, nonce="x" * 40)
        self.assertEqual(response.status_code, 400)
        revoke.assert_called_once()
        self.assertFalse(GitHubAccount.objects.exists())

    def test_a_parked_authorization_expires(self):
        pending = self.callback(self.start(self.alice))["github_pending"][0]
        GitHubPendingConnection.objects.update(created_at=timezone.now() - datetime.timedelta(minutes=11))
        self.assertEqual(self.complete(self.alice, pending)[0].status_code, 400)
        self.assertFalse(GitHubPendingConnection.objects.exists())

    def test_starting_needs_a_real_nonce(self):
        for nonce in ("", "short"):
            self.assertEqual(client_for(self.alice).get(f"/api/v1/integrations/github/connect/?nonce={nonce}").status_code, 400)

    def test_malformed_claims_are_refused_without_errors(self):
        for pending in ("not-a-uuid", "", None, 5, "00000000-0000-0000-0000-000000000000"):
            self.assertEqual(self.complete(self.alice, pending)[0].status_code, 400, pending)

    def test_only_githubs_own_error_code_reaches_the_ui(self):
        for error, shown in (("access_denied", "access_denied"), ("Your account is suspended, call 555", "authorization_failed")):
            response = APIClient().get("/api/v1/integrations/github/callback/", {"error": error})
            self.assertEqual(parse_qs(urlparse(response["Location"]).query)["github_error"], [shown])

    def test_github_being_unreachable_is_reported_not_a_crash(self):
        state = self.start(self.alice)
        with patch("apps.integrations.services.requests.post", side_effect=requests.ConnectionError("down")):
            response = APIClient(raise_request_exception=False).get(f"/api/v1/integrations/github/callback/?code=c&state={state}")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(parse_qs(urlparse(response["Location"]).query)["github_error"], ["connection_failed"])

    def test_reconnecting_as_another_github_user_revokes_the_old_token(self):
        GitHubAccount.objects.create(user=self.alice, github_user_id=1, github_username="old", access_token="OLD-TOKEN")
        pending = self.callback(self.start(self.alice), gh_id=2, login="new")["github_pending"][0]
        response, revoke = self.complete(self.alice, pending)
        self.assertEqual(response.status_code, 200)
        revoke.assert_called_once_with("OLD-TOKEN")


@override_settings(GITHUB_CLIENT_ID="cid", GITHUB_CLIENT_SECRET="csecret")
class ForgettingTokensTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="leaver", email="leaver@example.com", password="Zx9-unique-pass-77")
        GitHubAccount.objects.create(user=self.user, github_user_id=5, github_username="l-gh", access_token="LEAVER-TOKEN")

    def test_disconnecting_asks_github_to_revoke_the_token(self):
        with patch("apps.integrations.services.requests.delete", return_value=type("R", (), {"status_code": 204})()) as delete:
            client_for(self.user).delete("/api/v1/integrations/github/disconnect/")
        self.assertFalse(GitHubAccount.objects.exists())
        self.assertEqual(delete.call_args.kwargs["json"], {"access_token": "LEAVER-TOKEN"})
        self.assertEqual(delete.call_args.kwargs["auth"], ("cid", "csecret"))

    def test_deleting_the_account_forgets_and_revokes_the_github_token(self):
        with patch(f"{VIEWS}.revoke_quietly") as revoke:
            client_for(self.user).post("/api/v1/auth/me/delete/", {"password": "Zx9-unique-pass-77"}, format="json")
        self.assertFalse(GitHubAccount.objects.filter(user=self.user).exists())
        revoke.assert_called_once_with("LEAVER-TOKEN")

    def test_a_revocation_github_refuses_still_forgets_our_copy(self):
        with patch("apps.integrations.services.requests.delete", side_effect=requests.Timeout("slow")):
            client_for(self.user).delete("/api/v1/integrations/github/disconnect/")
        self.assertFalse(GitHubAccount.objects.exists())


class WorkspaceBoundaryTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="own", email="own@example.com", password="pw")
        self.connector = User.objects.create_user(username="conn", email="conn@example.com", password="pw")
        self.outsider = User.objects.create_user(username="outsider", email="out@example.com", password="pw")
        self.workspace = Workspace.objects.create(name="W", owner=self.owner)
        Membership.objects.create(workspace=self.workspace, user=self.owner, role="owner")
        self.connector_membership = Membership.objects.create(workspace=self.workspace, user=self.connector, role="admin")
        GitHubAccount.objects.create(user=self.connector, github_user_id=1, github_username="conn-gh", access_token="CONNECTOR-TOKEN")
        GitHubAccount.objects.create(user=self.owner, github_user_id=2, github_username="own-gh", access_token="OWNER-TOKEN")
        GitHubAccount.objects.create(user=self.outsider, github_user_id=3, github_username="out-gh", access_token="OUT-TOKEN")
        self.project = Project.objects.create(workspace=self.workspace, name="P", owner=self.owner)
        self.link = GitHubRepositoryLink.objects.create(project=self.project, github_repo_id=9, full_name="x/y", connected_by=self.connector)
        self.issue = Issue.objects.create(project=self.project, title="t", reporter=self.owner)

    def sync_token(self):
        with patch(f"{VIEWS}.list_repo_pulls", return_value=[]) as pulls, \
             patch(f"{VIEWS}.list_repo_commits", return_value=[]), \
             patch(f"{VIEWS}.list_recent_issues", return_value=[]):
            client_for(self.owner).post(f"/api/v1/integrations/projects/{self.project.id}/github-sync/")
        return pulls.call_args.args[0]

    def test_the_connectors_token_is_used_only_while_they_belong_to_the_workspace(self):
        self.assertEqual(self.sync_token(), "CONNECTOR-TOKEN")
        self.connector_membership.delete()
        self.assertEqual(self.sync_token(), "OWNER-TOKEN")  # the requester's own, never the departed member's

    @override_settings(GITHUB_WEBHOOK_SECRET="whsec")
    def push(self, sender):
        body = json.dumps({
            "repository": {"id": 9}, "ref": "refs/heads/main", "sender": sender,
            "commits": [{"id": "s1", "message": f"work #{self.issue.number}", "url": "https://github.com/x/y/commit/s1", "author": {"username": sender.get("login", ""), "name": "D"}}],
        }).encode()
        signature = "sha256=" + hmac.new(b"whsec", body, hashlib.sha256).hexdigest()
        APIClient().post("/api/v1/integrations/github/webhook/", data=body, content_type="application/json",
                         HTTP_X_HUB_SIGNATURE_256=signature, HTTP_X_GITHUB_EVENT="push")
        return Activity.objects.filter(workspace=self.workspace, verb="moved_issue").latest("id").actor

    def test_someone_outside_the_workspace_is_never_credited(self):
        self.assertEqual(self.push({"login": "out-gh", "id": 3}), self.connector)

    def test_a_member_is_credited_by_github_id_not_by_login(self):
        self.assertEqual(self.push({"login": "own-gh", "id": 2}), self.owner)

    def test_a_reused_login_with_another_id_is_not_trusted(self):
        # GitHub logins can be renamed and registered again by someone else; only the numeric id counts.
        self.assertEqual(self.push({"login": "own-gh", "id": 999999}), self.connector)


class NetworkFailureTests(TestCase):
    def test_every_github_call_turns_network_trouble_into_a_github_error(self):
        with patch("apps.integrations.services.requests.get", side_effect=requests.ConnectionError("down")):
            with self.assertRaises(services.GitHubAPIError):
                services.get_repo("t", "a/b")
        with patch("apps.integrations.services.requests.get", return_value=type("R", (), {"status_code": 200, "json": lambda self: (_ for _ in ()).throw(ValueError("html"))})()):
            with self.assertRaises(services.GitHubAPIError):
                services.fetch_github_user("t")
