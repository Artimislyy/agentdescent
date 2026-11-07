"""
Evolve a multi-file Agent Skill library an agent reads off disk.

Flagship skill path: ≥2 ``*/SKILL.md`` with YAML frontmatter, ``layout="skill_library"``.
Offline agent fails if it does not open those files. Contrast
``examples.skill_evolution`` (AppendRules playbook), ``examples.skill_dir_evolution``
(one skill), ``examples.evoskill`` (paper port). Seed is wrong: ``COLUMN: id`` /
``FIELD: month``.

    python -m examples.skill_library_evolution --dry-run
    python -m examples.skill_library_evolution
    python -m examples.skill_library_evolution --install-to ~/.claude/skills
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sys
import tempfile
from typing import Dict, List, Mapping, Optional

from agentdescent import (
    AggregatorConfig, FileTree, Policies, evolve, load_tree, scorer,
    tree_reflector, tree_runner,
)
from agentdescent.agents import claude_code, cli_agent, codex, openai_compatible
from agentdescent.governance import SKILL_BLAST_RADIUS
from agentdescent.skillspec import validate_skill_tree

SKILL_NAMES = ("csv-total", "date-parse")

_CSV_SKILL = """\
---
name: csv-total
description: Total one column of data.csv. Use when asked for a CSV column sum.
---
# csv-total
STATUS: draft
Read `references/rules.md` for the column; reply with only the sum.
"""

_DATE_SKILL = """\
---
name: date-parse
description: Extract a calendar field from date.txt. Use when asked for year/month/day.
---
# date-parse
STATUS: draft
Read `references/rules.md` for the field; parse `date.txt` (YYYY-MM-DD); reply with only that value.
"""


def make_library_dir() -> str:
    root = tempfile.mkdtemp(prefix="agentdescent-skill-library-")
    for name, skill, rules in (
        ("csv-total", _CSV_SKILL, "COLUMN: id\n"),
        ("date-parse", _DATE_SKILL, "FIELD: month\n"),
    ):
        path = os.path.join(root, name, "references")
        os.makedirs(path)
        open(os.path.join(root, name, "SKILL.md"), "w").write(skill)
        open(os.path.join(path, "rules.md"), "w").write(rules)
    return root


def library_validator(state: Mapping[str, Optional[str]]) -> Optional[str]:
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


def make_rows(n: int = 16, seed: int = 0) -> List[dict]:
    rng = random.Random(seed)
    rows = []
    for i in range(n // 2):
        amounts = [rng.randint(1, 99) for _ in range(rng.randint(3, 6))]
        csv = "id,amount,note\n" + "\n".join(
            f"{j + 1},{a},row-{j}" for j, a in enumerate(amounts))
        rows.append({
            "kind": "csv",
            "prompt": "What is the total of the requested column in data.csv?",
            "gold": str(sum(amounts)),
            "fixtures": {"data.csv": csv},
        })
    rng2 = random.Random(seed + 17)
    for i in range(n - n // 2):
        y, m, d = rng2.randint(1990, 2025), rng2.randint(1, 12), rng2.randint(1, 28)
        rows.append({
            "kind": "date",
            "prompt": "What year is recorded in date.txt?",
            "gold": str(y),
            "fixtures": {"date.txt": f"{y:04d}-{m:02d}-{d:02d}\n"},
        })
    rng.shuffle(rows)
    return rows


def to_tasks(rows):
    from agentdescent import Task
    return [Task(id=f"t{i}", prompt=r["prompt"],
                 meta={"gold": r["gold"], "fixtures": r["fixtures"], "kind": r["kind"]})
            for i, r in enumerate(rows)]


_OFFLINE_AGENT = r"""
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


def offline_agent():
    return cli_agent([sys.executable, "-c", _OFFLINE_AGENT])


def offline_reflector():
    def complete(prompt: str) -> str:
        edits = []
        # Per-skill STATUS flip from the inlined --- <slug>/SKILL.md --- sections (#847).
        for name in SKILL_NAMES:
            marker = f"--- {name}/SKILL.md ---"
            if marker not in prompt:
                continue
            section = prompt.split(marker, 1)[1].split("\n--- ", 1)[0]
            if "STATUS: draft" not in section:
                continue
            body = _CSV_SKILL if name == "csv-total" else _DATE_SKILL
            edits.append({
                "path": f"{name}/SKILL.md",
                "content": body.replace("STATUS: draft", "STATUS: ready"),
            })
        if "COLUMN: amount" not in prompt:
            edits.append({"path": "csv-total/references/rules.md",
                          "content": "COLUMN: amount\n"})
        if "FIELD: year" not in prompt:
            edits.append({"path": "date-parse/references/rules.md",
                          "content": "FIELD: year\n"})
        if not edits:
            edits.append({"path": "csv-total/references/rules.md",
                          "content": "COLUMN: amount\n"})
        return "<EDITS>" + json.dumps({
            "rationale": "mark skills ready; sum amount; date tasks ask for year",
            "edits": edits[:2],
        }) + "</EDITS>"
    return complete


