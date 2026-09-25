import hashlib
import hmac
import logging
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.activities.models import Activity
from apps.issues.models import Issue
from apps.projects.models import Label, Project, ProjectMember
from apps.workspaces.models import Workspace
from apps.workspaces.permissions import get_membership

from . import services
from .models import GitHubAccount, GitHubCommit, GitHubPullRequest, GitHubRepositoryLink
from .parsing import extract_issue_ids
from .workflow import advance_issue, branch_from_ref, parse_github_datetime
from .serializers import (
    GitHubCommitSerializer,
    GitHubImportSerializer,
    GitHubPullRequestSerializer,
    GitHubRepositoryLinkCreateSerializer,
    GitHubRepositoryLinkSerializer,
)

User = get_user_model()
logger = logging.getLogger(__name__)


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

        link, warning = _link_repository(project, request.user, account, github_repo_id, full_name)
        return Response(_link_response(link, warning), status=status.HTTP_201_CREATED)

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


def _link_repository(project, user, account, github_repo_id, full_name):
    """Link a repository to a project and try to install its webhook.

    The webhook is best-effort: GitHub refuses hooks that point at localhost or a private host, and
    plenty of users lack admin rights on the repo. The link is created either way (a manual sync
    still works); the returned warning says why live updates are off.
    """
    webhook_id, warning = None, None
    callback_url = settings.GITHUB_WEBHOOK_CALLBACK_URL
    if not services.is_public_url(callback_url):
        warning = {"code": "not_public_url", "detail": callback_url}
    else:
        try:
            hook = services.create_webhook(account.access_token, full_name, callback_url, settings.GITHUB_WEBHOOK_SECRET)
            webhook_id = hook.get("id")
        except services.GitHubAPIError as exc:
            warning = {"code": "github_rejected", "detail": str(exc)}

    link = GitHubRepositoryLink.objects.create(
        project=project,
        github_repo_id=github_repo_id,
        full_name=full_name,
        webhook_id=webhook_id,
        connected_by=user,
    )
    project.repository_url = f"https://github.com/{full_name}"
    project.save(update_fields=["repository_url"])
    return link, warning


def _link_response(link, warning):
    return {**GitHubRepositoryLinkSerializer(link).data, "webhook_warning": warning}


def _match_issues(project, ids):
    """Issues of `project` that `#<id>` references point at.

    In a project with imported GitHub issues, `#12` means GitHub's issue 12 (that is what people type
    in commits); otherwise it is the DevTrack issue id. GitHub numbering wins when both exist.
    """
    if not ids:
        return []
    by_number = list(Issue.objects.filter(project=project, github_number__in=ids))
    remaining = set(ids) - {issue.github_number for issue in by_number}
    by_id = list(Issue.objects.filter(project=project, id__in=remaining)) if remaining else []
    return by_number + by_id


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


def _resolve_actor(login, repo_link):
    """The DevTrack user behind a GitHub login, else whoever connected the repository."""
    if login:
        account = GitHubAccount.objects.filter(github_username__iexact=login).select_related("user").first()
        if account:
            return account.user
    return repo_link.connected_by


def _handle_push(repo_link, payload):
    branch = branch_from_ref(payload.get("ref", ""))
    for commit in payload.get("commits", []):
        ids = extract_issue_ids(commit.get("message", ""))
        matched = _match_issues(repo_link.project, ids)
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
                "branch": branch,
                "committed_at": parse_github_datetime(commit.get("timestamp")),
            },
        )
        commit_obj.issues.set(matched)
        # Work has started the moment a commit mentions the issue.
        actor = _resolve_actor(author.get("username"), repo_link)
        for issue in matched:
            advance_issue(issue, Issue.Status.IN_PROGRESS, actor)


