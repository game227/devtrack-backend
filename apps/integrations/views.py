import hashlib
import hmac
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.activities.models import Activity
from apps.issues.models import Issue
from apps.projects.models import Project
from apps.workspaces.permissions import get_membership

from . import services
from .models import GitHubAccount, GitHubCommit, GitHubPullRequest, GitHubRepositoryLink
from .parsing import extract_issue_ids
from .serializers import (
    GitHubCommitSerializer,
    GitHubPullRequestSerializer,
    GitHubRepositoryLinkCreateSerializer,
    GitHubRepositoryLinkSerializer,
)

User = get_user_model()


def _require_workspace_member(user, workspace):
    if get_membership(user, workspace) is None:
        raise PermissionDenied("You are not a member of this workspace.")


def _require_workspace_admin(user, workspace):
    membership = get_membership(user, workspace)
    if membership is None or membership.role not in ("owner", "admin"):
        raise PermissionDenied("Only a workspace admin/owner can do that.")


def _redirect_to_settings(**params):
    # Values here can originate from GitHub's redirect (e.g. `error`) — always
    # go through urlencode rather than f-string interpolation, so a stray
    # '&' or '#' can't inject extra query params or corrupt the redirect URL.
    return redirect(f"{settings.FRONTEND_URL}/settings?{urlencode(params)}")


class GitHubConnectView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        state = signing.dumps({"user_id": request.user.id}, salt="github-oauth")
        return Response({"authorize_url": services.build_authorize_url(state)})


class GitHubCallbackView(APIView):
    # Hit by a bare browser redirect from GitHub — no Authorization header is
    # possible here, so this overrides the global JWT/IsAuthenticated defaults.
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        error = request.query_params.get("error")
        if error:
            return _redirect_to_settings(github_error=error)

        code = request.query_params.get("code")
        state = request.query_params.get("state")
        if not code or not state:
            return _redirect_to_settings(github_error="missing_params")

        try:
            state_data = signing.loads(state, salt="github-oauth", max_age=300)
            user = User.objects.get(pk=state_data["user_id"])
        except (signing.BadSignature, User.DoesNotExist):
            return _redirect_to_settings(github_error="invalid_state")

        try:
            token_data = services.exchange_code_for_token(code)
            gh_user = services.fetch_github_user(token_data["access_token"])
        except services.GitHubAPIError:
            return _redirect_to_settings(github_error="connection_failed")

        already_linked = (
            GitHubAccount.objects.filter(github_user_id=gh_user["id"]).exclude(user=user).exists()
        )
        if already_linked:
            return _redirect_to_settings(github_error="account_already_linked")

        GitHubAccount.objects.update_or_create(
            user=user,
            defaults={
                "github_user_id": gh_user["id"],
                "github_username": gh_user["login"],
                "access_token": token_data["access_token"],
                "scope": token_data.get("scope", ""),
            },
        )
        return _redirect_to_settings(github="connected")


class GitHubStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        account = getattr(request.user, "github_account", None)
        if account is None:
            return Response({"connected": False})
        return Response(
            {
                "connected": True,
                "github_username": account.github_username,
                "connected_at": account.connected_at,
            }
        )


class GitHubDisconnectView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        # Deliberately does not touch any GitHubRepositoryLink — webhook
        # processing never uses a user's OAuth token, only GITHUB_WEBHOOK_SECRET,
        # so disconnecting doesn't break already-configured repo links.
        GitHubAccount.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class GitHubRepoListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        account = getattr(request.user, "github_account", None)
        if account is None:
            raise ValidationError({"detail": "Connect your GitHub account first."})
        try:
            repos = services.list_user_repos(account.access_token)
        except services.GitHubAPIError as exc:
            raise ValidationError({"detail": str(exc)})
        return Response({"repos": repos})


