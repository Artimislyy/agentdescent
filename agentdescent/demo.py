"""A complete, working evolution you can run with no API key: ``agentdescent demo``.

Every other entry point needs three things a newcomer does not have yet -- a
worker agent on ``PATH``, a provider key, and a dataset with known answers --
so the first thing they see is an error about a missing file. This module is
the answer to *"show me it working"*: one command builds a real skill
directory, a multi-file skill library, or a text prompt), a real dataset, and
runs the real loop against a deterministic offline agent.

Nothing here is a mock of the framework. Staging, the ledger, the merge and
the held-out gate all run exactly as they do against Claude Code. Only the
*model* is replaced: the "agent" obeys the skill mechanically, and the
"reflector" writes the one edit a model would write.

The callables are public and resolvable from a spec
(``{"ref": "agentdescent.demo:offline_agent"}``), so anyone can point their
own spec at them to rehearse a run before spending anything.
"""

from __future__ import annotations

import csv
import io
import json
import os
import random
import re
import sys
import tempfile
from typing import Any, Dict, List, Optional

from .agents import Completion, cli_agent
from .skillspec import validate_skill_tree

__all__ = [
    "DEMO_SKILL",
    "LIBRARY_SKILL_NAMES",
    "OFFLINE_ALGORITHMS",
    "OFFLINE_SKIP",
    "OFFLINE_TEXT_ALGORITHMS",
    "build",
    "demo_library_spec",
    "demo_spec",
    "demo_text_spec",
    "learned_summary",
    "library_rows",
    "library_validator",
    "make_library_dir",
    "offline_agent",
    "offline_library_agent",
    "offline_library_reflector",
    "offline_reflector",
    "offline_text_agent",
    "offline_text_reflector",
    "resolve_demo_kind",
    "skip_reason",
    "write_library",
]

#: The demo's skill directory name, and the artifact id the run reports.
DEMO_SKILL = "csv-total"

#: Named algorithms ``agentdescent demo --algorithm`` accepts offline.
#: ``archive_selection`` uses the skill_dir fixture; the rest use the text
#: fixture (those cards are text-only). Verified in ``tests/test_demo.py``.
OFFLINE_ALGORITHMS = (
    "archive_selection",
    "gepa",
    "dgm",
    "ace",
    "skillopt",
    "rrsi",
)

#: Cards that apply to skill_dir / skill_library but need a real proposal
#: protocol the offline reflector does not speak -- refused with a reason.
OFFLINE_SKIP = {
    "evoskill": (
        "evoskill's proposer/generator protocol needs a real model; the offline "
        "demo reflector only speaks the tree <EDITS> / text-rule formats. Run it "
        "for real with `agentdescent algorithms run evoskill <path> <cases.jsonl>`"
    ),
}

#: Subset of :data:`OFFLINE_ALGORITHMS` that run on the text fixture.
OFFLINE_TEXT_ALGORITHMS = ("gepa", "dgm", "ace", "skillopt", "rrsi")

#: Wrong on purpose: `id` is a row number. The smoke demo fixes it in one
#: commit; multi-round library evolution is ``demo --kind skill_library`` (#878).
_RULES_MD = "COLUMN: id\n"
_TEXT_SEED = "COLUMN: id\n"

#: The agent, as a program. It reads `references/rules.md` out of the workspace
#: to learn which column to total and which scale to apply.
_AGENT_SRC = (
    "import csv,os,re,sys;"
    f"p=os.path.join('.claude','skills','{DEMO_SKILL}','references','rules.md');"
    "t=open(p).read() if os.path.exists(p) else '';"
    "m=re.search(r'COLUMN:\\s*(\\w+)',t);"
    "col=m.group(1) if m else 'id';"
    "rows=list(csv.DictReader(open('data.csv')));"
    "print(sum(int(r[col]) for r in rows) if rows and col in rows[0] else 'unknown')"
)

#: A valid Agent Skill: hosts only load a skill whose SKILL.md carries
#: ``name`` + ``description`` frontmatter (#453).
_SKILL_MD = f"""---
name: {DEMO_SKILL}
description: Use when asked to total a column of data.csv; reads references/rules.md to learn which column to sum.
---

# {DEMO_SKILL}

Total one column of `data.csv`, which is in the working directory.

1. Read `references/rules.md` to find out **which** column to total.
2. Sum that column over every data row.
3. Reply with only the number.
"""


