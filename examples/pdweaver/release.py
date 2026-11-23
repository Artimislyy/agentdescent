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

from .harness import (SKILL_KEY, SKILL_NAME, HARNESS_FILES, LEGACY_HARNESS_FILES,
                      PROMPT_DIR, validate_skill, source_paths, read_text, safe_relpath)
from .records import RunRecords, harness_sha256
from .selection import DEFAULT_RULE, compare_default_trials, compare_trials
from .trajectory import analysis_paths


def _git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def _harness_keys(manifest, *, candidate=False):
    version = manifest.get("schema_version", 1)
    if version == 5:
        keys = list(manifest["candidate_files"] if candidate else manifest["source"]["files"])
        if not keys or len(keys) != len(set(keys)) or any(safe_relpath(key) != key for key in keys):
            raise ValueError("invalid skills file manifest")
        return tuple(keys)
    if version not in (1, 2, 3, 4):
        raise ValueError("unsupported experiment manifest version")
    return {1: (SKILL_KEY,), 2: LEGACY_HARNESS_FILES, 3: HARNESS_FILES, 4: HARNESS_FILES}[version]


def seal_evidence(root):
    """Digest durable evidence outside the mutable Git index/workspaces."""
    root = Path(root)
    files = {}
    excluded = {"ledger", "demo-workspaces", "reflector-runtime"}
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
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    required = {"manifest.json", "final_evaluation.json", "ledger_history.json"}
    required.update(f"{role}/{key}" for role in ("candidate", "baseline")
                    for key in _harness_keys(manifest, candidate=role == "candidate"))
    if manifest.get("schema_version", 1) >= 2:
        required.add("reflection_prompt.md")
    required.update("reflection_skill/" + key for key in manifest.get("source", {}).get("analysis", {}))
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
                    or output["phase"] != "test_" + role or output.get("harness_sha256", output.get("skill_sha256")) != digest):
                raise ValueError("test row does not match its recorded trial and skill")
            scores[role].append(_score(output["score"]))
    baseline = sum(scores["baseline"]) / len(rows)
    candidate = sum(scores["candidate"]) / len(rows)
    native = manifest.get("schema_version", 1) >= 4
    before, after = [r["baseline"] for r in rows], [r["candidate"] for r in rows]
    if native:
        if assessment.get("rule") != DEFAULT_RULE:
            raise ValueError("test acceptance policy does not match the experiment")
        comparison = compare_default_trials(before, after)
    else:
        # Previously sealed runs must retain their original adoption rule.
        gain = assessment["min_gain"]
        if isinstance(gain, bool) or not isinstance(gain, (int, float)) or not math.isfinite(gain) or gain < 0:
            raise ValueError("invalid minimum test gain")
        comparison = compare_trials(before, after, min_gain=gain)
    for key in ("baseline_passed_seconds", "candidate_passed_seconds", "speed_improved",
                "no_task_regression", "p_improve"):
        if key in assessment and assessment[key] != comparison[key]:
            raise ValueError("recorded test decision does not match the sealed trials")
    if (not math.isclose(_score(assessment["baseline_mean"]), baseline, abs_tol=1e-12)
            or not math.isclose(_score(assessment["candidate_mean"]), candidate, abs_tol=1e-12)
            or not comparison["passed"] or assessment["passed"] is not True
            or (not native and assessment["no_task_regression"] is not True)):
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
            or harness_sha256(state) != candidate_hash):
        raise ValueError("recorded Ledger commit has a different candidate")
    return commit