def estimate_calls(rounds: int, workers: int, tasks: int) -> Dict[str, int]:
    held = max(1, int(tasks * 0.3))
    return {
        "agent_rollouts_upper": rounds * (workers * 3 + held * 2),
        "reflector_calls_upper": rounds * workers,
        "held_out": held,
    }


def evolve_library(path, tasks, *, agent, reflect_with, score="contains", **kw):
    tree = load_tree(path)
    strategy = FileTree(tree, max_files_per_diff=2, validators=[library_validator])
    run = tree_runner(agent, layout="skill_library", name="skills",
                      overlay=strategy.frozen_files(tree))
    for key, value in (("self_verify", False), ("cheap_eval_tasks", 4),
                       ("held_out_frac", 0.3), ("patience", 3), ("target_reward", 0.98),
                       ("agg_config", AggregatorConfig(batch_trigger=2, max_wait_rounds=1)),
                       ("policies", Policies())):
        kw.setdefault(key, value)
    return evolve(tasks, scorer(score), run=run, strategy=strategy,
                  artifact_id="skill_library",
                  propose=tree_reflector(reflect_with, strategy=strategy),
                  blast_radius=SKILL_BLAST_RADIUS, **kw)


def _print_library_tree(path: str) -> None:
    tree = load_tree(path)
    print("Library tree:")
    for rel in sorted(tree):
        preview = tree[rel].strip().splitlines()[0] if tree[rel].strip() else "(empty)"
        print(f"  {rel}\n    {preview[:72]}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--agent", default="offline",
                    choices=["offline", "claude-code", "codex"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--tasks", type=int, default=16)
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--dry-run", action="store_true",
                    help="print library tree + estimate; no network, no evolve")
    ap.add_argument("--install-to", default=None,
                    help="write the evolved library here when the run improves it")
    args = ap.parse_args()

    path = make_library_dir()
    print(f"Library  : {path}")
    print(f"Skills   : {', '.join(SKILL_NAMES)}")
    print("Layout   : skill_library (.claude/skills/<name>/)")
    _print_library_tree(path)
    est = estimate_calls(args.rounds, args.workers, args.tasks)
    print(f"\nPlan     : agent={args.agent}, rounds={args.rounds}, "
          f"workers={args.workers}, tasks={args.tasks}")
    print(f"Budget   : up to ~{est['agent_rollouts_upper']} agent rollouts, "
          f"~{est['reflector_calls_upper']} reflector calls "
          f"(held-out ≈ {est['held_out']})")
    if args.dry_run:
        print("\n[dry-run] library tree + estimate only; no evolve, no network.")
        shutil.rmtree(path, ignore_errors=True)
        return

    agents = {
        "offline": offline_agent(),
        "claude-code": claude_code(extra_args=["--permission-mode", "acceptEdits"],
                                   timeout=300.0),
        "codex": codex(timeout=300.0),
    }
    agent = agents[args.agent]
    reflect = (openai_compatible(model=args.model) if args.model
               else (offline_reflector() if args.agent == "offline" else agent))
    print(f"Reflector: {args.model or ('stub' if args.agent == 'offline' else args.agent)}")
    print("Start    : csv-total COLUMN=id; date-parse FIELD=month (both wrong)\n")
    result = evolve_library(
        path, to_tasks(make_rows(args.tasks)), agent=agent, reflect_with=reflect,
        rounds=args.rounds, n_workers=args.workers, max_concurrency=args.workers,
        verbose=True)
    print(f"\nfinal reward : {result.final_reward:.3f}")
    print(f"stop reason  : {result.stop_reason}\noutcomes     : {result.outcomes()}")
    print(f"error        : {result.error}")
    print("\nevolved rules:")
    print("  csv-total :", result.state.get("csv-total/references/rules.md", "(missing)").strip())
    print("  date-parse:", result.state.get("date-parse/references/rules.md", "(missing)").strip())
    if args.install_to:
        plan = result.write_to(args.install_to)
        n = len({p.split("/", 1)[0] for p in plan["written"] + plan.get("unchanged", []) if "/" in p})
        bak = f" (backup: {plan['backup'][0]})" if plan["backup"] else ""
        print(f"\ninstalled {len(plan['written'])} file(s) ({n} skill dirs) to {args.install_to}{bak}")
    shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":
    main()