class ProjectGitHubLinkView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, project_id):
        project = get_object_or_404(Project, pk=project_id)
        _require_workspace_member(request.user, project.workspace)
        link = getattr(project, "github_link", None)
        if link is None:
            return Response({"linked": False})
        return Response({"linked": True, **GitHubRepositoryLinkSerializer(link).data})

    def post(self, request, project_id):
        project = get_object_or_404(Project, pk=project_id)
        _require_workspace_admin(request.user, project.workspace)

        if getattr(project, "github_link", None) is not None:
            raise ValidationError({"detail": "This project is already linked to a GitHub repository."})

        account = getattr(request.user, "github_account", None)
        if account is None:
            raise ValidationError({"detail": "Connect your GitHub account first."})

        serializer = GitHubRepositoryLinkCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        github_repo_id = serializer.validated_data["github_repo_id"]
        full_name = serializer.validated_data["full_name"]

        if GitHubRepositoryLink.objects.filter(github_repo_id=github_repo_id).exists():
            raise ValidationError({"detail": "This repository is already linked to another project."})

        try:
            hook = services.create_webhook(
                account.access_token,
                full_name,
                settings.GITHUB_WEBHOOK_CALLBACK_URL,
                settings.GITHUB_WEBHOOK_SECRET,
            )
        except services.GitHubAPIError as exc:
            raise ValidationError({"detail": str(exc)})

        link = GitHubRepositoryLink.objects.create(
            project=project,
            github_repo_id=github_repo_id,
            full_name=full_name,
            webhook_id=hook.get("id"),
            connected_by=request.user,
        )
        project.repository_url = f"https://github.com/{full_name}"
        project.save(update_fields=["repository_url"])
        return Response(GitHubRepositoryLinkSerializer(link).data, status=status.HTTP_201_CREATED)

    def delete(self, request, project_id):
        project = get_object_or_404(Project, pk=project_id)
        _require_workspace_admin(request.user, project.workspace)
        link = getattr(project, "github_link", None)
        if link is None:
            raise NotFound("This project has no linked GitHub repository.")

        account = getattr(link.connected_by, "github_account", None)
        if account is not None:
            try:
                services.delete_webhook(account.access_token, link.full_name, link.webhook_id)
            except services.GitHubAPIError:
                pass  # best-effort — local unlink still proceeds even if GitHub cleanup fails
        link.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class IssueGitHubLinksView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, issue_id):
        issue = get_object_or_404(Issue, pk=issue_id)
        _require_workspace_member(request.user, issue.project.workspace)
        commits = GitHubCommit.objects.filter(issues=issue).order_by("-created_at")
        pull_requests = GitHubPullRequest.objects.filter(issues=issue).order_by("-updated_at")
        return Response(
            {
                "commits": GitHubCommitSerializer(commits, many=True).data,
                "pull_requests": GitHubPullRequestSerializer(pull_requests, many=True).data,
            }
        )


def _verify_signature(body, header):
    secret = settings.GITHUB_WEBHOOK_SECRET
    # Fail closed if the secret was never configured — an empty secret would
    # otherwise mean "any request with a signature computed from an empty
    # key" passes, which is a guessable/known key, not a real check.
    if not secret or not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


def _upsert(model, retry_once=True, **kwargs):
    # update_or_create's get-then-create isn't atomic: two near-simultaneous
    # webhook deliveries for the same (repo_link, sha/github_pr_id) can both
    # miss the row and both try to insert, tripping the unique_together
    # constraint. One retry (now finding the row the other request just
    # created) resolves it without needing a broader lock.
    try:
        with transaction.atomic():
            return model.objects.update_or_create(**kwargs)
    except IntegrityError:
        if not retry_once:
            raise
        return _upsert(model, retry_once=False, **kwargs)


def _resolve_actor(pr_data, repo_link):
    login = (pr_data.get("user") or {}).get("login")
    if login:
        account = GitHubAccount.objects.filter(github_username__iexact=login).select_related("user").first()
        if account:
            return account.user
    return repo_link.connected_by


def _handle_push(repo_link, payload):
    for commit in payload.get("commits", []):
        ids = extract_issue_ids(commit.get("message", ""))
        matched = Issue.objects.filter(id__in=ids, project=repo_link.project)
        author = commit.get("author") or {}
        commit_obj, _ = _upsert(
            GitHubCommit,
            repo_link=repo_link,
            sha=commit["id"],
            defaults={
                "message": commit.get("message", ""),
                "author_username": author.get("username", "") or "",
                "author_name": author.get("name", ""),
                "url": commit.get("url", ""),
            },
        )
        commit_obj.issues.set(matched)


