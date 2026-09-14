from urllib.parse import urlencode

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
        "scope": "repo",
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
    return [
        {"id": repo["id"], "full_name": repo["full_name"], "private": repo["private"], "html_url": repo["html_url"]}
        for repo in repos
        if repo.get("permissions", {}).get("admin")
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
        raise GitHubAPIError("Failed to create a webhook on that repository. Do you have admin access to it?")
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
