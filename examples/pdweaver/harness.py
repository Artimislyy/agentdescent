"""A one-file PDWeaver skill with a recorded, bounded mutation surface."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from collections.abc import Mapping

from agentdescent import FileTree
from agentdescent.skillspec import skill_tree_validator
from agentdescent.treestrategy import parse_proposal

from .records import RunRecords

SKILL_KEY = "SKILL.md"
SKILL_NAME = "innovus-eco-closure-mcp"
MAX_SKILL_BYTES = 128 * 1024


def validate_skill(state, max_bytes=MAX_SKILL_BYTES):
    if SKILL_KEY not in state:
        return "missing-skill-md"
    if set(state) != {SKILL_KEY}:
        return "unexpected-path"
    text = state[SKILL_KEY]
    if not isinstance(text, str):
        return "non-text-skill"
    try:
        if len(text.encode("utf-8")) > max_bytes:
            return "skill-too-large"
    except UnicodeEncodeError:
        return "invalid-utf8"
    return skill_tree_validator(root_name=SKILL_NAME)(state)

#检查一份 Skill 是否符合格式和修改范围要求
def load_initial(skill_file: Path) -> dict:
    # read_text's universal newline conversion would alter a CRLF baseline.
    state = {SKILL_KEY: Path(skill_file).read_bytes().decode("utf-8")}
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
        super().__init__(initial_files=initial_files, editable=(SKILL_KEY,),
                         max_files_per_diff=1, max_file_bytes=max_file_bytes,
                         validators=(partial(validate_skill, max_bytes=max_file_bytes),))

    def to_diff(self, state, proposal, author, base_version, target):
        edits, rationale = parse_proposal(proposal)
        candidate = dict(state)
        for path, content in edits.items():
            if content is None:
                candidate.pop(path, None)
            else:
                candidate[path] = content
        reason = None
        if not edits:
            reason = "no-parsed-edits"
        elif set(edits) != {SKILL_KEY}:
            reason = "unexpected-path"
        elif candidate == state:
            reason = "no-change"
        else:
            reason = validate_skill(candidate, self.max_file_bytes)
        diff = None
        if not reason:
            diff = super().to_diff(state, proposal, author, base_version, target)
            if diff is None:
                reason = "filetree-rejected"
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
            "change": self.records.change(state.get(SKILL_KEY), candidate.get(SKILL_KEY)),
        })
        return diff