def _handle_pull_request(repo_link, payload):
    pr_data = payload.get("pull_request", {})
    ids = extract_issue_ids(pr_data.get("title", ""), pr_data.get("body") or "")
    matched = list(Issue.objects.filter(id__in=ids, project=repo_link.project))

    pr, _ = _upsert(
        GitHubPullRequest,
        repo_link=repo_link,
        github_pr_id=pr_data["id"],
        defaults={
            "number": pr_data["number"],
            "title": pr_data.get("title", ""),
            "state": pr_data.get("state", GitHubPullRequest.State.OPEN),
            "merged": bool(pr_data.get("merged", False)),
            "author_username": (pr_data.get("user") or {}).get("login", ""),
            "url": pr_data.get("html_url", ""),
            "head_ref": (pr_data.get("head") or {}).get("ref", ""),
            "base_ref": (pr_data.get("base") or {}).get("ref", ""),
        },
    )
    pr.issues.set(matched)

    # GitHub only ever sets merged: true together with action: "closed" — there
    # is no separate "merged" action, so this is the correct/only merge trigger.
    if payload.get("action") == "closed" and pr_data.get("merged"):
        actor = _resolve_actor(pr_data, repo_link)
        for issue in matched:
            if issue.status == Issue.Status.DONE:
                continue
            previous_status = issue.status
            issue.status = Issue.Status.DONE
            # pr_merged (below) already records this transition — skip the generic moved_issue.
            issue._skip_move_activity = True
            issue.save(update_fields=["status", "updated_at"])
            Activity.objects.create(
                workspace=repo_link.project.workspace,
                actor=actor,
                verb="pr_merged",
                target=issue,
                metadata={
                    "from": previous_status,
                    "to": Issue.Status.DONE,
                    "pr_number": pr_data["number"],
                    "pr_url": pr_data.get("html_url", ""),
                },
            )


class GitHubWebhookView(APIView):
    # Server-to-server delivery from GitHub — authenticated via HMAC signature
    # (X-Hub-Signature-256), not a JWT, so this overrides the global defaults.
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        # Must read request.body (raw bytes, for signature verification)
        # before request.data — Django caches the raw body on first access,
        # so DRF's later parsing of request.data still works off that cache.
        raw_body = request.body
        signature = request.headers.get("X-Hub-Signature-256", "")
        if not _verify_signature(raw_body, signature):
            return Response({"detail": "Invalid signature."}, status=status.HTTP_403_FORBIDDEN)

        event = request.headers.get("X-GitHub-Event", "")
        payload = request.data
        repo_id = (payload.get("repository") or {}).get("id")
        repo_link = (
            GitHubRepositoryLink.objects.filter(github_repo_id=repo_id)
            .select_related("project__workspace", "connected_by")
            .first()
        )

        if repo_link is None:
            # Always 2xx once past the signature check — GitHub disables a
            # hook after repeated non-2xx responses, and "not linked" isn't
            # an error condition for GitHub's delivery system.
            return Response({"detail": "Repository not linked to any project."}, status=status.HTTP_200_OK)

        if event == "ping":
            return Response({"detail": "pong"}, status=status.HTTP_200_OK)
        if event == "push":
            _safely(_handle_push, repo_link, payload)
        elif event == "pull_request":
            _safely(_handle_pull_request, repo_link, payload)
        else:
            return Response({"detail": f"Unhandled event: {event}"}, status=status.HTTP_200_OK)
        return Response({"detail": "ok"}, status=status.HTTP_200_OK)


def _safely(handler, repo_link, payload):
    try:
        handler(repo_link, payload)
    except (KeyError, TypeError):
        # Unexpected/malformed payload shape for an event we do parse — skip
        # rather than 500. GitHub disables a hook after repeated non-2xx
        # responses, and a shape we don't recognize isn't the sender's fault.
        pass
