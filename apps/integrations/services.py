from urllib.parse import urlencode, urlparse

import requests
from django.conf import settings

GITHUB_API_BASE = "https://api.github.com"
GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
REQUEST_TIMEOUT = 10


class GitHubAPIError(Exception):
    """Raised whenever a call to the GitHub API fails or returns an error payload."""


def _headers(access_token=None):
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    return headers


def build_authorize_url(state):
    params = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "redirect_uri": settings.GITHUB_CALLBACK_URL,
        "scope": settings.GITHUB_OAUTH_SCOPE,
        "state": state,
    }
    return f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code_for_token(code):
    response = requests.post(
        GITHUB_TOKEN_URL,
        data={
            "client_id": settings.GITHUB_CLIENT_ID,
            "client_secret": settings.GITHUB_CLIENT_SECRET,
            "code": code,
            "redirect_uri": settings.GITHUB_CALLBACK_URL,
        },
        headers={"Accept": "application/json"},
        timeout=REQUEST_TIMEOUT,
    )
    data = response.json()
    if response.status_code != 200 or "access_token" not in data:
        raise GitHubAPIError(data.get("error_description", "Failed to exchange code for token."))
    return data


def fetch_github_user(access_token):
    response = requests.get(f"{GITHUB_API_BASE}/user", headers=_headers(access_token), timeout=REQUEST_TIMEOUT)
    if response.status_code != 200:
        raise GitHubAPIError("Failed to fetch the GitHub user profile.")
    return response.json()


MAX_REPO_PAGES = 10  # safety cap: 10 * 100 = up to 1000 repos considered


def list_user_repos(access_token):
    repos = []
    for page in range(1, MAX_REPO_PAGES + 1):
        response = requests.get(
            f"{GITHUB_API_BASE}/user/repos",
            headers=_headers(access_token),
            params={"per_page": 100, "sort": "updated", "page": page},
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code != 200:
            raise GitHubAPIError("Failed to list GitHub repositories.")
        batch = response.json()
        repos.extend(batch)
        if len(batch) < 100:
            break
    # Every repository the user can see. `admin` tells the UI whether a webhook can be installed
    # (needs admin rights); importing and syncing only need read access.
    return [
        {
            "id": repo["id"],
            "full_name": repo["full_name"],
            "private": repo["private"],
            "html_url": repo["html_url"],
            "admin": bool((repo.get("permissions") or {}).get("admin")),
        }
        for repo in repos
    ]


def create_webhook(access_token, full_name, callback_url, secret):
    response = requests.post(
        f"{GITHUB_API_BASE}/repos/{full_name}/hooks",
        headers=_headers(access_token),
        json={
            "name": "web",
            "active": True,
            "events": ["push", "pull_request"],
            "config": {"url": callback_url, "content_type": "json", "secret": secret},
        },
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code != 201:
        raise GitHubAPIError(f"GitHub refused to create the webhook: {_github_message(response)}")
    return response.json()


def delete_webhook(access_token, full_name, webhook_id):
    if not webhook_id:
        return
    response = requests.delete(
        f"{GITHUB_API_BASE}/repos/{full_name}/hooks/{webhook_id}",
        headers=_headers(access_token),
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code not in (204, 404):
        raise GitHubAPIError("Failed to delete the webhook on that repository.")


def _github_message(response):
    """GitHub's own explanation of an error, e.g. "Not Found" or a validation error list."""
    try:
        data = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    message = data.get("message", f"HTTP {response.status_code}")
    details = [str(e.get("message") or e) for e in data.get("errors", []) if isinstance(e, (dict, str))]
    return f"{message} ({'; '.join(details)})" if details else message


def is_public_url(url):
    """GitHub cannot deliver webhooks to localhost / private hosts."""
    host = (urlparse(url).hostname or "").lower()
    return bool(host) and host not in ("localhost", "127.0.0.1", "0.0.0.0", "::1") and not host.endswith(".local")


def get_repo(access_token, full_name):
    response = requests.get(f"{GITHUB_API_BASE}/repos/{full_name}", headers=_headers(access_token), timeout=REQUEST_TIMEOUT)
    if response.status_code != 200:
        raise GitHubAPIError(f"Could not read that repository: {_github_message(response)}")
    return response.json()


MAX_IMPORT_ISSUES = 300  # import cap: 3 pages of 100


def list_repo_issues(access_token, full_name):
    """Issues of a repository, oldest first, without pull requests (GitHub lists PRs as issues too)."""
    issues = []
    for page in range(1, MAX_IMPORT_ISSUES // 100 + 1):
        response = requests.get(
            f"{GITHUB_API_BASE}/repos/{full_name}/issues",
            headers=_headers(access_token),
            params={"state": "all", "per_page": 100, "page": page, "sort": "created", "direction": "asc"},
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code != 200:
            raise GitHubAPIError(f"Could not read the repository's issues: {_github_message(response)}")
        batch = response.json()
        issues.extend(item for item in batch if "pull_request" not in item)
        if len(batch) < 100:
            break
    return issues


def list_repo_pulls(access_token, full_name, limit=30):
    response = requests.get(
        f"{GITHUB_API_BASE}/repos/{full_name}/pulls",
        headers=_headers(access_token),
        params={"state": "all", "per_page": limit, "sort": "updated", "direction": "desc"},
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code != 200:
        raise GitHubAPIError(f"Could not read the repository's pull requests: {_github_message(response)}")
    return response.json()


def list_repo_commits(access_token, full_name, limit=30):
    response = requests.get(
        f"{GITHUB_API_BASE}/repos/{full_name}/commits",
        headers=_headers(access_token),
        params={"per_page": limit},
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code != 200:
        raise GitHubAPIError(f"Could not read the repository's commits: {_github_message(response)}")
    return response.json()
