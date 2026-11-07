"""A complete, working evolution you can run with no API key: ``agentdescent demo``.

Every other entry point needs three things a newcomer does not have yet -- a
worker agent on ``PATH``, a provider key, and a dataset with known answers --
so the first thing they see is an error about a missing file. This module is
the answer to *"show me it working"*: one command builds a real skill
directory (or a text prompt), a real dataset, and runs the real loop against
a deterministic offline agent.

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
from typing import Any, Dict, List, Optional

from .agents import Completion, cli_agent

__all__ = [
    "DEMO_SKILL",
    "OFFLINE_ALGORITHMS",
    "OFFLINE_SKIP",
    "OFFLINE_TEXT_ALGORITHMS",
    "build",
    "demo_spec",
    "offline_agent",
    "offline_reflector",
    "offline_text_agent",
    "offline_text_reflector",
    "skip_reason",
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

#: The agent, as a program. It reads `references/rules.md` out of the workspace
#: to learn which column to total -- so a skill that names the wrong column
#: really does produce wrong answers, and the run really does have to fix the
#: file rather than the prompt.
_AGENT_SRC = (
    "import csv,os,re,sys;"
    f"p=os.path.join('.claude','skills','{DEMO_SKILL}','references','rules.md');"
    "t=open(p).read() if os.path.exists(p) else '';"
    "m=re.search(r'COLUMN:\\s*(\\w+)',t);"
    "col=m.group(1) if m else 'id';"
    "rows=list(csv.DictReader(open('data.csv')));"
    "print(sum(int(r[col]) for r in rows) if rows and col in rows[0] else 'unknown')"
)

#: A valid Agent Skill: hosts (Claude Code, Codex, OpenCode) only load a skill
#: whose SKILL.md carries ``name`` + ``description`` frontmatter, and a run on a
#: tree without it turns the SKILL.md structural gate off (#453).
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

#: Wrong on purpose: `id` is a row number, not the quantity anyone wants summed.
#: The run's whole job is to discover that and rewrite this file.
_RULES_MD = "COLUMN: id\n"

#: Seed prompt for the text offline fixture (cards that are text-only).
_TEXT_SEED = "COLUMN: id\n"


def skip_reason(name: str) -> Optional[str]:
    """Why ``demo --algorithm NAME`` is refused, or ``None`` if it is offline-ok."""
    return OFFLINE_SKIP.get(name)


def offline_agent() -> Completion:
    """A real workspace agent that needs no API key.

    A subprocess bound to the rollout's workspace, exactly like
    ``claude_code()`` -- it opens the candidate skill and obeys it. What it
    does not have is a model, which is what makes it free and deterministic.
    """
    return cli_agent([sys.executable, "-c", _AGENT_SRC])


def offline_reflector(prompt: str) -> str:
    """Stand in for the reflecting model: propose the fix the failure implies.

    A real reflector reads the same prompt and decides what to change. This one
    reads the current ``rules.md`` out of that prompt and names the column the
    data actually has, in the multi-file edit protocol a
    :class:`~agentdescent.treestrategy.FileTree` run expects.
    """
    match = re.search(r"--- references/rules\.md ---\n(.*?)\n(?:---|TASK)", prompt, re.S)
    body = (match.group(1) if match else "").strip()
    fixed = re.sub(r"COLUMN:\s*\w+", "COLUMN: amount", body) if body else "COLUMN: amount"
    if "COLUMN:" not in fixed:
        fixed = "COLUMN: amount"
    return "<EDITS>" + json.dumps({
        "rationale": "`id` is a row number; the quantity asked for is `amount`.",
        "edits": [{"path": "references/rules.md", "content": fixed + "\n"}],
    }) + "</EDITS>"


def offline_text_agent(prompt: str) -> str:
    """Plain :data:`~agentdescent.agents.Completion` for the text offline fixture.

    The template is ``{skill}\\n\\n{prompt}``. ACE / DGM keep the seed text and
    append lessons, so the **last** ``COLUMN:`` wins (#845).
    """
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
    """Text / SkillOpt offline reflector: one rule, or a SkillOpt JSON patch.

    SkillOpt replaces ``propose`` with an analyst that asks the completion for
    a JSON edit list; other text cards use :func:`~agentdescent.evolution.reflector`
    and expect a single rule that becomes the new skill (or an ACE/DGM lesson).
    """
    if '"edits"' in prompt or "Return ONLY a JSON object" in prompt:
        # Prefer replace so the seed COLUMN: id disappears (last-match agent
        # would also work with append, but replace is the faithful fix).
        return json.dumps({
            "reasoning": "`id` is a row number; sum `amount` instead.",
            "edits": [{
                "op": "replace",
                "target": "COLUMN: id",
                "content": "COLUMN: amount",
            }],
        })
    return "COLUMN: amount"


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
        # The stub agent echoes what it is asked, so the task reaches it as-is.
        "prompt_template": "{prompt}",
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


def build(root: str, algorithm: Optional[str] = None) -> Dict[str, Any]:
    """Write the demo's skill/prompt, dataset and spec under ``root``.

    ``algorithm`` (one of :data:`OFFLINE_ALGORITHMS`) picks the fixture: text
    cards get :func:`demo_text_spec`, ``archive_selection`` (and the default
    with no algorithm) get the skill_dir fixture. The caller validates the name.
    """
    use_text = algorithm in OFFLINE_TEXT_ALGORITHMS
    if use_text:
        with open(os.path.join(root, "prompt.txt"), "w", encoding="utf-8") as fh:
            fh.write(_TEXT_SEED)
        with open(os.path.join(root, "cases.jsonl"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(json.dumps(r) for r in _text_rows()) + "\n")
        spec = demo_text_spec(root)
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


def learned_summary(state: Dict[str, Any], *, kind: str) -> str:
    """One-line description of what the offline demo committed, for ``cmd_demo``."""
    if kind == "text":
        if "value" in state:
            return f"prompt -> {state.get('value', '').strip()!r}"
        if "skill" in state:
            return f"skill -> {state.get('skill', '').strip()!r}"
        if "capabilities" in state:
            return f"capabilities -> {state.get('capabilities', '').strip()!r}"
        # ACE playbook keys
        bullets = [v for k, v in state.items() if isinstance(v, str) and "::" in v]
        if bullets:
            return f"playbook -> {bullets[-1].strip()!r}"
        return f"state -> {state!r}"
    return f"rules.md -> {state.get('references/rules.md', '').strip()!r}"
