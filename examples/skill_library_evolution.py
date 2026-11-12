"""
Evolve a multi-file Agent Skill library an agent reads off disk.

Flagship skill path: ≥2 ``*/SKILL.md`` with YAML frontmatter, ``layout="skill_library"``.
The installed command is ``agentdescent demo --kind skill_library`` (any cwd, no
key). This module is the source-checkout CLI: ``--dry-run``, ``--agent
claude-code`` / ``codex``, and ``--install-to``.

    agentdescent demo --kind skill_library
    python -m examples.skill_library_evolution --dry-run   # source checkout
    python -m examples.skill_library_evolution
    python -m examples.skill_library_evolution --install-to ~/.claude/skills
"""

from __future__ import annotations

import argparse
import shutil
from typing import Dict

from agentdescent import (
    AggregatorConfig, FileTree, Policies, evolve, load_tree, scorer,
    tree_reflector, tree_runner,
)
from agentdescent.agents import claude_code, codex, openai_compatible
from agentdescent.demo import (
    LIBRARY_SKILL_NAMES as SKILL_NAMES,
    library_rows as make_rows,
    library_validator,
    make_library_dir,
    offline_library_agent as offline_agent,
    offline_library_reflector as _offline_library_reflector,
)
from agentdescent.governance import SKILL_BLAST_RADIUS


def offline_reflector():
    return _offline_library_reflector


def to_tasks(rows):
    from agentdescent import Task
    return [Task(id=f"t{i}", prompt=r["prompt"],
                 meta={"gold": r["gold"], "fixtures": r["fixtures"], "kind": r["kind"]})
            for i, r in enumerate(rows)]


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