def skip_reason(name: str) -> Optional[str]:
    """Why ``demo --algorithm NAME`` is refused, or ``None`` if it is offline-ok."""
    return OFFLINE_SKIP.get(name)




def offline_agent() -> Completion:
    """A real workspace agent that needs no API key."""
    return cli_agent([sys.executable, "-c", _AGENT_SRC])


def offline_reflector(prompt: str) -> str:
    """Propose the COLUMN fix as a tree edit (smoke demo; see --kind skill_library)."""
    match = re.search(
        r"--- references/rules\.md ---\n(.*?)(?:\n--- |\nTASK|\Z)", prompt, re.S)
    body = (match.group(1).strip() if match else "")
    fixed = re.sub(r"COLUMN:\s*\w+", "COLUMN: amount", body) if body else "COLUMN: amount"
    if "COLUMN:" not in fixed:
        fixed = "COLUMN: amount"
    if not fixed.endswith("\n"):
        fixed += "\n"
    return "<EDITS>" + json.dumps({
        "rationale": "`id` is a row number; the quantity asked for is `amount`.",
        "edits": [{"path": "references/rules.md", "content": fixed}],
    }) + "</EDITS>"




def offline_text_agent(prompt: str) -> str:
    """Plain Completion for the text offline fixture (last COLUMN wins)."""
    cols = re.findall(r"COLUMN:\s*(\w+)", prompt)
    col = cols[-1] if cols else "id"
    match = re.search(r"```csv\n(.*?)```", prompt, re.S)
    if not match:
        return "unknown"
    rows = list(csv.DictReader(io.StringIO(match.group(1).strip() + "\n")))
    if not rows or col not in rows[0]:
        return "unknown"
    return str(sum(int(r[col]) for r in rows))


def offline_text_reflector(prompt: str) -> str:
    """Text / SkillOpt offline reflector: one-shot COLUMN fix (#845).

    The skill_dir demo is a one-commit smoke; multi-round teaching is
    ``demo --kind skill_library`` (#878). Text cards stay one-shot.
    """
    if '"edits"' in prompt or "Return ONLY a JSON object" in prompt:
        return json.dumps({
            "reasoning": "`id` is a row number; sum `amount` instead.",
            "edits": [{
                "op": "replace",
                "target": "COLUMN: id",
                "content": "COLUMN: amount",
            }],
        })
    return "COLUMN: amount"




LIBRARY_SKILL_NAMES = ("csv-total", "date-parse")

_CSV_LIBRARY_SKILL = """\
---
name: csv-total
description: Total one column of data.csv. Use when asked for a CSV column sum.
---
# csv-total
STATUS: draft
Read `references/rules.md` for the column; reply with only the sum.
"""

_DATE_LIBRARY_SKILL = """\
---
name: date-parse
description: Extract a calendar field from date.txt. Use when asked for year/month/day.
---
# date-parse
STATUS: draft
Read `references/rules.md` for the field; parse `date.txt` (YYYY-MM-DD); reply with only that value.
"""

_LIBRARY_AGENT_SRC = r"""
import csv, os, re, sys
skills = os.path.join('.claude', 'skills')

def read_rules(name):
    p = os.path.join(skills, name, 'references', 'rules.md')
    return open(p).read() if os.path.exists(p) else ''

if os.path.exists('data.csv'):
    rules = read_rules('csv-total')
    if not rules:
        print('MISSING_SKILL'); sys.exit(0)
    m = re.search(r'COLUMN:\s*(\w+)', rules)
    column = m.group(1) if m else 'id'
    rows = list(csv.DictReader(open('data.csv')))
    print(sum(int(r[column]) for r in rows if r.get(column, '').strip().isdigit()))
elif os.path.exists('date.txt'):
    rules = read_rules('date-parse')
    if not rules:
        print('MISSING_SKILL'); sys.exit(0)
    m = re.search(r'FIELD:\s*(\w+)', rules)
    field = (m.group(1) if m else 'month').lower()
    y, mo, d = open('date.txt').read().strip().split('-')
    print({'year': str(int(y)), 'month': str(int(mo)), 'day': str(int(d))}.get(field, 'UNKNOWN'))
else:
    print('NO_FIXTURE')
"""


