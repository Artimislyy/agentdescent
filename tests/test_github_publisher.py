"""GitHub publisher: proposal branch, PR, labels and check run, offline."""

import json
import urllib.parse

import pytest

from agentdescent import cli
from agentdescent.github_surface import (
    CheckSpec,
    GitHubConfig,
    GitHubError,
    Proposal,
    extract_review_constraints,
    github_review,
    github_status,
    load_proposal,
    publish_proposal,
)


class FakeGitHub:
    def __init__(self, *, existing_pull=None):
        self.calls = []
        self.refs = {"main": "base123"}
        self.default_branch = "main"
        self.compare_status = {}
        self.pulls = []
        self.existing_pull = existing_pull
        self.labels = []
        self.checks = []
        self.reviews = []
        self.review_comments = []
        self._n = 0

    def _next(self, prefix):
        self._n += 1
        return f"{prefix}{self._n}"

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        root = "/repos/o/r"
        assert path.startswith(root), path
        path = path[len(root):]
        if method == "GET" and path == "":
            return {"default_branch": self.default_branch}
        if method == "GET" and path.startswith("/compare/"):
            base, _, head = path[len("/compare/"):].partition("...")
            return {"status": self.compare_status.get(
                (base, head), "identical" if base == head else "ahead")}
        if method == "GET" and path.startswith("/git/ref/heads"):
            ref = urllib.parse.unquote(path[len("/git/ref/"):])
            branch = ref.split("heads/", 1)[1]
            if branch not in self.refs:
                raise GitHubError("not found", status=404)
            return {"object": {"sha": self.refs[branch]}}
        if method == "GET" and path.startswith("/git/commits/"):
            return {"tree": {"sha": "treebase"}}
        if method == "POST" and path == "/git/blobs":
            return {"sha": self._next("blob")}
        if method == "POST" and path == "/git/trees":
            return {"sha": self._next("tree")}
        if method == "POST" and path == "/git/commits":
            return {"sha": self._next("commit")}
        if method == "POST" and path == "/git/refs":
            ref = payload["ref"].split("/", 2)[-1]
            if ref in self.refs:
                raise GitHubError("exists", status=422)
            self.refs[ref] = payload["sha"]
            return {"ref": payload["ref"], "object": {"sha": payload["sha"]}}
        if method == "PATCH" and path.startswith("/git/refs/heads"):
            ref = urllib.parse.unquote(path[len("/git/refs/"):])
            branch = ref.split("heads/", 1)[1]
            self.refs[branch] = payload["sha"]
            return {"ref": f"refs/heads/{branch}", "object": {"sha": payload["sha"]}}
        if method == "GET" and path.startswith("/pulls?"):
            return [self.existing_pull] if self.existing_pull else []
        if method == "POST" and path == "/pulls":
            pull = {"number": 7, "html_url": "https://github.com/o/r/pull/7",
                    "title": payload["title"], "state": "open", "draft": payload["draft"],
                    "head": {"sha": self.refs.get(payload["head"].split(":", 1)[1], "")},
                    "base": {"ref": payload["base"]}, "mergeable": True}
            self.pulls.append(pull)
            return pull
        if method == "PATCH" and path == "/pulls/7":
            pull = self.pulls[0]
            pull.update(payload)
            return pull
        if method == "POST" and path == "/issues/7/labels":
            self.labels = list(payload["labels"])
            return []
        if method == "POST" and path == "/check-runs":
            check = {"id": 1, "html_url": "https://github.com/o/r/check/1",
                     "name": payload["name"], "status": "completed",
                     "conclusion": payload["conclusion"]}
            self.checks.append(check)
            return check
        if method == "GET" and path == "/pulls/7":
            return self.pulls[0]
        if method == "GET" and path.startswith("/pulls/7/reviews"):
            return self.reviews
        if method == "GET" and path.startswith("/pulls/7/comments"):
            return self.review_comments
        if method == "GET" and path.startswith("/commits/") and "/check-runs" in path:
            return {"check_runs": self.checks}
        raise AssertionError(f"unexpected call {method} {path}")


