# *******************************************************************************
# Copyright (c) 2026 Contributors to the Eclipse Foundation
#
# See the NOTICE file(s) distributed with this work for additional
# information regarding copyright ownership.
#
# This program and the accompanying materials are made available under the
# terms of the Apache License Version 2.0 which is available at
# https://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0
# *******************************************************************************

"""Secure GitHub API client for repository and file discovery."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from typing import Any


class GitHubClient:
    """Client for interacting with GitHub REST API securely without token exposure."""

    def __init__(
        self, token: str | None = None, api_base_url: str = "https://api.github.com"
    ):
        self.api_base_url = api_base_url.rstrip("/")
        self._token = token or self._discover_token()

    def __repr__(self) -> str:
        return f"GitHubClient(authenticated={bool(self._token)})"

    def __str__(self) -> str:
        return f"GitHubClient(authenticated={bool(self._token)})"

    @staticmethod
    def _discover_token() -> str | None:
        """Finds token in environment variables or via gh CLI fallback."""
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            return token.strip()

        # Try gh CLI if available
        if shutil.which("gh"):
            try:
                res = subprocess.run(
                    ["gh", "auth", "token"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if res.returncode == 0 and res.stdout.strip():
                    return res.stdout.strip()
            except Exception:
                pass

        return None

    def _request(self, endpoint: str) -> Any:
        """Executes a GET request against GitHub API."""
        url = f"{self.api_base_url}/{endpoint.lstrip('/')}"
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "score-rust-dependency-audit",
        }
        if self._token:
            headers["Authorization"] = f"token {self._token}"

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # Handle rate limiting or not found without leaking tokens
            if e.code == 404:
                return None
            if e.code in (401, 403):
                raise RuntimeError(
                    f"GitHub API access denied (HTTP {e.code}). "
                    "Ensure GITHUB_TOKEN is set with adequate permissions."
                ) from None
            raise RuntimeError(
                f"GitHub API request failed with HTTP {e.code}"
            ) from None
        except Exception as e:
            raise RuntimeError(f"Network error querying GitHub API: {e}") from None

    def get_organization_repositories(
        self, org: str, include_archived: bool = False
    ) -> list[dict[str, Any]]:
        """Retrieves list of repositories for an organization."""
        repos: list[dict[str, Any]] = []
        page = 1
        per_page = 100

        while True:
            endpoint = f"orgs/{org}/repos?type=all&per_page={per_page}&page={page}"
            batch = self._request(endpoint)
            if not batch or not isinstance(batch, list):
                break

            for r in batch:
                if not include_archived and r.get("archived", False):
                    continue
                repos.append(r)

            if len(batch) < per_page:
                break
            page += 1

        return repos

    def get_repo_git_tree(
        self, owner: str, repo: str, branch: str = "main"
    ) -> list[str]:
        """Fetches recursive tree paths for a repository."""
        endpoint = f"repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
        data = self._request(endpoint)
        if not data or "tree" not in data:
            return []

        paths: list[str] = []
        for item in data.get("tree", []):
            if item.get("type") == "blob":
                paths.append(item.get("path", ""))

        return paths

    def get_file_content(
        self, owner: str, repo: str, path: str, branch: str = "main"
    ) -> str | None:
        """Retrieves raw content of a file from a repository."""
        # Raw URL is fast and directly returns text
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
        headers = {
            "User-Agent": "score-rust-dependency-audit",
        }
        if self._token:
            headers["Authorization"] = f"token {self._token}"

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            return None
        except Exception:
            return None
