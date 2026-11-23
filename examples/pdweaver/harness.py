"""A text-only candidate containing the complete PDWeaver skills tree."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from collections.abc import Mapping
import json
import re
import threading

from agentdescent import FileTree
from agentdescent.skillspec import skill_tree_validator
from agentdescent.treestrategy import parse_proposal, safe_relpath

from .records import RunRecords, harness_sha256

SKILL_KEY = "SKILL.md"
SKILL_NAME = "innovus-eco-closure-mcp"
SOLVER_KEY = "solver_prompt.md"
PROMPT_DIR = "rsi-prompts"
HARNESS_FILES = (SKILL_KEY, SOLVER_KEY)
LEGACY_HARNESS_FILES = (*HARNESS_FILES, "system_append.md")
MAX_SKILL_BYTES = 128 * 1024
MAX_TREE_BYTES = 1024 * 1024


def source_paths(skill_file, *, keys=None):
    """Read the whole skills tree; retain the two original proposal aliases."""
    skill_file = Path(skill_file)
    root = skill_file.parent.parent
    aliases = {SKILL_KEY: skill_file, SOLVER_KEY: root / PROMPT_DIR / SOLVER_KEY,
               "system_append.md": root / PROMPT_DIR / "system_append.md"}
    if keys is None:
        keys = list(HARNESS_FILES)
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"skills must not contain symlinks: {path}")
            if path.is_file():
                key = next((key for key, target in aliases.items() if target == path), path.relative_to(root).as_posix())
                if key in aliases and path != aliases[key]:
                    raise ValueError(f"skills file conflicts with a legacy alias: {path}")
                if key not in keys:
                    keys.append(key)
    paths = {key: aliases.get(key, root / safe_relpath(key)) for key in keys}
    for path in paths.values():
        if root not in path.parents or any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError(f"harness path escaped skills or contains a symlink: {path}")
    return paths


def read_text(path):
    # Preserve CRLF so source hashes and writeback reproduce the evaluated bytes.
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected regular harness file: {path}")
    return path.read_bytes().decode("utf-8")


def validate_skill(state, max_bytes=MAX_SKILL_BYTES, *, required=None):
    if SKILL_KEY not in state:
        return "missing-skill-md"
    if required and not set(required) <= set(state):
        return "unexpected-path"
    for key in state:
        try:
            if safe_relpath(key) != key:
                return "unexpected-path"
        except ValueError:
            return "unexpected-path"
        if key in {f"{SKILL_NAME}/{SKILL_KEY}", f"{PROMPT_DIR}/{SOLVER_KEY}", f"{PROMPT_DIR}/system_append.md"}:
            return "duplicate-harness-alias"
        if any(parent.as_posix() in state for parent in Path(key).parents if parent != Path(".")):
            return "file-directory-conflict"
    for text in state.values():
        if not isinstance(text, str) or not text.strip():
            return "empty-or-non-text-file"
        try:
            if len(text.encode("utf-8")) > max_bytes:
                return "file-too-large"
        except UnicodeEncodeError:
            return "invalid-utf8"
    if sum(len(text.encode("utf-8")) for text in state.values()) > MAX_TREE_BYTES:
        return "tree-too-large"
    for key, text in state.items():
        if Path(key).name == SKILL_KEY:
            name = SKILL_NAME if key == SKILL_KEY else Path(key).parent.name
            reason = skill_tree_validator(root_name=name)({SKILL_KEY: text})
            if reason:
                return reason

#检查一份 Skill 是否符合格式和修改范围要求
def load_initial(skill_file: Path) -> dict:
    # read_text's universal newline conversion would alter a CRLF baseline.
    state = {key: read_text(path) for key, path in source_paths(skill_file).items()}
    reason = validate_skill(state)
    if reason:
        raise ValueError(f"invalid initial skill: {reason}")
    return state

#Ledger将已采纳版本保存为 Git 提交，LoggedFileTree包括失败和被拒绝的尝试
class LoggedFileTree(FileTree):
    """Record attempted edits even when structural validation rejects them."""

    def __init__(self, initial_files, records: RunRecords, *, max_file_bytes=MAX_SKILL_BYTES):
        #1. 创建对象时，先检查原始 Skill。文件是否存在、格式合法、没有超出大小限制
        reason = validate_skill(initial_files, max_file_bytes)
        if reason:
            raise ValueError(f"invalid initial skill: {reason}")
        #2. 保存记录器对象，调用父类构造函数
        self.records = records
        self.candidate_keys = {}  # Match each diff to its harness and worker's retest.
        super().__init__(initial_files=initial_files, editable=("**",),
                         max_files_per_diff=1024, max_file_bytes=max_file_bytes,
                         validators=(partial(validate_skill, max_bytes=max_file_bytes,
                                             required=tuple(initial_files)),))

    def to_diff(self, state, proposal, author, base_version, target):
        edits, rationale = {}, ""
        reason = None
        for block in re.findall(r"<EDITS>.*?</EDITS>", proposal, re.S | re.I) or [proposal]:
            parsed, why = parse_proposal(block)
            if not parsed or any(re.fullmatch(r"<[^<>]+>", path) for path in parsed):
                continue
            if edits and parsed != edits:
                reason = "ambiguous-edit-blocks"
                break
            edits, rationale = parsed, why
        # 完整路径和旧别名指向同一文件；先统一名称，再构造候选。
        for full_path, alias in {f"{SKILL_NAME}/{SKILL_KEY}": SKILL_KEY,
                                 f"{PROMPT_DIR}/{SOLVER_KEY}": SOLVER_KEY,
                                 f"{PROMPT_DIR}/system_append.md": "system_append.md"}.items():
            if full_path in edits:
                if alias in edits and edits[alias] != edits[full_path]:
                    reason = "conflicting-harness-alias"
                    break
                edits[alias] = edits.pop(full_path)
        candidate = dict(state)
        for path, content in edits.items():
            if content is None:
                candidate.pop(path, None)
            else:
                candidate[path] = content
        if reason is None:
            if not edits:
                reason = "no-parsed-edits"
            elif any(content is None for content in edits.values()):
                reason = "file-deletion-not-allowed"
            elif candidate == state:
                reason = "no-change"
            else:
                reason = validate_skill(candidate, self.max_file_bytes, required=tuple(self.initial_files))
        diff = None
        if not reason:
            normalized = json.dumps({"rationale": rationale, "edits": [
                {"path": path, "content": content} for path, content in edits.items()]})
            diff = super().to_diff(state, normalized, author, base_version, target)
            if diff is None:
                reason = "filetree-rejected"
            else:
                self.candidate_keys[diff.diff_id] = (harness_sha256(candidate), threading.get_ident())
        else:
            with self._rejections_lock:
                self.structural_rejections[reason] += 1
        self.records.append("changes.jsonl", {
            "author": author,
            "base_version": dict(base_version) if isinstance(base_version, Mapping)
                            else {target: base_version},
            "target": target,
            "raw_proposal": proposal, "parsed_edits": edits, "rationale": rationale,
            "outcome": "accepted-for-evaluation" if diff is not None else "rejected",
            "reason": reason, "diff": diff,
            "change": self.records.change_tree(state, candidate),
        })
        return diff