def _handle_pull_request(repo_link, payload):
    pr_data = payload.get("pull_request", {})
    ids = extract_issue_ids(pr_data.get("title", ""), pr_data.get("body") or "")
    matched = _match_issues(repo_link.project, ids)

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
            "draft": bool(pr_data.get("draft", False)),
            "opened_at": parse_github_datetime(pr_data.get("created_at")),
            "merged_at": parse_github_datetime(pr_data.get("merged_at")),
            "closed_at": parse_github_datetime(pr_data.get("closed_at")),
        },
    )
    pr.issues.set(matched)
    actor = _resolve_actor((pr_data.get("user") or {}).get("login"), repo_link)

    # GitHub only ever sets merged: true together with action: "closed" — there
    # is no separate "merged" action, so this is the correct/only merge trigger.
    is_merge = payload.get("action") == "closed" and pr_data.get("merged")
    base_ref = (pr_data.get("base") or {}).get("ref", "")
    merged_into_default = not repo_link.default_branch or base_ref == repo_link.default_branch

    if is_merge and not merged_into_default:
        # Landed on a feature/release branch, not on the main line: the work is reviewed, not shipped.
        for issue in matched:
            advance_issue(issue, Issue.Status.IN_REVIEW, actor)
    elif not is_merge and pr_data.get("state", GitHubPullRequest.State.OPEN) == GitHubPullRequest.State.OPEN:
        # An open pull request means work is under way (a draft) or waiting for review (ready).
        target = Issue.Status.IN_PROGRESS if pr_data.get("draft") else Issue.Status.IN_REVIEW
        for issue in matched:
            advance_issue(issue, target, actor)

    if is_merge and merged_into_default:
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


def _apply_github_issue_state(repo_link, item, actor):
    """Mirror a GitHub issue being closed/reopened onto the imported DevTrack issue with that number."""
    if not item or "pull_request" in item:
        return
    issue = Issue.objects.filter(project=repo_link.project, github_number=item.get("number")).first()
    if issue is None:
        return
    if item.get("state") == "closed":
        advance_issue(issue, Issue.Status.DONE, actor)
    elif item.get("state") == "open" and issue.status == Issue.Status.DONE:
        issue._actor = actor
        issue.status = Issue.Status.TODO
        issue.save(update_fields=["status", "updated_at"])


def _handle_issues_event(repo_link, payload):
    if payload.get("action") not in ("closed", "reopened"):
        return
    item = payload.get("issue") or {}
    actor = _resolve_actor((payload.get("sender") or {}).get("login"), repo_link)
    _apply_github_issue_state(repo_link, item, actor)


def _touch_link(repo_link, payload):
    """Record that GitHub is talking to us, and keep the default branch current."""
    fields = ["last_event_at", "updated_at"]
    repo_link.last_event_at = timezone.now()
    default_branch = (payload.get("repository") or {}).get("default_branch")
    if default_branch and default_branch != repo_link.default_branch:
        repo_link.default_branch = default_branch
        fields.append("default_branch")
    repo_link.save(update_fields=fields)


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

        _touch_link(repo_link, payload)
        if event == "ping":
            return Response({"detail": "pong"}, status=status.HTTP_200_OK)
        if event == "push":
            _safely(_handle_push, repo_link, payload)
        elif event == "pull_request":
            _safely(_handle_pull_request, repo_link, payload)
        elif event == "issues":
            _safely(_handle_issues_event, repo_link, payload)
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
        # Log it though: a silent skip is how a broken integration goes unnoticed.
        logger.warning("Skipped a malformed GitHub payload for %s", repo_link.full_name, exc_info=True)


def _repo_token(link, requester):
    """The token used to read a linked repo: its connector's, else the requester's."""
    for user in (link.connected_by, requester):
        account = getattr(user, "github_account", None)
        if account is not None:
            return account.access_token
    return None


def _pull_request_payload(pr):
    # REST list items carry merged_at instead of the webhook's `merged` boolean.
    merged = bool(pr.get("merged_at"))
    return {
        "action": "closed" if pr.get("state") == "closed" else "synchronize",
        "pull_request": {**pr, "merged": merged},
    }


def _commit_payload(item):
    commit = item.get("commit") or {}
    author = commit.get("author") or {}
    return {
        "id": item["sha"],
        "message": commit.get("message", ""),
        "author": {"username": (item.get("author") or {}).get("login", ""), "name": author.get("name", "")},
        "url": item.get("html_url", ""),
        "timestamp": author.get("date", ""),
    }


