"""Durable records alongside (not inside) the experiment's Git ledger."""

from __future__ import annotations

import dataclasses
import difflib
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from datetime import datetime, timezone
from typing import Any, Mapping, Optional
import uuid

from agentdescent.filetree import parse_tree, safe_relpath


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json_default(value):
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"cannot record {type(value).__name__}")


class RunRecords:
    """Full proposals, gate outcomes and snapshots with a retained failure flag.

    The engine intentionally absorbs callback exceptions. ``assert_healthy``
    must therefore run before reporting success or applying the final skill.
    ``root`` is the run directory; give ``evolve`` its ``root / 'ledger'``.
    """

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._failures = []
        self._round = 0

    def _path(self, relative_name: str) -> Path:
        path = self.root / safe_relpath(str(relative_name))
        if self.root not in path.resolve().parents:
            raise ValueError("record path escapes the run directory")
        return path

    def _failed(self, exc: Exception) -> None:
        with self._lock:
            self._failures.append(f"{type(exc).__name__}: {exc}")

    def assert_healthy(self) -> None:
        with self._lock:
            if self._failures:
                raise RuntimeError("RSI records are incomplete: " + "; ".join(self._failures))

    def write_text(self, relative_name: str, text: str) -> Path:
        """Atomically write exact UTF-8 bytes, preserving CRLF if present."""
        temporary = None
        try:
            path = self._path(relative_name)
            with self._lock:
                path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
                    temporary = stream.name
                    stream.write(text.encode("utf-8"))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
                temporary = None
            return path
        except Exception as exc:
            self._failed(exc)
            raise
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)

    def write_json(self, relative_name: str, payload: Any) -> Path:
        try:
            text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True,
                              allow_nan=False, default=_json_default) + "\n"
        except Exception as exc:
            self._failed(exc)
            raise
        return self.write_text(relative_name, text)

    def append(self, relative_name: str, payload: Mapping[str, Any]) -> None:
        try:
            row = {"recorded_at": datetime.now(timezone.utc).isoformat(), **dict(payload)}
            data = (json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False,
                               default=_json_default) + "\n").encode("utf-8")
            path = self._path(relative_name)
            with self._lock:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("ab") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
        except Exception as exc:
            self._failed(exc)
            raise

    def snapshot(self, content: Optional[str]) -> dict:
        if content is None:
            return {"sha256": None, "file": None}
        digest = sha256_text(content)
        relative = f"snapshots/{digest}.md"
        self.write_text(relative, content)
        return {"sha256": digest, "file": relative}

    def change(self, before: Optional[str], after: Optional[str]) -> dict:
        old, new = self.snapshot(before), self.snapshot(after)
        lines = difflib.unified_diff((before or "").splitlines(keepends=True),
                                     (after or "").splitlines(keepends=True),
                                     fromfile="a/SKILL.md", tofile="b/SKILL.md")
        patch = "".join(line if line.endswith("\n") else
                        line + "\n\\ No newline at end of file\n" for line in lines)
        relative = f"diffs/{sha256_text(patch)}.patch"
        self.write_text(relative, patch)
        return {"before_sha256": old["sha256"], "after_sha256": new["sha256"],
                "before_file": old["file"], "after_file": new["file"],
                "patch_file": relative, "unified_diff": patch}

    def wrap_propose(self, propose):
        """Also record no-op responses and failures before ``to_diff`` is called."""
        def recorded(rendered, task, output, reward):
            before = self.snapshot(parse_tree(rendered).get("SKILL.md"))
            event = {"proposal_id": uuid.uuid4().hex, "task_id": task.id,
                     "task_prompt": task.prompt, "reward": reward, "output": output,
                     "before": before}
            try:
                proposal = propose(rendered, task, output, reward)
            except Exception as exc:
                # Provider exception text may echo HTTP headers or credentials.
                self.append("proposals.jsonl", {**event, "outcome": "error",
                                               "error": type(exc).__name__})
                raise
            self.append("proposals.jsonl", {**event, "raw_proposal": proposal,
                                           "outcome": "proposed" if proposal else "no-proposal"})
            return proposal
        return recorded

    def on_reports(self, reports) -> None:
        """Keep every merge report; no truncation and no rejected-only filter."""
        try:
            for report in reports:
                row = dataclasses.asdict(report)
                diff = report.candidate_diff or report.accepted
                if diff is not None:
                    text = (diff.ops or {}).get("SKILL.md")
                    row["candidate_snapshot"] = self.snapshot(text)
                self.append("reports.jsonl", {"round": self._round, **row})
        except Exception as exc:
            self._failed(exc)
            raise

    def on_round(self, info) -> None:
        try:
            self.append("rounds.jsonl", dataclasses.asdict(info))
            self._round = info.round + 1
        except Exception as exc:
            self._failed(exc)
            raise

    def link_ledger(self, repo_path: Path, artifact_id: str) -> list:
        """Map accepted versions to actual Git SHAs and full committed patches.

        ``MergeReport`` contains an artifact version, not a commit SHA. Reading
        that version from each commit avoids incorrectly assigning the last
        HEAD to every acceptance in a multi-round run.
        """
        try:
            if safe_relpath(artifact_id) != artifact_id or "/" in artifact_id:
                raise ValueError("artifact_id must be a filename")
            repo_path = Path(repo_path)

            def git(*args):
                return subprocess.run(["git", "-C", str(repo_path), *args], check=True,
                                      capture_output=True, text=True).stdout

            artifact_path = f"artifacts/{artifact_id}.json"
            shas = git("log", "--reverse", "--format=%H", "dev", "--", artifact_path).splitlines()
            history, before = [], None
            for sha in shas:
                artifact = json.loads(git("show", f"{sha}:{artifact_path}"))
                serialized = artifact["state"]
                # EvolvingArtifact.serialize stores its mapping under 'state'.
                state = serialized.get("state", serialized)
                text = state["SKILL.md"]
                history.append({"commit": sha, "version": artifact["version"],
                                "artifact_id": artifact_id,
                                "message": git("show", "-s", "--format=%B", sha).strip(),
                                "change": self.change(before, text)})
                before = text
            self.write_json("ledger_history.json", history)
            if (self.root / "reports.jsonl").exists():
                versions = {entry["version"]: entry["commit"] for entry in history}
                for line in (self.root / "reports.jsonl").read_text(encoding="utf-8").splitlines():
                    report = json.loads(line)
                    version = report.get("committed_version")
                    if version is not None:
                        if version not in versions:
                            raise RuntimeError(f"accepted version {version} has no ledger commit")
                        self.append("accepted.jsonl", {"round": report["round"],
                                    "artifact_id": artifact_id, "version": version,
                                    "commit": versions[version], "diff": report["accepted"],
                                    "prob_improve": report["prob_improve"]})
            return history
        except Exception as exc:
            self._failed(exc)
            raise
