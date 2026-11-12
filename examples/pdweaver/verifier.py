"""Fresh-process adapter for the archive's explicit Innovus Tcl protocol.

The site owns isolation of untrusted repair.tcl and the private evaluator.
This adapter preserves the selected verifier's semantics; it does not add a
logic-equivalence proof to older verifiers that do not implement one.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import signal
import subprocess
from pathlib import Path
from typing import Any, Dict, Sequence

from agentdescent.evolution import Task
from agentdescent.integrations import provider_key_names

from .dataset import assert_frozen_assets


_METRICS = {
    "setup_wns_ps", "setup_tns_ps", "hold_wns_ps", "hold_tns_ps",
    "max_transition", "max_capacitance", "max_fanout", "max_fanout_delta",
    "drc_clean", "connectivity_clean", "placement_violations",
}
_CHECKS = {"timing", "setup", "hold", "drv", "physical", "drc",
           "connectivity", "placement", "logic", "logic_guard", "constraints"}


def _feedback(report: Dict[str, Any]) -> str:
    """Only allow known numeric metrics and Boolean gates into reflection."""
    safe = {"status": report["status"]}
    for key in ("initial_metrics", "final_metrics", "checks"):
        values = report.get(key)
        if not isinstance(values, dict):
            continue
        allowed = _CHECKS if key == "checks" else _METRICS
        selected = {}
        for name, value in values.items():
            if name not in allowed:
                continue
            if isinstance(value, bool):
                selected[name] = value
            elif key != "checks" and isinstance(value, (int, float)) and math.isfinite(value):
                selected[name] = value
        if selected:
            safe[key] = selected
    return json.dumps(safe, sort_keys=True, ensure_ascii=False)


def verify_submission(task: Task, submission: Path, evidence_dir: Path, *,
                      innovus: str = "innovus", timeout: float = 600,
                      secret_env: Sequence[str] = ()) -> Dict[str, Any]:
    """Return PASS/FAIL scores, or score=None for infrastructure uncertainty.

    Missing repair.tcl is a solver failure (score=0). Missing/malformed private
    reports, EXECUTION_ERROR, and timeouts are not valid score-zero samples.
    Raw reports and logs stay in evidence_dir; feedback excludes their text.
    Model credential variables are removed from the evaluator's environment;
    secret_env adds site-specific credential names without removing licenses.
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Verifier timeout must be finite and positive")
    if task.meta.get("verifier") != "innovus_tcl":
        raise ValueError("Unsupported verifier protocol")
    submission, evidence_dir = Path(submission), Path(evidence_dir).resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    result_path, log_path = evidence_dir / "result.json", evidence_dir / "innovus.log"
    copied_submission = evidence_dir / "submission.tcl"
    if any(path.exists() or path.is_symlink() for path in (result_path, log_path, copied_submission)):
        raise ValueError("Verifier evidence paths must be fresh; refusing stale results")
    result = {"status": "INFRA_ERROR", "score": None, "feedback": "",
              "result_path": str(result_path), "log_path": str(log_path),
              "exit_code": None, "submission_sha256": None}
    try:
        assert_frozen_assets(task)
    except (OSError, ValueError):
        result["feedback"] = "Trusted benchmark inputs or verifier changed after the manifest was frozen."
        return result
    if submission.is_symlink() or not submission.is_file():
        result.update(status="NO_SUBMISSION", score=0.0,
                      feedback="No regular repair.tcl was produced by the Agent.")
        return result
    content = submission.read_bytes()
    if not content.strip():
        result.update(status="NO_SUBMISSION", score=0.0,
                      feedback="The Agent produced an empty repair.tcl.")
        return result
    copied_submission.write_bytes(content)
    result["submission_sha256"] = hashlib.sha256(content).hexdigest()
    verifier = Path(task.meta["task_dir"]) / "verifier" / "verify.tcl"
    if verifier.is_symlink() or not verifier.is_file():
        result["feedback"] = "Trusted verifier entrypoint is unavailable."
        return result
    excluded = set(provider_key_names()) | {"PDWEAVER_MODEL_API_KEY"} | set(secret_env)
    env = {name: value for name, value in os.environ.items() if name not in excluded}
    env.update(SUBMISSION_TCL=str(copied_submission), OUTPUT_DIR=str(evidence_dir))
    try:
        with log_path.open("wb") as log:
            process = subprocess.Popen(
                [str(innovus), "-64", "-no_gui", "-files", str(verifier.resolve())],
                cwd=str(evidence_dir), env=env, stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
            )
            try:
                result["exit_code"] = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                result["feedback"] = "Private verifier exceeded its fixed time budget."
                return result
    except OSError:
        result["feedback"] = "Private verifier process could not be started."
        return result
    try:
        assert_frozen_assets(task)
        if result_path.is_symlink() or result_path.stat().st_size > 1024 * 1024:
            raise ValueError("Invalid result file")
        report = json.loads(result_path.read_text(encoding="utf-8"))
        if not isinstance(report, dict) or report.get("task_id") != task.id:
            raise ValueError("Mismatched task report")
        if result["exit_code"] != 0 or report.get("status") not in {"PASS", "FAIL"}:
            raise ValueError("Verifier execution failed")
    except (OSError, UnicodeError, ValueError, TypeError):
        result["feedback"] = "Private verifier did not produce a valid completed PASS/FAIL report."
        return result
    result.update(status=report["status"], score=1.0 if report["status"] == "PASS" else 0.0,
                  feedback=_feedback(report))
    # {
    #     "status": "PASS",
    #     "score": 1.0,
    #     "feedback": '{"status": "PASS", "checks": {"timing": true, "drv": true, "physical": true}}',
    #     "result_path": "/data/rsi-records/run-001/trials/abc123/verifier/result.json",
    #     "log_path": "/data/rsi-records/run-001/trials/abc123/verifier/innovus.log",
    #     "exit_code": 0,
    #     "submission_sha256": "提交脚本内容的完整SHA256哈希"
    # }
    return result
