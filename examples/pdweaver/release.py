"""Explicit final skill application, Git history and recoverable adoption receipts."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import uuid
from pathlib import Path

from .harness import SKILL_KEY, SKILL_NAME, validate_skill
from .records import RunRecords
from .selection import compare_trials


def _git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def seal_evidence(root):
    """Digest durable evidence outside the mutable Git index/workspaces."""
    root = Path(root)
    files = {}
    excluded = {"ledger", "demo-workspaces"}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if rel.parts[0] in excluded or rel.name in {"evidence-manifest.json", "adoption.json", "adoption-pending.json"}:
            continue
        if path.is_file():
            files[rel.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    RunRecords(root).write_json("evidence-manifest.json", {"files": files})


def _verify_evidence(root):
    manifest_path = root / "evidence-manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = {"manifest.json", "final_evaluation.json", "candidate/SKILL.md",
                "baseline/SKILL.md", "ledger_history.json"}
    if not required <= set(data["files"]):
        raise ValueError("incomplete evidence manifest")
    for relative, expected in data["files"].items():
        path = root / relative
        if path.is_symlink() or root not in path.resolve().parents:
            raise ValueError("evidence escaped the run directory")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("evidence changed: {}".format(relative))
    return hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def _score(value):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not 0 <= value <= 1):
        raise ValueError("invalid test score")
    return float(value)


def _verify_test_gate(root, manifest, assessment, baseline_hash, candidate_hash):
    """Recompute the decision and bind every test row to its sealed trial output."""
    if (manifest["plan"]["offline"] is not False or assessment["offline"] is not False
            or assessment["adoption_eligible"] is not True):
        raise ValueError("only an independently evaluated real improvement may be applied")
    if baseline_hash == candidate_hash or assessment["baseline_sha256"] != baseline_hash:
        raise ValueError("baseline does not match the evaluated version, or candidate is unchanged")
    split = manifest["split"]
    expected = split["test"]
    if (not expected or len(set(expected)) != len(expected)
            or set(expected) & set(split["train"] + split["val"])):
        raise ValueError("final test tasks must be nonempty, unique and excluded from search")
    rows = assessment["rows"]
    if [row["task_id"] for row in rows] != expected:
        raise ValueError("final test rows do not match the frozen split")
    sealed = json.loads((root / "evidence-manifest.json").read_text(encoding="utf-8"))["files"]
    scores = {"baseline": [], "candidate": []}
    seen_trials = set()
    for row in rows:
        for role, digest in (("baseline", baseline_hash), ("candidate", candidate_hash)):
            output = row[role]
            trial_id = output["trial_id"]
            if not isinstance(trial_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", trial_id):
                raise ValueError("invalid test trial id")
            if trial_id in seen_trials:
                raise ValueError("test evaluations must use distinct fresh trials")
            seen_trials.add(trial_id)
            relative = "trials/{}/output.json".format(trial_id)
            if relative not in sealed:
                raise ValueError("test trial output was not sealed")
            saved = json.loads((root / relative).read_text(encoding="utf-8"))
            if (saved != output or output["task_id"] != row["task_id"]
                    or output["phase"] != "test_" + role or output["skill_sha256"] != digest):
                raise ValueError("test row does not match its recorded trial and skill")
            scores[role].append(_score(output["score"]))
    baseline = sum(scores["baseline"]) / len(rows)
    candidate = sum(scores["candidate"]) / len(rows)
    gain = assessment["min_gain"]
    if isinstance(gain, bool) or not isinstance(gain, (int, float)) or not math.isfinite(gain) or gain < 0:
        raise ValueError("invalid minimum test gain")
    comparison = compare_trials([r["baseline"] for r in rows], [r["candidate"] for r in rows], min_gain=gain)
    for key in ("baseline_passed_seconds", "candidate_passed_seconds", "speed_improved"):
        if key in assessment and assessment[key] != comparison[key]:
            raise ValueError("recorded test timing does not match the sealed trials")
    if (not math.isclose(_score(assessment["baseline_mean"]), baseline, abs_tol=1e-12)
            or not math.isclose(_score(assessment["candidate_mean"]), candidate, abs_tol=1e-12)
            or not comparison["passed"]
            or assessment["passed"] is not True or assessment["no_task_regression"] is not True):
        raise ValueError("recorded test scores do not satisfy the adoption rule")


def _verified_ledger_commit(root, candidate_hash):
    history = json.loads((root / "ledger_history.json").read_text(encoding="utf-8"))
    if not history:
        raise ValueError("no recorded Ledger history")
    entry = history[-1]
    commit = entry["commit"]
    artifact = entry["artifact_id"]
    if (not re.fullmatch(r"[a-f0-9]{40,64}", commit)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+", artifact)
            or entry["change"]["after_sha256"] != candidate_hash):
        raise ValueError("candidate does not match the sealed Ledger history")
    payload = json.loads(_git(root / "ledger", "show", "{}:artifacts/{}.json".format(commit, artifact)))
    state = payload["state"].get("state", payload["state"])
    if (payload["version"] != entry["version"]
            or hashlib.sha256(state[SKILL_KEY].encode("utf-8")).hexdigest() != candidate_hash):
        raise ValueError("recorded Ledger commit has a different candidate")
    return commit


def _atomic_bytes(path, content):
    temporary = path.with_name(".{}.{}.tmp".format(path.name, uuid.uuid4().hex))
    try:
        temporary.write_bytes(content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _matches_receipt(payload, run_id, candidate_hash, evidence_hash):
    return (payload.get("run_id") == run_id
            and payload.get("candidate_sha256") == candidate_hash
            and payload.get("evidence_manifest_sha256") == evidence_hash)


def apply_run(run_dir):
    """Apply only a sealed real experiment; unrelated staged changes are refused."""
    root = Path(run_dir).resolve()
    evidence_hash = _verify_evidence(root)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assessment = json.loads((root / "final_evaluation.json").read_text(encoding="utf-8"))
    candidate = (root / "candidate" / SKILL_KEY).read_bytes()
    before = (root / "baseline" / SKILL_KEY).read_bytes()
    candidate_hash = hashlib.sha256(candidate).hexdigest()
    if candidate_hash != assessment["candidate_sha256"] or hashlib.sha256(before).hexdigest() != manifest["source"]["sha256"]:
        raise ValueError("candidate/baseline does not match the evaluated version")
    if validate_skill({SKILL_KEY: candidate.decode("utf-8")}):
        raise ValueError("invalid candidate skill")
    _verify_test_gate(root, manifest, assessment, hashlib.sha256(before).hexdigest(), candidate_hash)
    ledger_commit = _verified_ledger_commit(root, candidate_hash)
    repo = Path(manifest["pdweaver_repo"]).resolve()
    relative = "skills/{}/{}".format(SKILL_NAME, SKILL_KEY)
    target = repo / relative
    if (target.is_symlink() or repo not in target.resolve().parents
            or target.resolve() != Path(manifest["source"]["path"])
            or Path(_git(repo, "rev-parse", "--show-toplevel")).resolve() != repo):
        raise ValueError("native skill source mapping changed")
    run_id = manifest["run_id"]
    # Only our generated run ids may become paths or Git grep expressions.
    if not run_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in run_id):
        raise ValueError("invalid run id")
    records = RunRecords(root)
    adoption_path = "rsi/adoptions/{}.json".format(run_id)
    adoption_file = repo / adoption_path
    if repo not in adoption_file.resolve().parents:
        raise ValueError("adoption record escaped the PDWeaver repository")
    existing = _git(repo, "log", "--all", "--format=%H", "--grep=^PDWeaver-RSI-Run: {}$".format(run_id)).splitlines()
    if existing:
        commit = existing[0]
        saved = subprocess.check_output(["git", "-C", str(repo), "show", "{}:{}".format(commit, relative)])
        if hashlib.sha256(saved).hexdigest() != candidate_hash:
            raise ValueError("existing adoption commit has a different skill")
        adopted = json.loads(_git(repo, "show", "{}:{}".format(commit, adoption_path)))
        if (not _matches_receipt(adopted, run_id, candidate_hash, evidence_hash)
                or adopted.get("ledger_head") != ledger_commit
                or adopted.get("source_sha256") != hashlib.sha256(before).hexdigest()):
            raise ValueError("existing adoption receipt belongs to different evidence")
        receipt = {**adopted, "status": "committed", "pdweaver_commit": commit,
                   "activation": "not_checked", "recovered": True,
                   "working_skill_matches": target.read_bytes() == candidate}
        records.write_json("adoption.json", receipt)
        return receipt
    expected_head = manifest["source"]["git_head"]
    baseline_commits = _git(repo, "log", "--all", "--format=%H",
                            "--grep=^PDWeaver-RSI-Baseline: {}$".format(run_id)).splitlines()
    if baseline_commits:
        expected_head = baseline_commits[0]
        saved = subprocess.check_output(["git", "-C", str(repo), "show", "{}:{}".format(expected_head, relative)])
        if saved != before or _git(repo, "rev-parse", expected_head + "^") != manifest["source"]["git_head"]:
            raise ValueError("baseline commit does not match the evaluated source")
    if _git(repo, "rev-parse", "HEAD") != expected_head:
        raise ValueError("PDWeaver advanced since evaluation; revalidate before application")
    pending_path = root / "adoption-pending.json"
    pending = json.loads(pending_path.read_text(encoding="utf-8")) if pending_path.exists() else None
    own_pending = (pending is not None and _matches_receipt(pending, run_id, candidate_hash, evidence_hash)
                   and pending.get("source_head") in {expected_head, manifest["source"]["git_head"]})
    if pending is not None and not own_pending:
        raise ValueError("pending adoption belongs to different evidence")
    staged = _git(repo, "diff", "--cached", "--name-only").splitlines()
    allowed = {relative, adoption_path}
    if staged and (not own_pending or not set(staged) <= allowed):
        raise ValueError("existing staged changes: finish or unstage them before explicit application")
    changed = _git(repo, "diff", "HEAD", "--name-only").splitlines()
    if any(path not in allowed for path in changed):
        raise ValueError("unrelated PDWeaver code changed since evaluation")
    if adoption_file.exists():
        prior = json.loads(adoption_file.read_text(encoding="utf-8"))
        if (not own_pending or adoption_file.is_symlink()
                or not _matches_receipt(prior, run_id, candidate_hash, evidence_hash)
                or _git(repo, "ls-tree", "--name-only", "HEAD", "--", adoption_path)):
            raise ValueError("adoption record path already occupied")
    current = target.read_bytes()
    if current != before and (not own_pending or current != candidate):
        raise ValueError("PDWeaver advanced since evaluation; revalidate before application")
    # A killed process can leave our candidate and index updates behind. Undo
    # only files whose content and pending receipt prove they belong to this run.
    if own_pending:
        for path in staged:
            indexed = subprocess.check_output(["git", "-C", str(repo), "show", ":" + path])
            if path == relative:
                if indexed not in (before, candidate):
                    raise ValueError("staged skill contains unrelated edits")
            elif not _matches_receipt(json.loads(indexed), run_id, candidate_hash, evidence_hash):
                raise ValueError("staged adoption record contains unrelated edits")
        if staged:
            _git(repo, "reset", "--", *staged)
        if current != before:
            _atomic_bytes(target, before)
        if adoption_file.exists():
            adoption_file.unlink()
    changed = _git(repo, "diff", "HEAD", "--name-only").splitlines()
    records.write_json("adoption-pending.json", {"run_id": run_id, "source_head": expected_head,
                       "candidate_sha256": candidate_hash, "evidence_manifest_sha256": evidence_hash})
    # An untracked/modified native seed still needs a real rollback target.
    tracked = bool(_git(repo, "ls-files", "--", relative))
    if not tracked or relative in changed:
        try:
            _git(repo, "add", "--", relative)
            _git(repo, "commit", "--only", "-m", "chore(pdweaver): record native RSI skill baseline\n\nPDWeaver-RSI-Baseline: " + run_id,
                 "--", relative)
        except Exception:
            if _git(repo, "rev-parse", "HEAD") == expected_head:
                _git(repo, "reset", "--", relative)
            raise
        expected_head = _git(repo, "rev-parse", "HEAD")
    records.write_json("adoption-pending.json", {"run_id": run_id, "source_head": expected_head,
                       "candidate_sha256": candidate_hash, "evidence_manifest_sha256": evidence_hash})
    adoption = {"schema_version": 1, "run_id": run_id, "source_commit": manifest["source"]["git_head"],
                "parent_commit": expected_head, "source_sha256": manifest["source"]["sha256"],
                "candidate_sha256": candidate_hash, "skill_path": relative,
                "baseline_mean": assessment["baseline_mean"], "candidate_mean": assessment["candidate_mean"],
                "baseline_passed_seconds": assessment.get("baseline_passed_seconds"),
                "candidate_passed_seconds": assessment.get("candidate_passed_seconds"),
                "evidence_directory": str(root), "evidence_manifest_sha256": evidence_hash,
                "ledger_head": ledger_commit}
    adoption_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        _atomic_bytes(target, candidate)
        _atomic_bytes(adoption_file, (json.dumps(adoption, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        _git(repo, "add", "--", relative, adoption_path)
        _git(repo, "commit", "--only", "-m", "feat(pdweaver): adopt validated ECO skill\n\nPDWeaver-RSI-Run: " + run_id,
             "--", relative, adoption_path)
    except Exception:
        # Only restore our own uncommitted files; preserve any successful Git history.
        if _git(repo, "rev-parse", "HEAD") == expected_head:
            _git(repo, "reset", "--", relative, adoption_path)
            _atomic_bytes(target, before)
            adoption_file.unlink(missing_ok=True)
        raise
    receipt = {**adoption, "status": "committed", "pdweaver_commit": _git(repo, "rev-parse", "HEAD"),
               "activation": "not_checked"}
    records.write_json("adoption.json", receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(apply_run(args.run), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