def write_library(root: str) -> None:
    """Write the two-skill fixture (wrong COLUMN / FIELD on purpose) under ``root``."""
    for name, skill, rules in (
        ("csv-total", _CSV_LIBRARY_SKILL, "COLUMN: id\n"),
        ("date-parse", _DATE_LIBRARY_SKILL, "FIELD: month\n"),
    ):
        path = os.path.join(root, name, "references")
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(root, name, "SKILL.md"), "w", encoding="utf-8") as fh:
            fh.write(skill)
        with open(os.path.join(path, "rules.md"), "w", encoding="utf-8") as fh:
            fh.write(rules)


def make_library_dir() -> str:
    """Temp directory with the two-skill fixture (used by the source-checkout example)."""
    root = tempfile.mkdtemp(prefix="agentdescent-skill-library-")
    write_library(root)
    return root


def library_validator(state):
    """Per-skill Agent Skills frontmatter gate, matching the checkout example."""
    names = {p.split("/", 1)[0] for p in state if p and "/" in p}
    for name in sorted(names):
        skill_state = {}
        for p, body in state.items():
            if p == f"{name}/SKILL.md":
                skill_state["SKILL.md"] = body
            elif p.startswith(f"{name}/"):
                skill_state[p[len(name) + 1:]] = body
        if "SKILL.md" not in skill_state:
            continue
        errors = validate_skill_tree(skill_state, root_name=name)
        if errors:
            return f"skill-library-{name}-{errors[0]}"
    return None


