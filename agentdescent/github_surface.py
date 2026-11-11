"""Publish an accepted candidate as a GitHub proposal branch and pull request.

The evolution loop already produces the two things a reviewer needs: the diff it
accepted and the evidence behind it. GitHub is where a team reviews and merges
that change, so this module is deliberately a *publisher*, not a second merge
engine:

* the local :class:`~agentdescent.ledger.Ledger` keeps the fast CAS/merge loop;
* this surface turns one accepted state into a proposal branch, a commit, a PR
  and an optional check run;
* the PR body carries the evidence summary and the decision/lineage hashes;
* the server never merges, auto-approves or writes the base branch.

    config = GitHubConfig("Birfy", "agentdescent", token_env="GITHUB_TOKEN")
    proposal = Proposal(
        branch="agent/skill-csv-total",
        title="feat(skill): improve csv total",
        body="evidence...",
        files={"skills/csv/SKILL.md": new_text},
        evidence={"decision": "promote", "artifact_hash": "sha256:..."})
    publish_proposal(config, proposal, dry_run=True)   # plan, no network
    publish_proposal(config, proposal, dry_run=False)  # branch + PR + check

The token is read from an environment variable named by ``token_env`` and is
never accepted as a command-line argument, written into the proposal or printed.
The base branch and the repository's default branch are never written, and an
existing proposal branch is only ever fast-forwarded, never force-updated.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence, Set, Tuple, Union

__all__ = [
    "GITHUB_SCHEMA_VERSION",
    "GitHubError",
    "GitHubConfig",
    "CheckSpec",
    "Proposal",
    "ReviewConstraint",
    "extract_review_constraints",
    "UrllibTransport",
    "GitHubClient",
    "publish_proposal",
    "github_status",
    "github_review",
    "load_proposal",
]

GITHUB_SCHEMA_VERSION = 1

_ALLOWED_CONCLUSIONS = ("success", "failure", "neutral", "skipped")


class GitHubError(ValueError):
    """A GitHub input or API failure the surface can report safely."""

    def __init__(self, message: str, *, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.status = status


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GitHubError(f"{name} must be a non-empty string")
    return value


def _safe_path(path: Any) -> str:
    text = _text(path, "proposal file path").replace("\\", "/")
    if text.startswith("/") or text.startswith("../") or "/../" in text or text == "..":
        raise GitHubError(f"proposal file path {path!r} must be relative and "
                          "must not leave the repository")
    if any(part in ("", ".", "..") for part in text.split("/")):
        raise GitHubError(f"proposal file path {path!r} is not a clean relative path")
    return text


@dataclass(frozen=True)
class GitHubConfig:
    """Where to publish and which environment variable holds the token."""

    owner: str
    repo: str
    base: str = "main"
    token_env: str = "AGENTDESCENT_GITHUB_TOKEN"
    api_url: str = "https://api.github.com"

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner", _text(self.owner, "owner"))
        object.__setattr__(self, "repo", _text(self.repo, "repo"))
        object.__setattr__(self, "base", _text(self.base, "base"))
        object.__setattr__(self, "token_env", _text(self.token_env, "token_env"))
        object.__setattr__(self, "api_url", _text(self.api_url, "api_url").rstrip("/"))

    def token(self) -> str:
        value = os.environ.get(self.token_env)
        if not value:
            raise GitHubError(
                f"GitHub token is not set; export {self.token_env}=... "
                "(the token is never read from argv)")
        return value


@dataclass(frozen=True)
class CheckSpec:
    """One check run attached to the proposal commit."""

    conclusion: str = "success"
    title: str = ""
    summary: str = ""
    text: str = ""
    name: str = "agentdescent/evidence"

    def __post_init__(self) -> None:
        if self.conclusion not in _ALLOWED_CONCLUSIONS:
            raise GitHubError(
                f"check conclusion must be one of {_ALLOWED_CONCLUSIONS}")
        object.__setattr__(self, "name", _text(self.name, "check name"))


@dataclass(frozen=True)
class Proposal:
    """One accepted candidate ready for human review."""

    branch: str
    title: str
    body: str
    files: Mapping[str, Union[str, bytes]]
    base: Optional[str] = None
    draft: bool = False
    labels: Tuple[str, ...] = ()
    run_id: str = ""
    artifact_id: str = ""
    evidence: Mapping[str, Any] = field(default_factory=dict)
    check: Optional[CheckSpec] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "branch", _text(self.branch, "branch"))
        object.__setattr__(self, "title", _text(self.title, "title"))
        if not isinstance(self.body, str):
            raise GitHubError("body must be a string")
        if not isinstance(self.files, Mapping) or not self.files:
            raise GitHubError("files must be a non-empty mapping")
        cleaned = {}
        for path, content in self.files.items():
            clean = _safe_path(path)
            if not isinstance(content, (str, bytes)):
                raise GitHubError(f"file {path!r} content must be str or bytes")
            cleaned[clean] = content
        object.__setattr__(self, "files", cleaned)
        if self.base is not None:
            object.__setattr__(self, "base", _text(self.base, "base"))
        if isinstance(self.labels, str):
            raise GitHubError("labels must be a sequence, not a bare string")
        object.__setattr__(self, "labels", tuple(str(label) for label in self.labels))
        if not isinstance(self.evidence, Mapping):
            raise GitHubError("evidence must be a JSON object")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "branch": self.branch,
            "title": self.title,
            "body": self.body,
            "files": sorted(self.files),
            "base": self.base,
            "draft": self.draft,
            "labels": list(self.labels),
            "run_id": self.run_id,
            "artifact_id": self.artifact_id,
            "evidence": dict(self.evidence),
            "check": None if self.check is None else {
                "name": self.check.name,
                "conclusion": self.check.conclusion,
                "title": self.check.title,
                "summary": self.check.summary,
            },
        }


def load_proposal(value: Any) -> Proposal:
    """A :class:`Proposal` from a mapping or a JSON file."""
    if isinstance(value, Mapping):
        data = dict(value)
    elif isinstance(value, str):
        path = os.path.abspath(os.path.expanduser(value))
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except OSError as error:
            raise GitHubError(f"proposal {value!r} cannot be read: {error}") from None
        except ValueError as error:
            raise GitHubError(
                f"proposal {value!r} is not valid JSON: {error}") from None
        if not isinstance(data, Mapping):
            raise GitHubError("proposal must be a JSON object")
        data = dict(data)
    else:
        raise GitHubError("proposal must be a JSON object or a path")
    files = data.get("files")
    if isinstance(files, list):
        files = {_safe_path(row.get("path")): row.get("content")
                 for row in files if isinstance(row, Mapping)}
    check = data.get("check")
    if isinstance(check, Mapping):
        check = CheckSpec(**dict(check))
    return Proposal(
        branch=data.get("branch", ""),
        title=data.get("title", ""),
        body=data.get("body", ""),
        files=files or {},
        base=data.get("base"),
        draft=bool(data.get("draft", False)),
        labels=tuple(data.get("labels") or ()),
        run_id=str(data.get("run_id", "")),
        artifact_id=str(data.get("artifact_id", "")),
        evidence=dict(data.get("evidence") or {}),
        check=check if isinstance(check, CheckSpec) else None,
    )


@dataclass(frozen=True)
class ReviewConstraint:
    """One actionable request extracted from a review or inline comment."""

    id: str
    kind: str
    text: str
    source: str
    path: str = ""
    severity: str = "suggestion"
    resolved: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "text": self.text,
            "source": self.source,
            "path": self.path,
            "severity": self.severity,
            "resolved": self.resolved,
        }


_ACTION = re.compile(
    r"\b(must|blocking|required?|please|needs?|cannot|can't|don't|do not|"
    r"fix|add|remove|rename|refuse|handle|avoid|ensure|update|revert)\b",
    re.IGNORECASE)
_TEST = re.compile(r"\b(test|tests|pytest|coverage|regression|fixture)\b",
                   re.IGNORECASE)
_SECURITY = re.compile(
    r"\b(secret|token|credential|permission|auth|injection|sanitize|leak|"
    r"escape|traversal)\b", re.IGNORECASE)
_API = re.compile(
    r"\b(api|compat|backward|deprecat|signature|rename|schema|contract)\b",
    re.IGNORECASE)
_DOCS = re.compile(r"\b(doc|docs|readme|docstring|comment|typo)\b",
                   re.IGNORECASE)
_STYLE = re.compile(r"\b(lint|format|typing|type hint|naming|style)\b",
                    re.IGNORECASE)
_PATH = re.compile(r"`([^`\n]+\.[A-Za-z0-9_]+)`")
_WS = re.compile(r"\s+")


def _constraint_kind(text: str) -> str:
    if _SECURITY.search(text):
        return "security"
    if _TEST.search(text):
        return "test"
    if _API.search(text):
        return "api"
    if _DOCS.search(text):
        return "docs"
    if _STYLE.search(text):
        return "style"
    if _ACTION.search(text):
        return "behavior"
    return "note"


def _constraint_text(value: Any) -> str:
    return _WS.sub(" ", str(value or "")).strip()


def _constraint_id(kind: str, text: str, path: str) -> str:
    payload = json.dumps([kind, text.lower(), path], ensure_ascii=False)
    return "rc_" + hashlib.sha1(payload.encode()).hexdigest()[:12]


def extract_review_constraints(
        reviews: Sequence[Mapping[str, Any]],
        comments: Sequence[Mapping[str, Any]], *,
        resolved_ids: Sequence[str] = ()) -> Tuple[ReviewConstraint, ...]:
    """Turn review bodies and inline comments into deduplicated constraints.

    REST does not expose whether a review thread is resolved, so ``resolved``
    is false unless the caller passes the ids it knows are resolved. A
    ``CHANGES_REQUESTED`` review (or one of its inline comments) is a blocking
    constraint; any other review or comment is a suggestion unless its text
    carries an action phrase (``please``, ``add``, ``update``, ``fix``, ...),
    which promotes it to blocking. Plain "thanks" notes are dropped rather than
    becoming tasks. Each reviewer's representative review decides (see
    ``_latest_reviews``): a change request that reviewer later approved or had
    dismissed stays as a suggestion instead of blocking, while a plain later
    comment neither lifts nor weakens the block (#774).
    """
    resolved = {str(value) for value in resolved_ids}
    mapped = [review for review in reviews if isinstance(review, Mapping)]
    superseded = _superseded_review_ids(mapped)
    review_state = {}
    for review in mapped:
        if str(review.get("id", "")) in superseded:
            continue
        review_state[str(review.get("id", ""))] = str(
            review.get("state", "")).upper()
    found: Dict[str, ReviewConstraint] = {}
    for review in mapped:
        text = _constraint_text(review.get("body"))
        if not text:
            continue
        kind = _constraint_kind(text)
        if kind == "note":
            continue
        source = f"review:{review.get('id', '')}"
        stale = str(review.get("id", "")) in superseded
        severity = ("blocking"
                    if str(review.get("state", "")).upper() == "CHANGES_REQUESTED"
                    and not stale else "suggestion")
        if _ACTION.search(text) and severity == "suggestion" and not stale:
            severity = "blocking"
        rc_id = _constraint_id(kind, text, "")
        _add_constraint(found, ReviewConstraint(
            id=rc_id, kind=kind, text=text, source=source,
            severity=severity, resolved=source in resolved))
    for comment in comments:
        if not isinstance(comment, Mapping):
            continue
        text = _constraint_text(comment.get("body"))
        if not text:
            continue
        kind = _constraint_kind(text)
        if kind == "note":
            continue
        path = str(comment.get("path", "") or "")
        source = f"comment:{comment.get('id', '')}"
        parent = str(comment.get("pull_request_review_id", ""))
        stale = parent in superseded
        severity = ("blocking"
                    if review_state.get(parent) == "CHANGES_REQUESTED"
                    or (_ACTION.search(text) and not stale) else "suggestion")
        rc_id = _constraint_id(kind, text, path)
        _add_constraint(found, ReviewConstraint(
            id=rc_id, kind=kind, text=text, source=source, path=path,
            severity=severity, resolved=source in resolved))
    return tuple(sorted(found.values(), key=lambda row: (
        row.severity != "blocking", row.kind, row.path, row.text)))


def _add_constraint(found: Dict[str, ReviewConstraint],
                    row: ReviewConstraint) -> None:
    """Keep the strongest row for a duplicated request; blocking wins."""
    current = found.get(row.id)
    if current is None or (current.severity != "blocking"
                           and row.severity == "blocking"):
        found[row.id] = row


class UrllibTransport:
    """The default HTTP transport. Tests inject their own instead."""

    def __init__(self, config: GitHubConfig, *, timeout: float = 60.0) -> None:
        self.config = config
        self.timeout = float(timeout)

    def request(self, method: str, path: str, payload: Optional[Mapping[str, Any]] = None
                ) -> Any:
        body = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            self.config.api_url + path, data=body, method=method,
            headers={
                "Authorization": "token " + self.config.token(),
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": "agentdescent-github-publisher",
            })
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                detail = json.loads(raw).get("message", raw.decode("utf-8", "replace"))
            except (ValueError, AttributeError):
                detail = raw.decode("utf-8", "replace")
            raise GitHubError(
                f"GitHub {method} {path} failed with {error.code}: {detail}",
                status=error.code) from None
        except urllib.error.URLError as error:
            raise GitHubError(
                f"GitHub {method} {path} cannot be reached: {error.reason}") from None
        except ValueError as error:
            raise GitHubError(
                f"GitHub {method} {path} returned invalid JSON: {error}") from None


class GitHubClient:
    """The small Git Data / PR / check-run API this publisher needs."""

    def __init__(self, config: GitHubConfig, *, transport: Any = None) -> None:
        self.config = config
        self.transport = transport or UrllibTransport(config)
        self.root = f"/repos/{config.owner}/{config.repo}"

    def _request(self, method: str, path: str,
                 payload: Optional[Mapping[str, Any]] = None) -> Any:
        return self.transport.request(method, self.root + path, payload)

    def get_repo(self) -> Dict[str, Any]:
        return self._request("GET", "")

    def get_ref(self, ref: str) -> Dict[str, Any]:
        encoded = urllib.parse.quote(f"heads/{ref}", safe="")
        return self._request("GET", f"/git/ref/{encoded}")

    def get_commit(self, sha: str) -> Dict[str, Any]:
        return self._request("GET", f"/git/commits/{sha}")

    def compare_commits(self, base_sha: str, head_sha: str) -> Dict[str, Any]:
        return self._request("GET", f"/compare/{base_sha}...{head_sha}")

    def create_blob(self, content: Union[str, bytes]) -> str:
        raw = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        result = self._request("POST", "/git/blobs", {
            "content": base64.b64encode(raw).decode(),
            "encoding": "base64"})
        return result["sha"]

    def create_tree(self, base_tree: str,
                    entries: Sequence[Mapping[str, Any]]) -> str:
        result = self._request("POST", "/git/trees", {
            "base_tree": base_tree, "tree": list(entries)})
        return result["sha"]

    def create_commit(self, message: str, tree: str,
                      parents: Sequence[str]) -> str:
        result = self._request("POST", "/git/commits", {
            "message": message, "tree": tree, "parents": list(parents)})
        return result["sha"]

    def create_ref(self, branch: str, sha: str) -> Any:
        return self._request("POST", "/git/refs", {
            "ref": f"refs/heads/{branch}", "sha": sha})

    def update_ref(self, branch: str, sha: str) -> Any:
        # Never `force: true`: GitHub then refuses a non-fast-forward write
        # itself, so a rewritten proposal history cannot slip through (#913).
        encoded = urllib.parse.quote(f"heads/{branch}", safe="")
        return self._request("PATCH", f"/git/refs/{encoded}", {
            "sha": sha, "force": False})

    def find_pull(self, branch: str, base: str) -> Optional[Dict[str, Any]]:
        query = urllib.parse.urlencode({
            "state": "open", "head": f"{self.config.owner}:{branch}",
            "base": base, "per_page": 5})
        rows = self._request("GET", f"/pulls?{query}")
        return rows[0] if rows else None

    def create_pull(self, title: str, branch: str, base: str, body: str,
                    *, draft: bool = False) -> Dict[str, Any]:
        return self._request("POST", "/pulls", {
            "title": title, "head": f"{self.config.owner}:{branch}",
            "base": base, "body": body, "draft": draft})

    def update_pull(self, number: int, **fields: Any) -> Dict[str, Any]:
        return self._request("PATCH", f"/pulls/{number}", fields)

    def get_pull(self, number: int) -> Dict[str, Any]:
        return self._request("GET", f"/pulls/{number}")

    def add_labels(self, number: int, labels: Sequence[str]) -> Any:
        if not labels:
            return None
        return self._request("POST", f"/issues/{number}/labels",
                             {"labels": list(labels)})

    def create_check_run(self, name: str, head_sha: str, check: CheckSpec) -> Any:
        output = {"title": check.title or check.name,
                  "summary": check.summary or ""}
        if check.text:
            output["text"] = check.text
        return self._request("POST", "/check-runs", {
            "name": name, "head_sha": head_sha, "status": "completed",
            "conclusion": check.conclusion, "output": output})

    def list_check_runs(self, ref: str) -> Any:
        return self._request("GET", f"/commits/{ref}/check-runs?per_page=100")

    def list_reviews(self, number: int) -> Any:
        return self._request("GET", f"/pulls/{number}/reviews?per_page=100")

    def list_review_comments(self, number: int) -> Any:
        return self._request("GET", f"/pulls/{number}/comments?per_page=100")


def _evidence_text(proposal: Proposal) -> str:
    if not proposal.evidence:
        return ""
    try:
        payload = json.dumps(dict(proposal.evidence), indent=2, sort_keys=True,
                             ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        payload = str(proposal.evidence)
    if len(payload) > 4000:
        payload = payload[:3999].rstrip() + "…"
    return payload


def _body(proposal: Proposal) -> str:
    body = proposal.body.rstrip()
    evidence = _evidence_text(proposal)
    trailer = [
        "",
        "---",
        "Published by `agentdescent github publish`.",
        f"Run: `{proposal.run_id or '-'}`  ·  artifact: `{proposal.artifact_id or '-'}`",
    ]
    if evidence:
        trailer += ["", "```json", evidence, "```"]
    return body + "\n" + "\n".join(trailer) + "\n"


def _dry_run_payload(proposal: Proposal, config: GitHubConfig) -> Dict[str, Any]:
    base = proposal.base or config.base
    return {
        "schema_version": GITHUB_SCHEMA_VERSION,
        "ok": True,
        "dry_run": True,
        "owner": config.owner,
        "repo": config.repo,
        "base": base,
        "branch": proposal.branch,
        "title": proposal.title,
        "files": sorted(proposal.files),
        "labels": list(proposal.labels),
        "check": None if proposal.check is None else proposal.check.name,
        "next": [
            "review the proposal JSON, then re-run with --apply "
            f"(token from {config.token_env})",
        ],
    }


def _require_fast_forward(client: GitHubClient, branch: str, old_sha: str,
                          base_sha: str) -> None:
    """Refuse to rewrite an existing proposal branch (#913).

    The new commit is built on ``base_sha``, so the branch can be fast-forwarded
    exactly when its current head is an ancestor of that base. Anything else
    (a rewound or diverged branch) is a history rewrite this surface must not do.
    """
    status = client.compare_commits(old_sha, base_sha).get("status", "")
    if status not in ("ahead", "identical"):
        raise GitHubError(
            f"proposal branch {branch!r} is not a fast-forward of base "
            f"{base_sha[:12]} ({status or 'unknown'}); refusing to rewrite it")


def publish_proposal(config: GitHubConfig, proposal: Proposal, *,
                     dry_run: bool = True, transport: Any = None) -> Dict[str, Any]:
    """Create/update a proposal branch, commit, PR and optional check run.

    ``dry_run=True`` makes no network call and needs no token. Neither the base
    branch nor the repository's default branch is ever written, and an existing
    proposal branch is only fast-forwarded (never force-updated).
    """
    if not isinstance(config, GitHubConfig):
        raise GitHubError("config must be a GitHubConfig")
    if not isinstance(proposal, Proposal):
        raise GitHubError("proposal must be a Proposal")
    base = proposal.base or config.base
    if proposal.branch in (base, config.base):
        raise GitHubError("a proposal branch cannot be the base branch")
    if dry_run:
        return _dry_run_payload(proposal, config)

    client = GitHubClient(config, transport=transport)
    default_branch = client.get_repo().get("default_branch", "")
    if proposal.branch in (base, config.base, default_branch):
        raise GitHubError(
            f"a proposal branch cannot be the repository default branch "
            f"{default_branch!r}")
    base_ref = client.get_ref(base)
    base_sha = base_ref["object"]["sha"]
    try:
        existing = client.get_ref(proposal.branch)["object"]["sha"]
    except GitHubError as error:
        if error.status != 404:
            raise
        existing = None
    if existing is not None:
        _require_fast_forward(client, proposal.branch, existing, base_sha)
    base_commit = client.get_commit(base_sha)
    base_tree = base_commit["tree"]["sha"]

    entries = []
    for path in sorted(proposal.files):
        blob = client.create_blob(proposal.files[path])
        entries.append({"path": path, "mode": "100644", "type": "blob",
                        "sha": blob})
    tree = client.create_tree(base_tree, entries)
    commit = client.create_commit(proposal.title, tree, [base_sha])
    if existing is not None:
        client.update_ref(proposal.branch, commit)
    else:
        try:
            client.create_ref(proposal.branch, commit)
        except GitHubError as error:
            if error.status != 422:
                raise
            # The branch appeared between the read and the write: re-read it and
            # fast-forward only, instead of the old blind force update (#913).
            current = client.get_ref(proposal.branch)["object"]["sha"]
            _require_fast_forward(client, proposal.branch, current, base_sha)
            client.update_ref(proposal.branch, commit)

    body = _body(proposal)
    existing = client.find_pull(proposal.branch, base)
    if existing is not None:
        number = int(existing["number"])
        pull = client.update_pull(number, title=proposal.title, body=body)
    else:
        pull = client.create_pull(
            proposal.title, proposal.branch, base, body, draft=proposal.draft)
        number = int(pull["number"])
    warnings = []
    try:
        client.add_labels(number, proposal.labels)
    except GitHubError as error:
        warnings.append(f"labels: {error}")
    check = None
    if proposal.check is not None:
        try:
            check = client.create_check_run(proposal.check.name, commit, proposal.check)
        except GitHubError as error:
            warnings.append(f"check run: {error}")
    payload = {
        "schema_version": GITHUB_SCHEMA_VERSION,
        "ok": True,
        "dry_run": False,
        "owner": config.owner,
        "repo": config.repo,
        "base": base,
        "branch": proposal.branch,
        "head": commit,
        "pull_request": number,
        "url": pull.get("html_url", ""),
        "check_run": check,
        "files": sorted(proposal.files),
        "next": [
            "review the PR and its check run",
            "merge only after the risk-tier rule and an explicit owner click",
        ],
    }
    if warnings:
        payload["warnings"] = warnings
    return payload


def github_status(config: GitHubConfig, number: int, *,
                  transport: Any = None) -> Dict[str, Any]:
    """Read one PR plus its check runs; no writes and no model calls."""
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise GitHubError("pr must be an int >= 1")
    client = GitHubClient(config, transport=transport)
    pull = client.get_pull(number)
    head = pull.get("head", {}).get("sha", "")
    checks = []
    if head:
        raw = client.list_check_runs(head)
        for row in raw.get("check_runs", []) if isinstance(raw, dict) else []:
            checks.append({
                "name": row.get("name", ""),
                "status": row.get("status", ""),
                "conclusion": row.get("conclusion", ""),
            })
    return {
        "schema_version": GITHUB_SCHEMA_VERSION,
        "ok": True,
        "owner": config.owner,
        "repo": config.repo,
        "pull_request": number,
        "title": pull.get("title", ""),
        "state": pull.get("state", ""),
        "draft": bool(pull.get("draft", False)),
        "mergeable": pull.get("mergeable"),
        "head": head,
        "base": pull.get("base", {}).get("ref", ""),
        "url": pull.get("html_url", ""),
        "checks": checks,
    }

def _checks_state(checks: Sequence[Mapping[str, Any]]) -> str:
    if not checks:
        return "none"
    conclusions = {str(row.get("conclusion") or "").lower() for row in checks}
    statuses = {str(row.get("status") or "").lower() for row in checks}
    if conclusions & {"failure", "timed_out", "cancelled", "action_required"}:
        return "failure"
    if "in_progress" in statuses or "queued" in statuses or "" in statuses:
        return "pending"
    if conclusions <= {"success", "skipped", "neutral"}:
        return "success"
    return "pending"


def _review_sort_key(review: Mapping[str, Any]) -> Tuple[str, int]:
    try:
        ident = int(review.get("id") or 0)
    except (TypeError, ValueError):
        ident = 0
    return (str(review.get("submitted_at") or ""), ident)


def _review_author(review: Mapping[str, Any]) -> str:
    user = review.get("user")
    login = str(user.get("login", "")) if isinstance(user, Mapping) else ""
    # A review without a login cannot supersede anyone: keep it its own author so
    # the packet stays fail-closed instead of dropping a change request.
    return login or f"review:{review.get('id', '')}"


_DECISIVE_REVIEW_STATES = frozenset({"APPROVED", "CHANGES_REQUESTED", "DISMISSED"})


def _latest_reviews(
        reviews: Sequence[Mapping[str, Any]]) -> Dict[str, Mapping[str, Any]]:
    """Keep each reviewer's representative review.

    GitHub keeps every review event, so ``CHANGES_REQUESTED`` followed by
    ``APPROVED`` from the same reviewer would otherwise block forever, which is
    the "please re-review" flow this repository actually runs on (#774).

    The representative is the author's latest ``APPROVED``,
    ``CHANGES_REQUESTED`` or ``DISMISSED`` review: those are the states that
    settle a block. A plain ``COMMENTED`` review never overrides one of them,
    because GitHub keeps a change request until an approval or a dismissal, so
    a later comment must not read as if the block were lifted (#774). An author
    with no such review keeps the latest review of any state. A pending review
    has no ``submitted_at`` and therefore never supersedes a submitted one.
    """
    latest: Dict[str, Mapping[str, Any]] = {}
    decisive: Dict[str, Mapping[str, Any]] = {}
    for review in reviews:
        if not isinstance(review, Mapping):
            continue
        author = _review_author(review)
        key = _review_sort_key(review)
        current = latest.get(author)
        if current is None or key >= _review_sort_key(current):
            latest[author] = review
        if str(review.get("state", "")).upper() in _DECISIVE_REVIEW_STATES:
            settled = decisive.get(author)
            if settled is None or key >= _review_sort_key(settled):
                decisive[author] = review
    latest.update(decisive)
    return latest


def _superseded_review_ids(reviews: Sequence[Mapping[str, Any]]) -> Set[str]:
    known = {str(review.get("id", "")) for review in reviews
             if isinstance(review, Mapping)}
    latest = {str(review.get("id", ""))
              for review in _latest_reviews(reviews).values()}
    return known - latest


def _review_counts(reviews: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    """Count review states, one per reviewer: the latest review wins."""
    counts = {"approved": 0, "changes_requested": 0, "commented": 0,
              "dismissed": 0, "pending": 0, "other": 0}
    for review in _latest_reviews(reviews).values():
        state = str(review.get("state", "")).upper()
        key = {
            "APPROVED": "approved", "CHANGES_REQUESTED": "changes_requested",
            "COMMENTED": "commented", "DISMISSED": "dismissed",
            "PENDING": "pending",
        }.get(state, "other")
        counts[key] += 1
    return counts


def github_review(config: GitHubConfig, number: int, *,
                  transport: Any = None,
                  resolved_ids: Sequence[str] = ()) -> Dict[str, Any]:
    """Read a PR's reviews, inline comments and checks into one review packet.

    Extracted review constraints are *evidence*, not an approval: the packet
    reports whether the PR is ready for a human click and why it is blocked.
    This function never writes, approves or merges.
    """
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise GitHubError("pr must be an int >= 1")
    client = GitHubClient(config, transport=transport)
    pull = client.get_pull(number)
    head = pull.get("head", {}).get("sha", "")
    reviews = client.list_reviews(number)
    comments = client.list_review_comments(number)
    raw_checks = client.list_check_runs(head) if head else {"check_runs": []}
    check_rows = raw_checks.get("check_runs", []) if isinstance(raw_checks, dict) else []
    checks = [{
        "name": row.get("name", ""),
        "status": row.get("status", ""),
        "conclusion": row.get("conclusion", ""),
    } for row in check_rows if isinstance(row, Mapping)]
    constraints = extract_review_constraints(
        reviews if isinstance(reviews, list) else [],
        comments if isinstance(comments, list) else [],
        resolved_ids=resolved_ids)
    counts = _review_counts(reviews if isinstance(reviews, list) else [])
    state = _checks_state(check_rows)
    blockers = []
    if str(pull.get("state", "")) != "open":
        blockers.append("pull request is not open")
    if pull.get("draft"):
        blockers.append("pull request is a draft")
    if pull.get("mergeable") is False:
        blockers.append("GitHub reports merge conflicts")
    if counts["changes_requested"]:
        blockers.append(f"{counts['changes_requested']} reviewer(s) requested changes")
    unresolved = [row for row in constraints
                  if row.severity == "blocking" and not row.resolved]
    if unresolved:
        blockers.append(f"{len(unresolved)} unresolved blocking review constraint(s)")
    if state == "failure":
        blockers.append("a check failed")
    elif state == "pending":
        blockers.append("checks are still running")
    elif state == "none":
        blockers.append("no check runs on the head")
    ready = not blockers
    return {
        "schema_version": GITHUB_SCHEMA_VERSION,
        "ok": True,
        "owner": config.owner,
        "repo": config.repo,
        "pull_request": number,
        "title": pull.get("title", ""),
        "state": pull.get("state", ""),
        "draft": bool(pull.get("draft", False)),
        "mergeable": pull.get("mergeable"),
        "head": head,
        "base": pull.get("base", {}).get("ref", ""),
        "url": pull.get("html_url", ""),
        "reviews": counts,
        "checks_state": state,
        "checks": checks,
        "constraints": [row.to_dict() for row in constraints],
        "merge_readiness": {
            "ready": ready,
            "requires_human_click": True,
            "blockers": blockers,
            "next": (["ready for an authorized reviewer/owner click; this surface "
                      "never merges"] if ready else blockers),
        },
    }