def _proposal(**overrides):
    payload = {
        "branch": "agent/skill-csv",
        "title": "feat(skill): improve csv total",
        "body": "The held-out evidence is green.",
        "files": {"skills/csv/SKILL.md": "# CSV\nUse cents."},
        "labels": ["agent-pr", "risk:T2"],
        "run_id": "run-1",
        "artifact_id": "skill-csv",
        "evidence": {"decision": "promote", "artifact_hash": "sha256:abc"},
        "check": CheckSpec(
            conclusion="success", title="evidence", summary="held-out +0.2"),
    }
    payload.update(overrides)
    return Proposal(**payload)


def test_dry_run_makes_no_calls_and_needs_no_token(monkeypatch):
    monkeypatch.delenv("AGENTDESCENT_GITHUB_TOKEN", raising=False)
    fake = FakeGitHub()
    payload = publish_proposal(
        GitHubConfig("o", "r"), _proposal(), dry_run=True, transport=fake)
    assert payload["dry_run"] is True
    assert payload["branch"] == "agent/skill-csv"
    assert payload["files"] == ["skills/csv/SKILL.md"]
    assert fake.calls == []


def test_publish_creates_branch_commit_pr_labels_and_check(monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_GITHUB_TOKEN", "secret-token")
    fake = FakeGitHub()
    payload = publish_proposal(
        GitHubConfig("o", "r"), _proposal(), dry_run=False, transport=fake)

    assert payload["dry_run"] is False
    assert payload["pull_request"] == 7
    assert payload["head"].startswith("commit")
    assert payload["check_run"]["name"] == "agentdescent/evidence"
    assert fake.refs["main"] == "base123"
    assert fake.refs["agent/skill-csv"] == payload["head"]
    assert fake.labels == ["agent-pr", "risk:T2"]
    assert fake.checks[0]["conclusion"] == "success"
    encoded = json.dumps(fake.calls)
    assert "secret-token" not in encoded
    assert "sha256:abc" in encoded  # evidence is in the PR body


def test_publish_updates_an_existing_pull(monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_GITHUB_TOKEN", "secret-token")
    existing = {"number": 7, "html_url": "https://github.com/o/r/pull/7",
                "title": "old", "state": "open", "draft": False,
                "head": {"sha": "old"}, "base": {"ref": "main"},
                "mergeable": True}
    fake = FakeGitHub(existing_pull=existing)
    fake.pulls = [existing]
    payload = publish_proposal(
        GitHubConfig("o", "r"), _proposal(), dry_run=False, transport=fake)
    assert payload["pull_request"] == 7
    assert fake.pulls[0]["title"] == "feat(skill): improve csv total"
    assert not any(method == "POST" and path == "/pulls"
                   for method, path, _ in fake.calls)


def test_publish_refuses_base_branch_and_path_traversal(monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_GITHUB_TOKEN", "secret-token")
    with pytest.raises(GitHubError):
        publish_proposal(GitHubConfig("o", "r"),
                         _proposal(branch="main"), dry_run=False,
                         transport=FakeGitHub())
    with pytest.raises(GitHubError):
        _proposal(files={"../escape": "x"})
    with pytest.raises(GitHubError):
        _proposal(files={"/absolute": "x"})


def test_publish_refuses_the_default_branch_before_any_write(monkeypatch):
    # A proposal that names the default branch must never reach a ref write, even
    # when its own base is something else (#913).
    monkeypatch.setenv("AGENTDESCENT_GITHUB_TOKEN", "secret-token")
    fake = FakeGitHub()
    with pytest.raises(GitHubError) as error:
        publish_proposal(GitHubConfig("o", "r", base="develop"),
                         _proposal(branch="main", base="develop"),
                         dry_run=False, transport=fake)
    assert "default branch" in str(error.value)
    writes = [(method, path) for method, path, _ in fake.calls
              if method in ("POST", "PATCH")]
    assert writes == []


def test_publish_refuses_the_configured_base_without_a_network_call():
    # The configured base is knowable offline, so even a dry run refuses it
    # instead of printing a plan that would write `main`.
    with pytest.raises(GitHubError) as error:
        publish_proposal(GitHubConfig("o", "r", base="main"),
                         _proposal(branch="main", base="develop"),
                         dry_run=True, transport=FakeGitHub())
    assert "base branch" in str(error.value)


def test_publish_refuses_to_rewrite_a_diverged_proposal_branch(monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_GITHUB_TOKEN", "secret-token")
    fake = FakeGitHub()
    fake.refs["agent/skill-csv"] = "old-head"
    fake.compare_status[("old-head", "base123")] = "diverged"
    with pytest.raises(GitHubError) as error:
        publish_proposal(GitHubConfig("o", "r"), _proposal(), dry_run=False,
                         transport=fake)
    assert "fast-forward" in str(error.value)
    writes = [(method, path) for method, path, payload in fake.calls
              if method in ("POST", "PATCH")]
    assert writes == []
    assert fake.refs["agent/skill-csv"] == "old-head"


def test_publish_fast_forwards_an_existing_branch_without_force(monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_GITHUB_TOKEN", "secret-token")
    fake = FakeGitHub()
    fake.refs["agent/skill-csv"] = "old-head"
    fake.compare_status[("old-head", "base123")] = "ahead"
    payload = publish_proposal(GitHubConfig("o", "r"), _proposal(),
                               dry_run=False, transport=fake)
    updates = [payload_ for method, path, payload_ in fake.calls
               if method == "PATCH" and "/git/refs/" in path]
    assert len(updates) == 1 and updates[0]["force"] is False
    assert "force\": true" not in json.dumps(fake.calls)
    assert fake.refs["agent/skill-csv"] == payload["head"]


def test_publish_requires_a_token(monkeypatch):
    monkeypatch.delenv("AGENTDESCENT_GITHUB_TOKEN", raising=False)
    with pytest.raises(GitHubError) as error:
        publish_proposal(GitHubConfig("o", "r"), _proposal(), dry_run=False)
    assert "token is not set" in str(error.value)


def test_status_reads_pull_and_checks(monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_GITHUB_TOKEN", "secret-token")
    fake = FakeGitHub()
    fake.pulls = [{"number": 7, "html_url": "https://github.com/o/r/pull/7",
                   "title": "feat", "state": "open", "draft": False,
                   "head": {"sha": "abc"}, "base": {"ref": "main"},
                   "mergeable": True}]
    fake.checks = [{"name": "build", "status": "completed", "conclusion": "success"}]
    payload = github_status(GitHubConfig("o", "r"), 7, transport=fake)
    assert payload["pull_request"] == 7
    assert payload["checks"][0]["conclusion"] == "success"


def test_load_proposal_accepts_a_file_and_list_files(tmp_path):
    path = tmp_path / "proposal.json"
    path.write_text(json.dumps({
        "branch": "agent/x", "title": "t", "body": "",
        "files": [{"path": "a.txt", "content": "hello"}]}), encoding="utf-8")
    proposal = load_proposal(str(path))
    assert proposal.files == {"a.txt": "hello"}


def test_cli_publish_dry_run_and_missing_proposal(tmp_path, capsys):
    path = tmp_path / "proposal.json"
    path.write_text(json.dumps({
        "branch": "agent/x", "title": "t", "body": "",
        "files": {"a.txt": "hello"}}), encoding="utf-8")
    assert cli.main(["github", "publish", "--proposal", str(path),
                     "--owner", "o", "--repo", "r", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True

    assert cli.main(["github", "publish", "--proposal",
                     str(tmp_path / "missing.json"), "--owner", "o",
                     "--repo", "r", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_review_extracts_constraints_and_blocks_readiness(monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_GITHUB_TOKEN", "secret-token")
    fake = FakeGitHub()
    fake.pulls = [{"number": 7, "html_url": "https://github.com/o/r/pull/7",
                   "title": "feat", "state": "open", "draft": False,
                   "head": {"sha": "abc"}, "base": {"ref": "main"},
                   "mergeable": True}]
    fake.reviews = [{"id": 1, "state": "CHANGES_REQUESTED", "body": "Please add a test for empty input"}]
    fake.review_comments = [
        {"id": 2, "body": "This must handle the timeout path.",
         "path": "src/f.py", "pull_request_review_id": 1},
        {"id": 3, "body": "Thanks!", "path": "src/f.py", "pull_request_review_id": 1},
    ]
    fake.checks = [{"name": "build", "status": "completed", "conclusion": "success"}]
    payload = github_review(GitHubConfig("o", "r"), 7, transport=fake)
    kinds = {row["kind"] for row in payload["constraints"]}
    assert "test" in kinds and "behavior" in kinds
    assert all(row["severity"] == "blocking" for row in payload["constraints"])
    assert len(payload["constraints"]) == 2  # "Thanks!" is a note, not a task
    assert payload["merge_readiness"]["ready"] is False
    assert payload["merge_readiness"]["requires_human_click"] is True
    assert any("changes" in b for b in payload["merge_readiness"]["blockers"])
    assert any("constraint" in b for b in payload["merge_readiness"]["blockers"])


def test_review_ready_only_when_checks_green_and_no_changes(monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_GITHUB_TOKEN", "secret-token")
    fake = FakeGitHub()
    fake.pulls = [{"number": 7, "html_url": "https://github.com/o/r/pull/7",
                   "title": "feat", "state": "open", "draft": False,
                   "head": {"sha": "abc"}, "base": {"ref": "main"},
                   "mergeable": True}]
    fake.reviews = [{"id": 1, "state": "APPROVED", "body": "Looks good"}]
    fake.review_comments = []
    fake.checks = [{"name": "build", "status": "completed", "conclusion": "success"}]
    payload = github_review(GitHubConfig("o", "r"), 7, transport=fake)
    assert payload["constraints"] == []
    assert payload["merge_readiness"]["ready"] is True
    assert payload["merge_readiness"]["requires_human_click"] is True


def test_review_failed_check_blocks_even_with_approval(monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_GITHUB_TOKEN", "secret-token")
    fake = FakeGitHub()
    fake.pulls = [{"number": 7, "html_url": "https://github.com/o/r/pull/7",
                   "title": "feat", "state": "open", "draft": False,
                   "head": {"sha": "abc"}, "base": {"ref": "main"},
                   "mergeable": True}]
    fake.reviews = [{"id": 1, "state": "APPROVED", "body": ""}]
    fake.checks = [{"name": "test", "status": "completed", "conclusion": "failure"}]
    payload = github_review(GitHubConfig("o", "r"), 7, transport=fake)
    assert payload["checks_state"] == "failure"
    assert payload["merge_readiness"]["ready"] is False


def test_review_resolved_ids_clear_a_blocking_constraint():
    constraints = extract_review_constraints(
        [], [{"id": 2, "body": "must add a test", "path": "a.py"}],
        resolved_ids=["comment:2"])
    assert constraints[0].resolved is True


def test_cli_review_requires_a_token(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("AGENTDESCENT_GITHUB_TOKEN", raising=False)
    code = cli.main(["github", "review", "--pr", "7", "--owner", "o",
                     "--repo", "r", "--json"])
    assert code == 2
    assert "token is not set" in json.loads(capsys.readouterr().out)["error"]

def test_publish_updates_an_existing_branch_with_an_encoded_ref(monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_GITHUB_TOKEN", "secret-token")
    fake = FakeGitHub()
    fake.refs["agent/skill-csv"] = "old-head"
    payload = publish_proposal(
        GitHubConfig("o", "r"), _proposal(), dry_run=False, transport=fake)
    update_calls = [path for method, path, _ in fake.calls
                    if method == "PATCH" and "/git/refs/" in path]
    assert update_calls == ["/repos/o/r/git/refs/heads%2Fagent%2Fskill-csv"]
    assert fake.refs["agent/skill-csv"] == payload["head"]


def _green_checks():
    return [{"name": "build", "status": "completed", "conclusion": "success"}]


def test_a_later_approval_clears_that_reviewers_change_request(monkeypatch):
    # "Please re-review" is this repository's normal flow: a reviewer who asked
    # for changes and then approved it again must stop blocking the packet.
    monkeypatch.setenv("AGENTDESCENT_GITHUB_TOKEN", "secret-token")
    fake = FakeGitHub()
    fake.pulls = [{"number": 7, "html_url": "https://github.com/o/r/pull/7",
                   "title": "feat", "state": "open", "draft": False,
                   "head": {"sha": "abc"}, "base": {"ref": "main"},
                   "mergeable": True}]
    fake.reviews = [
        {"id": 1, "state": "CHANGES_REQUESTED",
         "body": "Please add a test for the empty input",
         "user": {"login": "alice"}, "submitted_at": "2026-11-10T02:00:00Z"},
        {"id": 2, "state": "APPROVED", "body": "Looks good now",
         "user": {"login": "alice"}, "submitted_at": "2026-11-11T02:00:00Z"},
    ]
    fake.review_comments = [
        {"id": 3, "body": "This must handle the timeout path.",
         "path": "src/f.py", "pull_request_review_id": 1},
    ]
    fake.checks = _green_checks()
    payload = github_review(GitHubConfig("o", "r"), 7, transport=fake)
    readiness = payload["merge_readiness"]
    assert readiness["ready"] is True
    assert readiness["blockers"] == []
    assert payload["reviews"]["approved"] == 1
    assert payload["reviews"]["changes_requested"] == 0
    blocking = [row for row in payload["constraints"]
                if row["severity"] == "blocking"]
    assert blocking == []


def test_a_superseded_change_request_stays_a_suggestion(monkeypatch):
    # Only the reviewer's latest review decides; the superseded one is kept as
    # evidence but its constraints no longer block.
    monkeypatch.setenv("AGENTDESCENT_GITHUB_TOKEN", "secret-token")
    fake = FakeGitHub()
    fake.pulls = [{"number": 7, "html_url": "https://github.com/o/r/pull/7",
                   "title": "feat", "state": "open", "draft": False,
                   "head": {"sha": "abc"}, "base": {"ref": "main"},
                   "mergeable": True}]
    fake.reviews = [
        {"id": 1, "state": "CHANGES_REQUESTED",
         "body": "Please add a test for the empty input",
         "user": {"login": "alice"}, "submitted_at": "2026-11-10T02:00:00Z"},
        {"id": 2, "state": "APPROVED", "body": "Looks good now",
         "user": {"login": "alice"}, "submitted_at": "2026-11-11T02:00:00Z"},
    ]
    fake.review_comments = [
        {"id": 4, "body": "This must handle the timeout path.",
         "path": "src/f.py", "pull_request_review_id": 1},
    ]
    fake.checks = _green_checks()
    payload = github_review(GitHubConfig("o", "r"), 7, transport=fake)
    by_text = {row["text"]: row["severity"] for row in payload["constraints"]}
    assert by_text["Please add a test for the empty input"] == "suggestion"
    assert by_text["This must handle the timeout path."] == "suggestion"
    assert payload["merge_readiness"]["ready"] is True
    assert payload["reviews"]["changes_requested"] == 0


def test_another_reviewers_change_request_still_blocks(monkeypatch):
    # Clearing one reviewer's stale request must not clear a different one.
    monkeypatch.setenv("AGENTDESCENT_GITHUB_TOKEN", "secret-token")
    fake = FakeGitHub()
    fake.pulls = [{"number": 7, "html_url": "https://github.com/o/r/pull/7",
                   "title": "feat", "state": "open", "draft": False,
                   "head": {"sha": "abc"}, "base": {"ref": "main"},
                   "mergeable": True}]
    fake.reviews = [
        {"id": 1, "state": "CHANGES_REQUESTED",
         "body": "Please add a test for the empty input",
         "user": {"login": "alice"}, "submitted_at": "2026-11-10T02:00:00Z"},
        {"id": 2, "state": "APPROVED", "body": "Looks good now",
         "user": {"login": "alice"}, "submitted_at": "2026-11-11T02:00:00Z"},
        {"id": 3, "state": "CHANGES_REQUESTED",
         "body": "Please rename the flag",
         "user": {"login": "bob"}, "submitted_at": "2026-11-11T03:00:00Z"},
    ]
    fake.checks = _green_checks()
    payload = github_review(GitHubConfig("o", "r"), 7, transport=fake)
    assert payload["reviews"]["approved"] == 1
    assert payload["reviews"]["changes_requested"] == 1
    assert payload["merge_readiness"]["ready"] is False
    assert "1 reviewer(s) requested changes" in payload["merge_readiness"]["blockers"]
    blocking = {row["text"] for row in payload["constraints"]
                if row["severity"] == "blocking"}
    assert blocking == {"Please rename the flag"}


def test_a_plain_comment_does_not_clear_a_change_request(monkeypatch):
    # GitHub keeps a change request until an approval or a dismissal, so a
    # later COMMENTED review must not read as if the block were lifted.
    monkeypatch.setenv("AGENTDESCENT_GITHUB_TOKEN", "secret-token")
    fake = FakeGitHub()
    fake.pulls = [{"number": 7, "html_url": "https://github.com/o/r/pull/7",
                   "title": "feat", "state": "open", "draft": False,
                   "head": {"sha": "abc"}, "base": {"ref": "main"},
                   "mergeable": True}]
    fake.reviews = [
        {"id": 1, "state": "CHANGES_REQUESTED",
         "body": "Please add a test for the empty input",
         "user": {"login": "alice"}, "submitted_at": "2026-11-10T02:00:00Z"},
        {"id": 2, "state": "COMMENTED", "body": "Please fix the typo in the docstring",
         "user": {"login": "alice"}, "submitted_at": "2026-11-11T02:00:00Z"},
    ]
    fake.checks = _green_checks()
    payload = github_review(GitHubConfig("o", "r"), 7, transport=fake)
    readiness = payload["merge_readiness"]
    assert payload["reviews"]["changes_requested"] == 1
    assert payload["reviews"]["commented"] == 0
    assert readiness["ready"] is False
    assert "1 reviewer(s) requested changes" in readiness["blockers"]
    by_text = {row["text"]: row["severity"] for row in payload["constraints"]}
    assert by_text["Please add a test for the empty input"] == "blocking"
    assert by_text["Please fix the typo in the docstring"] == "suggestion"


def test_a_comment_after_an_approval_keeps_the_approval(monkeypatch):
    # A later COMMENTED review must not degrade the reviewer's approval either.
    monkeypatch.setenv("AGENTDESCENT_GITHUB_TOKEN", "secret-token")
    fake = FakeGitHub()
    fake.pulls = [{"number": 7, "html_url": "https://github.com/o/r/pull/7",
                   "title": "feat", "state": "open", "draft": False,
                   "head": {"sha": "abc"}, "base": {"ref": "main"},
                   "mergeable": True}]
    fake.reviews = [
        {"id": 1, "state": "CHANGES_REQUESTED",
         "body": "Please add a test for the empty input",
         "user": {"login": "alice"}, "submitted_at": "2026-11-10T02:00:00Z"},
        {"id": 2, "state": "APPROVED", "body": "Looks good now",
         "user": {"login": "alice"}, "submitted_at": "2026-11-11T02:00:00Z"},
        {"id": 3, "state": "COMMENTED", "body": "One small nit in the docstring",
         "user": {"login": "alice"}, "submitted_at": "2026-11-11T03:00:00Z"},
    ]
    fake.checks = _green_checks()
    payload = github_review(GitHubConfig("o", "r"), 7, transport=fake)
    readiness = payload["merge_readiness"]
    assert payload["reviews"]["approved"] == 1
    assert payload["reviews"]["changes_requested"] == 0
    assert payload["reviews"]["commented"] == 0
    assert readiness["ready"] is True
    assert readiness["blockers"] == []


def test_a_dismissed_change_request_stops_blocking(monkeypatch):
    # Dismissal is the other way GitHub clears a change request.
    monkeypatch.setenv("AGENTDESCENT_GITHUB_TOKEN", "secret-token")
    fake = FakeGitHub()
    fake.pulls = [{"number": 7, "html_url": "https://github.com/o/r/pull/7",
                   "title": "feat", "state": "open", "draft": False,
                   "head": {"sha": "abc"}, "base": {"ref": "main"},
                   "mergeable": True}]
    fake.reviews = [
        {"id": 1, "state": "CHANGES_REQUESTED",
         "body": "Please add a test for the empty input",
         "user": {"login": "alice"}, "submitted_at": "2026-11-10T02:00:00Z"},
        {"id": 2, "state": "DISMISSED", "body": "",
         "user": {"login": "alice"}, "submitted_at": "2026-11-11T02:00:00Z"},
    ]
    fake.checks = _green_checks()
    payload = github_review(GitHubConfig("o", "r"), 7, transport=fake)
    readiness = payload["merge_readiness"]
    assert payload["reviews"]["changes_requested"] == 0
    assert payload["reviews"]["dismissed"] == 1
    assert readiness["ready"] is True
    by_text = {row["text"]: row["severity"] for row in payload["constraints"]}
    assert by_text["Please add a test for the empty input"] == "suggestion"
