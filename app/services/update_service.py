"""
Lightweight update detection: compare local deployment revision with GitHub `main`.

- Uses the GitHub REST API for the latest commit SHA (no full clone).
- Fetches `update.md` from raw.githubusercontent.com for the same ref.
- Skips all network work when offline (silent).
- Caches results to avoid hammering GitHub on every HTTP request.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("webable.update")

# Production repository (HTTPS API; no deploy key required for public repo).
DEFAULT_OWNER = "zeromeia0"
DEFAULT_REPO = "webable"
GITHUB_API_COMMITS = "https://api.github.com/repos/{owner}/{repo}/commits/main"
RAW_UPDATE_MD = "https://raw.githubusercontent.com/{owner}/{repo}/{ref}/update.md"

# Connectivity probe (small, reliable).
CONNECTIVITY_CHECK_URL = os.environ.get("WEBABLE_CONNECTIVITY_URL", "https://api.github.com")

_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {
    "checked_at": 0.0,
    "payload": None,  # serialized UpdateStatus
    "ttl_seconds": float(os.environ.get("WEBABLE_UPDATE_CACHE_TTL", "300")),
}


@dataclass
class UpdateStatus:
    """Serializable result of an update check."""

    online: bool = False
    check_performed: bool = False
    local_sha: str | None = None
    remote_sha: str | None = None
    update_available: bool = False
    update_md_raw: str | None = None
    update_md_html: str | None = None
    auto_update_enabled: bool = False
    can_apply_git_update: bool = False
    repo_root: str | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        from . import deployment_mode

        return {
            "online": self.online,
            "check_performed": self.check_performed,
            "local_sha": self.local_sha,
            "remote_sha": self.remote_sha,
            "update_available": self.update_available,
            "update_md_html": self.update_md_html,
            "auto_update_enabled": self.auto_update_enabled,
            "can_apply_git_update": self.can_apply_git_update,
            "repo_root": self.repo_root,
            "error": self.error,
            "deployment_mode": deployment_mode.get_deployment_mode(),
        }


def _repo_root() -> Path:
    """Project root (directory containing `app/` and usually `webapp.py`)."""
    return Path(__file__).resolve().parent.parent.parent


def _read_text_file(path: Path) -> str | None:
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError as exc:
        log.warning("Could not read %s: %s", path, exc)
    return None


def get_local_revision() -> str | None:
    """
    Resolve the running app's source revision, in order:
    1) WEBABLE_LOCAL_GIT_COMMIT env
    2) .webable-git-rev next to app (Docker / CI)
    3) git rev-parse HEAD when .git exists
    """
    env_sha = (os.environ.get("WEBABLE_LOCAL_GIT_COMMIT") or "").strip()
    if env_sha:
        return env_sha[:40]

    rev_file = _repo_root() / ".webable-git-rev"
    file_sha = _read_text_file(rev_file)
    if file_sha:
        return file_sha[:40]

    git_dir = _repo_root() / ".git"
    if git_dir.exists():
        try:
            out = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(_repo_root()),
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()[:40]
        except (OSError, subprocess.SubprocessError) as exc:
            log.debug("git rev-parse unavailable: %s", exc)
    return None


def has_internet(timeout: float = 4.0) -> bool:
    """Return True if a lightweight HTTPS request succeeds."""
    try:
        req = urllib.request.Request(
            CONNECTIVITY_CHECK_URL,
            method="HEAD",
            headers={"User-Agent": "Webable-UpdateCheck/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= getattr(resp, "status", resp.getcode()) < 500
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return False


def _github_headers() -> dict[str, str]:
    h = {
        "User-Agent": "Webable-UpdateCheck/1.0",
        "Accept": "application/vnd.github+json",
    }
    tok = (os.environ.get("WEBABLE_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _http_get_json(url: str, timeout: float = 12.0) -> dict[str, Any] | None:
    req = urllib.request.Request(url, headers=_github_headers(), method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw)


def _http_get_text(url: str, timeout: float = 15.0, *, github_api_headers: bool = False) -> str | None:
    headers = _github_headers() if github_api_headers else {"User-Agent": "Webable-UpdateCheck/1.0"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def _render_markdown_safe(md: str) -> str:
    """Turn release notes into HTML and strip dangerous tags."""
    try:
        import bleach
        from markdown import markdown

        html = markdown(md or "", extensions=["nl2br", "tables"], output_format="html")
        allowed_tags = {
            "p",
            "pre",
            "code",
            "h1",
            "h2",
            "h3",
            "h4",
            "ul",
            "ol",
            "li",
            "hr",
            "br",
            "strong",
            "em",
            "blockquote",
            "a",
            "span",
            "div",
            "table",
            "thead",
            "tbody",
            "tr",
            "th",
            "td",
        }
        allowed_attrs = {"a": ["href", "title", "rel"], "th": ["colspan", "rowspan"], "td": ["colspan", "rowspan"]}
        return bleach.clean(html, tags=allowed_tags, attributes=allowed_attrs, strip=True)
    except ImportError:
        from html import escape

        return f'<pre class="whitespace-pre-wrap text-sm text-slate-300">{escape(md or "")}</pre>'


def fetch_remote_main_sha(owner: str, repo: str) -> str | None:
    url = GITHUB_API_COMMITS.format(owner=owner, repo=repo)
    try:
        data = _http_get_json(url)
        sha = (data or {}).get("sha")
        if isinstance(sha, str) and len(sha) >= 7:
            return sha[:40]
    except Exception as exc:
        log.warning("GitHub commit fetch failed: %s", exc)
    return None


def fetch_update_md(owner: str, repo: str, ref: str) -> tuple[str | None, str | None]:
    """Return (raw_markdown, html) for update.md at ref (branch name or full sha)."""
    url = RAW_UPDATE_MD.format(owner=owner, repo=repo, ref=ref)
    try:
        raw = _http_get_text(url)
        if raw is None:
            return None, None
        return raw, _render_markdown_safe(raw)
    except Exception as exc:
        log.warning("update.md fetch failed: %s", exc)
        return None, None


def _can_apply_git_update(repo: Path) -> bool:
    from . import deployment_mode

    if deployment_mode.get_deployment_mode() != "git":
        return False
    if os.environ.get("WEBABLE_AUTO_UPDATE", "").strip().lower() not in ("1", "true", "yes"):
        return False
    git_dir = repo / ".git"
    if not git_dir.exists():
        return False
    try:
        r = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=5)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def check_for_update(*, force_refresh: bool = False) -> UpdateStatus:
    """
    Compare local revision to GitHub main. Safe to call from any thread.
    When offline, returns update_available=False without error noise.
    """
    from . import deployment_mode

    owner = os.environ.get("WEBABLE_GITHUB_OWNER", DEFAULT_OWNER).strip() or DEFAULT_OWNER
    repo = os.environ.get("WEBABLE_GITHUB_REPO", DEFAULT_REPO).strip() or DEFAULT_REPO
    repo_root = _repo_root()

    env_git_auto = os.environ.get("WEBABLE_AUTO_UPDATE", "").strip().lower() in ("1", "true", "yes")
    auto_enabled = env_git_auto and deployment_mode.get_deployment_mode() == "git"

    status = UpdateStatus(
        repo_root=str(repo_root),
        auto_update_enabled=auto_enabled,
        can_apply_git_update=_can_apply_git_update(repo_root),
    )

    if not has_internet():
        status.online = False
        status.check_performed = True
        status.local_sha = get_local_revision()
        return status

    status.online = True
    status.local_sha = get_local_revision()
    remote_sha = fetch_remote_main_sha(owner, repo)
    status.remote_sha = remote_sha
    status.check_performed = True

    if not remote_sha:
        status.error = "Could not read latest revision from GitHub."
        return status

    # Prefer release notes at the same commit as remote tip when possible.
    raw_md, html_md = fetch_update_md(owner, repo, remote_sha)
    if raw_md is None:
        raw_md, html_md = fetch_update_md(owner, repo, "main")

    status.update_md_raw = raw_md
    status.update_md_html = html_md or '<p class="text-slate-400 text-sm">No update.md found for this release.</p>'

    local = status.local_sha
    if not local:
        # Unknown local revision (e.g. shallow image without stamp): treat as update candidate if you want nagging;
        # we only flag when local is known and differs.
        status.update_available = False
        status.error = status.error or "Local revision unknown; set WEBABLE_LOCAL_GIT_COMMIT or mount .webable-git-rev."
        return status

    status.update_available = local != remote_sha
    return status


def invalidate_update_cache() -> None:
    """Clear cached GitHub comparison (e.g. after a successful git pull)."""
    with _CACHE_LOCK:
        _CACHE["payload"] = None
        _CACHE["checked_at"] = 0.0


def get_cached_status(*, force_refresh: bool = False) -> UpdateStatus:
    """Return cached UpdateStatus, refreshing if stale or force_refresh."""
    ttl = float(_CACHE.get("ttl_seconds") or 300)
    now = time.monotonic()
    with _CACHE_LOCK:
        if not force_refresh and _CACHE["payload"] is not None and (now - float(_CACHE["checked_at"] or 0)) < ttl:
            return _CACHE["payload"]
        payload = check_for_update(force_refresh=force_refresh)
        _CACHE["checked_at"] = now
        _CACHE["payload"] = payload
        return payload


def refresh_cache_background() -> None:
    """Non-blocking refresh used on app startup."""

    def _run() -> None:
        try:
            get_cached_status(force_refresh=True)
            log.info("Background update check finished.")
        except Exception:
            log.exception("Background update check failed.")

    threading.Thread(target=_run, name="webable-update-check", daemon=True).start()