class ProjectGitHubSyncView(APIView):
    """Pull recent pull requests and commits from GitHub and process them exactly like webhook deliveries.

    This is how a linked project stays current when webhooks cannot reach the server (local
    development, or a repo the user has no admin rights on).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, project_id):
        project = get_object_or_404(Project, pk=project_id)
        _require_workspace_member(request.user, project.workspace)
        link = getattr(project, "github_link", None)
        if link is None:
            raise NotFound("This project has no linked GitHub repository.")
        token = _repo_token(link, request.user)
        if token is None:
            raise ValidationError({"detail": "Connect your GitHub account first."})

        try:
            pulls = services.list_repo_pulls(token, link.full_name)
            commits = services.list_repo_commits(token, link.full_name)
            github_issues = services.list_recent_issues(token, link.full_name)
        except services.GitHubAPIError as exc:
            raise ValidationError({"detail": str(exc)})

        # Oldest first so a merge is applied after the PR was first seen.
        for pr in reversed(pulls):
            _safely(_handle_pull_request, link, _pull_request_payload(pr))
        push = {"ref": f"refs/heads/{link.default_branch}"} if link.default_branch else {}
        for item in reversed(commits):
            _safely(_handle_push, link, {**push, "commits": [_commit_payload(item)]})
        for item in github_issues:
            _apply_github_issue_state(link, item, link.connected_by)
        link.last_synced_at = timezone.now()
        link.save(update_fields=["last_synced_at", "updated_at"])
        return Response({"pull_requests": len(pulls), "commits": len(commits), "issues": len(github_issues)})


ISSUE_TYPE_BY_LABEL = {
    "bug": Issue.Type.BUG,
    "enhancement": Issue.Type.FEATURE,
    "feature": Issue.Type.FEATURE,
    "improvement": Issue.Type.IMPROVEMENT,
    "chore": Issue.Type.CHORE,
}


def _import_issues(project, user, workspace, github_issues):
    labels_cache, assignee_cache = {}, {}

    def label_for(data):
        name = (data.get("name") or "")[:50]
        if name and name not in labels_cache:
            color = "#" + (data.get("color") or "6b7280")
            labels_cache[name], _ = Label.objects.get_or_create(
                workspace=workspace, project=None, name=name, defaults={"color": color[:7]}
            )
        return labels_cache.get(name)

    def assignee_for(login):
        if not login:
            return None
        if login not in assignee_cache:
            account = GitHubAccount.objects.filter(github_username__iexact=login).select_related("user").first()
            assignee_cache[login] = account.user if account and get_membership(account.user, workspace) else None
        return assignee_cache[login]

    imported = 0
    for item in github_issues:
        label_data = item.get("labels") or []
        issue_type = next(
            (ISSUE_TYPE_BY_LABEL[l["name"].lower()] for l in label_data if l.get("name", "").lower() in ISSUE_TYPE_BY_LABEL),
            Issue.Type.TASK,
        )
        body = item.get("body") or ""
        issue = Issue.objects.create(
            project=project,
            title=(item.get("title") or f"GitHub issue #{item['number']}")[:200],
            description=body,
            type=issue_type,
            status=Issue.Status.DONE if item.get("state") == "closed" else Issue.Status.TODO,
            reporter=user,
            assignee=assignee_for((item.get("assignee") or {}).get("login")),
            github_number=item["number"],
            github_url=item.get("html_url", ""),
        )
        issue.labels.set([label for label in (label_for(l) for l in label_data) if label is not None])
        imported += 1
    return imported


class GitHubImportView(APIView):
    """Turn a GitHub repository into a DevTrack project: create it, link the repo and (optionally)
    import the repository's issues."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = GitHubImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        workspace = get_object_or_404(Workspace, pk=data["workspace"])
        _require_workspace_admin(request.user, workspace)
        account = getattr(request.user, "github_account", None)
        if account is None:
            raise ValidationError({"detail": "Connect your GitHub account first."})
        if GitHubRepositoryLink.objects.filter(github_repo_id=data["github_repo_id"]).exists():
            raise ValidationError({"detail": "This repository is already linked to another project."})

        # Everything that talks to GitHub and can fail is read first, so a failure leaves nothing behind.
        try:
            repo = services.get_repo(account.access_token, data["full_name"])
            github_issues = (
                services.list_repo_issues(account.access_token, data["full_name"]) if data["import_issues"] else []
            )
        except services.GitHubAPIError as exc:
            raise ValidationError({"detail": str(exc)})

        with transaction.atomic():
            project = Project.objects.create(
                workspace=workspace,
                name=(repo.get("name") or data["full_name"].split("/")[-1])[:150],
                description=repo.get("description") or "",
                status=Project.Status.ACTIVE,
                owner=request.user,
                repository_url=repo.get("html_url", ""),
            )
            ProjectMember.objects.create(project=project, user=request.user, role="owner")
            imported = _import_issues(project, request.user, workspace, github_issues)

        link, warning = _link_repository(project, request.user, account, data["github_repo_id"], data["full_name"])
        return Response(
            {
                "project": {"id": project.id, "name": project.name},
                "issues_imported": imported,
                "link": _link_response(link, warning),
            },
            status=status.HTTP_201_CREATED,
        )