def _atomic_bytes(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
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
    keys = _harness_keys(manifest, candidate=True)
    candidate = {key: read_text(root / "candidate" / key) for key in keys}
    before = {key: read_text(root / "baseline" / key) for key in _harness_keys(manifest)}
    candidate_hash, baseline_hash = harness_sha256(candidate), harness_sha256(before)
    if candidate_hash != assessment["candidate_sha256"] or baseline_hash != manifest["source"]["sha256"]:
        raise ValueError("candidate/baseline does not match the evaluated version")
    if validate_skill(candidate, required=tuple(before)):
        raise ValueError("invalid candidate harness")
    _verify_test_gate(root, manifest, assessment, baseline_hash, candidate_hash)
    ledger_commit = _verified_ledger_commit(root, candidate_hash)
    repo = Path(manifest["pdweaver_repo"]).resolve()
    paths = source_paths(repo / "skills" / SKILL_NAME / SKILL_KEY, keys=keys)
    targets = {key: paths[key] for key in keys}
    relative = {key: str(path.relative_to(repo)) for key, path in targets.items()}
    if Path(_git(repo, "rev-parse", "--show-toplevel")).resolve() != repo:
        raise ValueError("native harness repository mapping changed")
    for key, target in targets.items():
        expected = (manifest["source"]["files"].get(key, {"path": str(target)})["path"] if "files" in manifest["source"]
                    else manifest["source"]["path"])
        if target.is_symlink() or repo not in target.resolve().parents or target.resolve() != Path(expected):
            raise ValueError("native harness source mapping changed")

    def committed_state(commit):
        return {key: subprocess.check_output(["git", "-C", str(repo), "show", commit + ":" + rel]).decode("utf-8")
                for key, rel in relative.items()}

    def write_state(state):
        for key in set(targets) - set(state):
            targets[key].unlink(missing_ok=True)
        for key, content in state.items():
            _atomic_bytes(targets[key], content.encode("utf-8"))

    baseline_files = {relative[key]: text.encode("utf-8") for key, text in before.items()}
    reflection = manifest["source"].get("reflection") if manifest.get("schema_version", 1) < 5 else None
    if reflection:
        path = repo / "skills" / PROMPT_DIR / "reflection_prompt.md"
        text = read_text(path)
        if (path.resolve() != Path(reflection["path"]) or repo not in path.resolve().parents
                or hashlib.sha256(text.encode("utf-8")).hexdigest() != reflection["sha256"]
                or text != read_text(root / "reflection_prompt.md")):
            raise ValueError("reflection prompt changed since evaluation")
        baseline_files[str(path.relative_to(repo))] = text.encode("utf-8")
    analysis = manifest["source"].get("analysis") if manifest.get("schema_version", 1) < 5 else None
    if analysis:
        paths = analysis_paths(repo)
        if set(paths) != set(analysis):
            raise ValueError("analysis skill files changed since evaluation")
        for key, path in paths.items():
            text = read_text(path)
            if (path.resolve() != Path(analysis[key]["path"]) or repo not in path.resolve().parents
                    or hashlib.sha256(text.encode("utf-8")).hexdigest() != analysis[key]["sha256"]
                    or text != read_text(root / "reflection_skill" / key)):
                raise ValueError("analysis skill changed since evaluation")
            baseline_files[str(path.relative_to(repo))] = text.encode("utf-8")

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
        if committed_state(commit) != candidate:
            raise ValueError("existing adoption commit has a different skill")
        adopted = json.loads(_git(repo, "show", "{}:{}".format(commit, adoption_path)))
        if (not _matches_receipt(adopted, run_id, candidate_hash, evidence_hash)
                or adopted.get("ledger_head") != ledger_commit
                or adopted.get("source_sha256") != baseline_hash):
            raise ValueError("existing adoption receipt belongs to different evidence")
        receipt = {**adopted, "status": "committed", "pdweaver_commit": commit,
                   "activation": "not_checked", "recovered": True,
                   "working_harness_matches": all(read_text(targets[key]) == candidate[key] for key in keys)}
        records.write_json("adoption.json", receipt)
        return receipt
    expected_head = manifest["source"]["git_head"]
    baseline_commits = _git(repo, "log", "--all", "--format=%H",
                            "--grep=^PDWeaver-RSI-Baseline: {}$".format(run_id)).splitlines()
    if baseline_commits:
        expected_head = baseline_commits[0]
        saved = {rel: subprocess.check_output(["git", "-C", str(repo), "show", expected_head + ":" + rel])
                 for rel in baseline_files}
        if saved != baseline_files or _git(repo, "rev-parse", expected_head + "^") != manifest["source"]["git_head"]:
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
    allowed = set(baseline_files) | {adoption_path}
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
    if manifest.get("schema_version") == 5 and not set(source_paths(repo / "skills" / SKILL_NAME / SKILL_KEY)) <= set(keys):
        raise ValueError("skills files changed since evaluation")
    current = {key: read_text(target) for key, target in targets.items() if target.exists()}
    if any(current.get(key) != before.get(key) and (not own_pending or current.get(key) != candidate[key]) for key in keys):
        raise ValueError("PDWeaver advanced since evaluation; revalidate before application")
    # A killed process can leave our candidate and index updates behind. Undo
    # only files whose content and pending receipt prove they belong to this run.
    if own_pending:
        for path in staged:
            indexed = subprocess.check_output(["git", "-C", str(repo), "show", ":" + path])
            if path in relative.values():
                key = next(key for key, rel in relative.items() if rel == path)
                if indexed not in (before.get(key, "").encode("utf-8"), candidate[key].encode("utf-8")):
                    raise ValueError("staged skill contains unrelated edits")
            elif path in baseline_files:
                if indexed != baseline_files[path]:
                    raise ValueError("staged reflection prompt contains unrelated edits")
            elif not _matches_receipt(json.loads(indexed), run_id, candidate_hash, evidence_hash):
                raise ValueError("staged adoption record contains unrelated edits")
        if staged:
            _git(repo, "reset", "--", *staged)
        if current != before:
            write_state(before)
        if adoption_file.exists():
            adoption_file.unlink()
    changed = _git(repo, "diff", "HEAD", "--name-only").splitlines()
    records.write_json("adoption-pending.json", {"run_id": run_id, "source_head": expected_head,
                       "candidate_sha256": candidate_hash, "evidence_manifest_sha256": evidence_hash})
    # An untracked/modified native seed still needs a real rollback target.
    needs_baseline = any(not _git(repo, "ls-files", "--", rel) or rel in changed for rel in baseline_files)
    if needs_baseline:
        try:
            _git(repo, "add", "--", *baseline_files)
            _git(repo, "commit", "--only", "-m", "chore(pdweaver): record native RSI harness baseline\n\nPDWeaver-RSI-Baseline: " + run_id,
                 "--", *baseline_files)
        except Exception:
            if _git(repo, "rev-parse", "HEAD") == expected_head:
                _git(repo, "reset", "--", *baseline_files)
            raise
        expected_head = _git(repo, "rev-parse", "HEAD")
    records.write_json("adoption-pending.json", {"run_id": run_id, "source_head": expected_head,
                       "candidate_sha256": candidate_hash, "evidence_manifest_sha256": evidence_hash})
    adoption = {"schema_version": 1, "run_id": run_id, "source_commit": manifest["source"]["git_head"],
                "parent_commit": expected_head, "source_sha256": manifest["source"]["sha256"],
                "candidate_sha256": candidate_hash, "harness_paths": relative,
                "baseline_mean": assessment["baseline_mean"], "candidate_mean": assessment["candidate_mean"],
                "baseline_passed_seconds": assessment.get("baseline_passed_seconds"),
                "candidate_passed_seconds": assessment.get("candidate_passed_seconds"),
                "evidence_directory": str(root), "evidence_manifest_sha256": evidence_hash,
                "ledger_head": ledger_commit}
    adoption_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        write_state(candidate)
        _atomic_bytes(adoption_file, (json.dumps(adoption, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        _git(repo, "add", "--", *relative.values(), adoption_path)
        _git(repo, "commit", "--only", "-m", "feat(pdweaver): adopt validated ECO harness\n\nPDWeaver-RSI-Run: " + run_id,
             "--", *relative.values(), adoption_path)
    except Exception:
        # Only restore our own uncommitted files; preserve any successful Git history.
        if _git(repo, "rev-parse", "HEAD") == expected_head:
            _git(repo, "reset", "--", *relative.values(), adoption_path)
            write_state(before)
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
