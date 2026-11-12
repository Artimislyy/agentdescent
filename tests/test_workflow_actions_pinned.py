"""Workflow actions must be pinned to a commit, not to a moving ref.

Every ``uses:`` in ``.github/workflows/*.yml`` is a supply-chain input: ``@v4``
and ``@release/v1`` are mutable refs, so whoever can move the tag or branch
decides what our CI executes -- with ``id-token: write`` on the publish jobs,
that includes the OIDC token and the PyPI/npm upload.  Pinning to a 40-hex
commit SHA freezes the code that runs and leaves the update as an explicit,
reviewable diff; the version stays readable in a trailing ``# vX.Y.Z`` comment.

Offline: reads the workflow files in the checkout, no network, no fixtures.
Local ``./path`` composite actions are exempt -- they are this repo, not a
remote ref that can move.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))

USES = re.compile(r"^[ \t]*(?:-[ \t]*)?uses:[ \t]*[\"']?([^\"'#\s]+)")
COMMIT = re.compile(r"[0-9a-f]{40}")


def _uses_lines(path):
    """(line number, ref) for every ``uses:`` in one workflow file."""
    out = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        match = USES.match(line)
        if match:
            out.append((number, match.group(1)))
    return out


def _floating(ref):
    """True when ``ref`` is a remote action pinned only by a moving ref."""
    if ref.startswith("./"):
        return False
    _, _, version = ref.partition("@")
    return not COMMIT.fullmatch(version)


def test_workflows_exist():
    assert WORKFLOWS, f"no workflow files found under {ROOT / '.github' / 'workflows'}"


def test_every_workflow_action_is_pinned_to_a_commit_sha():
    floating = [
        f".github/workflows/{path.name}:{number}: {ref}"
        for path in WORKFLOWS
        for number, ref in _uses_lines(path)
        if _floating(ref)
    ]

    assert not floating, (
        "every `uses:` must be pinned to a full 40-hex commit SHA "
        "(keep the version in a trailing `# vX.Y.Z` comment); floating refs:\n  "
        + "\n  ".join(floating)
    )


def test_every_workflow_file_parses_as_yaml():
    for path in WORKFLOWS:
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(config, dict), f"{path.name} is not a YAML mapping"
        assert "jobs" in config, f"{path.name} has no jobs:"