def library_rows(n: int = 16, seed: int = 0) -> List[Dict[str, Any]]:
    """Mixed CSV-total and date-year tasks for the library fixture.

    CSV and date rows are interleaved so a prefix/suffix held-out split
    still contains both kinds; a single-skill commit then moves reward.
    """
    rng = random.Random(seed)
    csv_rows: List[Dict[str, Any]] = []
    for _ in range(n // 2):
        amounts = [rng.randint(1, 99) for _ in range(rng.randint(3, 6))]
        csv_body = "id,amount,note\n" + "\n".join(
            f"{j + 1},{a},row-{j}" for j, a in enumerate(amounts))
        csv_rows.append({
            "kind": "csv",
            "prompt": "What is the total of the requested column in data.csv?",
            "gold": str(sum(amounts)),
            "fixtures": {"data.csv": csv_body},
        })
    rng2 = random.Random(seed + 17)
    date_rows: List[Dict[str, Any]] = []
    for _ in range(n - n // 2):
        y, m, d = rng2.randint(1990, 2025), rng2.randint(1, 12), rng2.randint(1, 28)
        date_rows.append({
            "kind": "date",
            "prompt": "What year is recorded in date.txt?",
            "gold": str(y),
            "fixtures": {"date.txt": f"{y:04d}-{m:02d}-{d:02d}\n"},
        })
    rows: List[Dict[str, Any]] = []
    for i in range(max(len(csv_rows), len(date_rows))):
        if i < len(csv_rows):
            rows.append(csv_rows[i])
        if i < len(date_rows):
            rows.append(date_rows[i])
    return rows


def offline_library_agent() -> Completion:
    """Workspace agent that reads ``*/SKILL.md`` off the library layout."""
    return cli_agent([sys.executable, "-c", _LIBRARY_AGENT_SRC])


def _library_skill_is_draft(prompt: str, name: str) -> bool:
    marker = f"--- {name}/SKILL.md ---"
    if marker not in prompt:
        return False
    section = prompt.split(marker, 1)[1].split("\n--- ", 1)[0]
    return "STATUS: draft" in section


def _library_skill_shown(prompt: str, name: str) -> bool:
    return f"--- {name}/SKILL.md ---" in prompt


def offline_library_reflector(prompt: str) -> str:
    """Pair each SKILL.md STATUS flip with that skill's rule fix.

    Path A inlines ``*/SKILL.md`` but not nested ``references/rules.md``, so
    ``COLUMN: amount`` never appears in the prompt. Using draft-vs-ready as
    the per-skill signal keeps each 2-file commit reward-improving (#878).
    """
    edits = []
    csv_draft = _library_skill_is_draft(prompt, "csv-total")
    date_draft = _library_skill_is_draft(prompt, "date-parse")
    if csv_draft or (not _library_skill_shown(prompt, "csv-total")
                     and "COLUMN: amount" not in prompt):
        if csv_draft:
            edits.append({
                "path": "csv-total/SKILL.md",
                "content": _CSV_LIBRARY_SKILL.replace(
                    "STATUS: draft", "STATUS: ready"),
            })
        edits.append({"path": "csv-total/references/rules.md",
                      "content": "COLUMN: amount\n"})
    if date_draft or (not _library_skill_shown(prompt, "date-parse")
                      and "FIELD: year" not in prompt):
        if date_draft:
            edits.append({
                "path": "date-parse/SKILL.md",
                "content": _DATE_LIBRARY_SKILL.replace(
                    "STATUS: draft", "STATUS: ready"),
            })
        edits.append({"path": "date-parse/references/rules.md",
                      "content": "FIELD: year\n"})
    if not edits:
        edits.append({"path": "csv-total/references/rules.md",
                      "content": "COLUMN: amount\n"})
    return "<EDITS>" + json.dumps({
        "rationale": "mark skills ready; sum amount; date tasks ask for year",
        "edits": edits[:2],
    }) + "</EDITS>"


def resolve_demo_kind(algorithm: Optional[str] = None,
                     kind: Optional[str] = None) -> str:
    """Pick the demo fixture from an explicit ``--kind`` and/or ``--algorithm``."""
    if kind is None:
        return "text" if algorithm in OFFLINE_TEXT_ALGORITHMS else "skill_dir"
    if kind not in ("text", "skill_dir", "skill_library"):
        raise ValueError(
            f"demo --kind must be one of ['skill_dir', 'text', 'skill_library'], "
            f"got {kind!r}")
    if kind == "skill_library" and algorithm in OFFLINE_TEXT_ALGORITHMS:
        raise ValueError(
            f"demo --kind skill_library does not run the text-only card "
            f"{algorithm!r}; use archive_selection or omit --algorithm")
    if kind == "skill_dir" and algorithm in OFFLINE_TEXT_ALGORITHMS:
        raise ValueError(
            f"demo --kind skill_dir does not run the text-only card "
            f"{algorithm!r}; omit --kind (the demo picks the text fixture) "
            f"or pass --kind text")
    if kind == "text" and algorithm and algorithm not in OFFLINE_TEXT_ALGORITHMS:
        raise ValueError(
            f"demo --kind text: {algorithm!r} runs on a skill_dir / "
            f"skill_library fixture; omit --kind or pass --kind skill_dir "
            f"or --kind skill_library")
    return kind


def _rows(n: int = 12, seed: int = 0) -> List[Dict[str, Any]]:
    """One CSV per task, staged into the workspace beside the skill."""
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        amounts = [rng.randint(1, 99) for _ in range(rng.randint(3, 6))]
        csv_body = "id,amount\n" + "\n".join(
            f"{i + 1},{a}" for i, a in enumerate(amounts))
        out.append({"prompt": "What is the total?", "gold": str(sum(amounts)),
                    "fixtures": {"data.csv": csv_body}})
    return out


def _text_rows(n: int = 12, seed: int = 0) -> List[Dict[str, Any]]:
    """CSV embedded in the prompt -- kind=text has no workspace fixtures."""
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        amounts = [rng.randint(1, 99) for _ in range(rng.randint(3, 6))]
        csv_body = "id,amount\n" + "\n".join(
            f"{i + 1},{a}" for i, a in enumerate(amounts))
        out.append({
            "prompt": f"What is the total?\n```csv\n{csv_body}\n```",
            "gold": str(sum(amounts)),
        })
    return out


def demo_spec(root: str) -> Dict[str, Any]:
    """The skill_dir spec the default demo runs: offline agent + reflector."""
    return {
        "version": 1,
        "kind": "skill_dir",
        "target": os.path.join(root, DEMO_SKILL),
        "data": {"path": os.path.join(root, "cases.jsonl"),
                 "prompt": "prompt", "gold": "gold"},
        "score": "exact",
        "agent": {"ref": "agentdescent.demo:offline_agent"},
        "reflect": {"ref": "agentdescent.demo:offline_reflector", "call": False},
        "prompt_template": "{prompt}",
        # Two coordinated fixes need more than one successful commit (#847).
        "evolve": {"rounds": 4, "n_workers": 2, "seed": 0},
    }


def demo_text_spec(root: str) -> Dict[str, Any]:
    """The text spec for offline text-only cards (#845)."""
    return {
        "version": 1,
        "kind": "text",
        "target": os.path.join(root, "prompt.txt"),
        "data": {"path": os.path.join(root, "cases.jsonl"),
                 "prompt": "prompt", "gold": "gold"},
        "score": "exact",
        "agent": {"ref": "agentdescent.demo:offline_text_agent", "call": False},
        "reflect": {"ref": "agentdescent.demo:offline_text_reflector", "call": False},
        "evolve": {"rounds": 4, "n_workers": 2, "seed": 0},
    }


def demo_library_spec(root: str) -> Dict[str, Any]:
    """The skill_library spec for ``demo --kind skill_library`` (#878)."""
    return {
        "version": 1,
        "kind": "skill_library",
        "target": root,
        "data": {"path": os.path.join(root, "cases.jsonl"),
                 "prompt": "prompt", "gold": "gold"},
        "score": "exact",
        "agent": {"ref": "agentdescent.demo:offline_library_agent"},
        "reflect": {"ref": "agentdescent.demo:offline_library_reflector", "call": False},
        "prompt_template": "{prompt}",
        "evolve": {"rounds": 4, "n_workers": 2, "seed": 0},
    }


def build(root: str, algorithm: Optional[str] = None,
          kind: Optional[str] = None) -> Dict[str, Any]:
    """Write the demo's skill/library/prompt, dataset and spec under ``root``."""
    resolved = resolve_demo_kind(algorithm, kind)
    if resolved == "text":
        with open(os.path.join(root, "prompt.txt"), "w", encoding="utf-8") as fh:
            fh.write(_TEXT_SEED)
        with open(os.path.join(root, "cases.jsonl"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(json.dumps(r) for r in _text_rows()) + "\n")
        spec = demo_text_spec(root)
    elif resolved == "skill_library":
        write_library(root)
        with open(os.path.join(root, "cases.jsonl"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(json.dumps(r) for r in library_rows(n=12)) + "\n")
        spec = demo_library_spec(root)
    else:
        skill = os.path.join(root, DEMO_SKILL)
        os.makedirs(os.path.join(skill, "references"), exist_ok=True)
        with open(os.path.join(skill, "SKILL.md"), "w", encoding="utf-8") as fh:
            fh.write(_SKILL_MD)
        with open(os.path.join(skill, "references", "rules.md"), "w", encoding="utf-8") as fh:
            fh.write(_RULES_MD)
        with open(os.path.join(root, "cases.jsonl"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(json.dumps(r) for r in _rows()) + "\n")
        spec = demo_spec(root)
    if algorithm:
        spec["algorithm"] = algorithm
    with open(os.path.join(root, "spec.json"), "w", encoding="utf-8") as fh:
        json.dump(spec, fh, indent=2)
    return spec


#: How many rules a one-line ``learned`` summary names before it counts the rest.
_RULES_SHOWN = 2


def _rules_line(state: Dict[str, Any]) -> str:
    """The learned rule text of a rule-id keyed state, without the ids (#927)."""
    rules: List[str] = []
    for value in state.values():
        if not isinstance(value, str):
            continue
        text = value.strip()
        if text and text not in rules:
            rules.append(text)
    if not rules:
        return "rules -> (none)"
    shown = rules[:_RULES_SHOWN]
    line = " | ".join(shown)
    if len(rules) > len(shown):
        line = f"{line} (+{len(rules) - len(shown)} more)"
    return f"rules -> {line!r}"


def learned_summary(state: Dict[str, Any], *, kind: str) -> str:
    """One-line description of what the offline demo committed, for ``cmd_demo``."""
    if kind == "text":
        if "value" in state:
            return f"prompt -> {state.get('value', '').strip()!r}"
        if "skill" in state:
            return f"skill -> {state.get('skill', '').strip()!r}"
        if "capabilities" in state:
            return f"capabilities -> {state.get('capabilities', '').strip()!r}"
        bullets = [v for k, v in state.items() if isinstance(v, str) and "::" in v]
        if bullets:
            return f"playbook -> {bullets[-1].strip()!r}"
        # #927: what is left is a mapping of internal rule ids to rule text
        # (rrsi). Print the rules, never the ids or the dict repr -- `show`
        # renders the same run as text, and a reader compares the two.
        return _rules_line(state)
    if kind == "skill_library":
        parts = []
        for name in LIBRARY_SKILL_NAMES:
            rules = state.get(f"{name}/references/rules.md", "").strip()
            parts.append(f"{name}/rules.md -> {rules!r}")
        return "; ".join(parts)
    return f"rules.md -> {state.get('references/rules.md', '').strip()!r}"
