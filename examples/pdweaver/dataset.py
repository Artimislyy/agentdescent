"""Freeze EDA splits and export only the task's declared public inputs.

Copying an allowlist is data hygiene, not an OS sandbox. The Agent must run in
an environment that cannot read the evaluator's archive or evidence directory.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import stat
from pathlib import Path
from typing import Dict, List

from agentdescent.evolution import Task


PUBLIC_FILES = ("task.md", "initial_state/design.enc")
PUBLIC_DATABASE = "initial_state/design.enc.dat"


def _regular(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("Public inputs must not contain symlinks: %s" % path)
    if not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("Required regular input file is missing: %s" % path)


def _public_files(root: Path) -> List[Path]:
    if root.is_symlink() or (root / "initial_state").is_symlink():
        raise ValueError("Public input directories must not be symlinks")
    files = [root / name for name in PUBLIC_FILES]
    database = root / PUBLIC_DATABASE
    if database.is_symlink() or not database.is_dir():
        raise ValueError("Checkpoint directory missing or a symlink: %s" % database)
    for child in sorted(database.rglob("*")):
        if child.is_symlink():
            raise ValueError("Public inputs must not contain symlinks: %s" % child)
        if not child.is_dir():
            files.append(child)
    if len(files) == len(PUBLIC_FILES):
        raise ValueError("Checkpoint data directory is empty: %s" % database)
    for path in files:
        _regular(path)
    return files


def _fingerprint(root: Path) -> Dict[str, str]:
    result = {}
    for path in _public_files(root):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            block = stream.read(1024 * 1024)
            if block.startswith(b"version https://git-lfs.github.com/spec/v1"):
                raise ValueError("Unexpanded Git LFS pointer: %s" % path)
            while block:
                digest.update(block)
                block = stream.read(1024 * 1024)
        result[path.relative_to(root).as_posix()] = digest.hexdigest()
    return result


def fingerprint_public_inputs(task: Task) -> Dict[str, str]:
    """Validate and hash only public inputs; use again after an Agent trial."""
    return _fingerprint(Path(task.meta["task_dir"]))


def fingerprint_workspace(workspace: Path) -> Dict[str, str]:
    """Detect changes to staged inputs without hashing generated reports."""
    return _fingerprint(Path(workspace))


def fingerprint_verifier(task: Task) -> Dict[str, str]:
    """Freeze the task-local evaluator code, configuration, and support assets."""
    root = Path(task.meta["task_dir"]) / "verifier"
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Verifier directory is missing or a symlink")
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Verifier assets must not contain symlinks")
        if path.is_dir():
            continue
        _regular(path)
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        result[path.relative_to(root).as_posix()] = digest.hexdigest()
    return result


def assert_frozen_assets(task: Task) -> None:
    """Fail if trusted inputs/evaluator changed since loading the manifest."""
    for key, fingerprint in (("public_inputs_sha256", fingerprint_public_inputs),
                             ("verifier_sha256", fingerprint_verifier)):
        expected = task.meta.get(key)
        if expected is not None and fingerprint(task) != expected:
            raise ValueError("Frozen benchmark assets changed: %s" % key)


def load_manifest(path: Path, *, preflight: bool = True) -> Dict[str, List[Task]]:
    """Load fixed train/val/test splits; relative paths are manifest-relative.

    ``preflight=False`` is for inspection only: real runs must resolve all LFS
    files and pass the public-input fingerprint checks before calling evolve.
    """
    path = Path(path).expanduser().resolve()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema_version") != 1 or not isinstance(raw.get("tasks"), list):
        raise ValueError("Expected manifest schema_version=1 and tasks list")
    splits = {name: [] for name in ("train", "val", "test")}
    seen_ids, seen_paths = set(), set()
    for row in raw["tasks"]:
        if not isinstance(row, dict) or set(row) != {"id", "split", "task_dir", "verifier"}:
            raise ValueError("Each task needs exactly id, split, task_dir, verifier")
        task_id, split = row["id"], row["split"]
        if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", task_id):
            raise ValueError("Task id must be a nonempty filename-safe string")
        if not isinstance(split, str) or split not in splits:
            raise ValueError("Task split must be train, val, or test")
        if row["verifier"] != "innovus_tcl":
            raise ValueError("This example supports only the explicit innovus_tcl result.json protocol")
        if not isinstance(row["task_dir"], str) or not row["task_dir"]:
            raise ValueError("task_dir must be a nonempty path string")
        supplied = Path(row["task_dir"]).expanduser()
        if not supplied.is_absolute():
            supplied = path.parent / supplied
        if supplied.is_symlink():
            raise ValueError("Task archive must not be a symlink: %s" % supplied)
        root = supplied.resolve()
        if task_id in seen_ids or root in seen_paths:
            raise ValueError("Duplicate task id or archive across splits: %s" % task_id)
        if not root.is_dir():
            raise ValueError("Task archive does not exist: %s" % root)
        for existing in seen_paths:
            if existing in root.parents or root in existing.parents:
                raise ValueError("Task archives must not overlap: %s" % root)
        seen_ids.add(task_id)
        seen_paths.add(root)
        _regular(root / "task.md")
        _regular(root / "verifier" / "verify.tcl")
        if (root / "verifier" / "verify.py").exists():
            raise ValueError("Task has a verify.py protocol; add a dedicated adapter before using it")
        task = Task(task_id, (root / "task.md").read_text(encoding="utf-8"),
                    {"split": split, "task_dir": str(root), "verifier": "innovus_tcl"})
        if preflight:
            task.meta["public_inputs_sha256"] = fingerprint_public_inputs(task)
            task.meta["verifier_sha256"] = fingerprint_verifier(task)
        splits[split].append(task)
    if any(not tasks for tasks in splits.values()):
        raise ValueError("Freeze at least one task in each of train, val, and test")
    if len(splits["train"]) + len(splits["val"]) < 4:
        raise ValueError("AgentDescent requires at least four train + val tasks")
    return splits

# 检查工作区是新目录或空目录，且位于原始任务档案之外。
# 检查原始题目和验收资产没有变化。
# 创建工作区，复制 task.md、initial_state/design.enc 和 design.enc.dat/。
# 比较复制前后的文件哈希，确认输入没有变化。
# 返回输入文件的哈希，供试跑结束后检查是否被修改。
def stage_task(task: Task, workspace: Path) -> Dict[str, str]:
    """Create an isolated fresh task directory and verify the exact copy."""
    source, workspace = Path(task.meta["task_dir"]), Path(workspace)
    if workspace.is_symlink() or (workspace.exists() and any(workspace.iterdir())):
        raise ValueError("Task workspace must be new or empty: %s" % workspace)
    if source.resolve() == workspace.resolve() or source.resolve() in workspace.resolve().parents:
        raise ValueError("Task workspace must be outside the evaluator task archive")
    assert_frozen_assets(task)
    before = fingerprint_public_inputs(task)
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "initial_state").mkdir()
    for name in PUBLIC_FILES:
        shutil.copy2(source / name, workspace / name)
    shutil.copytree(source / PUBLIC_DATABASE, workspace / PUBLIC_DATABASE)
    if _fingerprint(workspace) != before or fingerprint_public_inputs(task) != before:
        raise ValueError("Public inputs changed while staging the trial")
    return before
