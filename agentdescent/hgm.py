"""The Huxley-Gödel Machine's expand-vs-evaluate scheduler, as a pure planner.

The framework already ports HGM's **expansion** rule as
:class:`~agentdescent.selection.CladeThompson`; what it lacked is the other half
of the algorithm: the evaluation policy and the decision between expanding a
node and spending the next task evaluation on it. HGM (Wang et al., ICLR 2026,
arXiv:2510.21614) compares the tree's *clade* evidence with fresh measurements:

* if ``n_task_evals ** alpha >= len(nodes) - 1`` (with any pending expansions),
  expand a node chosen by Thompson sampling on its clade evidence;
* otherwise evaluate a node chosen by Thompson sampling on its own evidence,
  on a task it has not seen yet.

This module is that planner over a JSON tree. It does not run the benchmark or
edit an agent; a caller records expansions/evaluations and asks for the next
action. That keeps the scheduling deterministic and testable while leaving the
existing ``evolve`` loop untouched.

    tree = HGM.from_dict(json.load(open("hgm-tree.json")))
    action = tree.next_action()      # {"action": "expand", "node_id": "initial"}
    tree.record_expansion("initial", "child-1")
    action = tree.next_action()      # {"action": "evaluate", ...}
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "HGM_SCHEMA_VERSION",
    "HGMError",
    "HGMConfig",
    "HGMNode",
    "HGM",
]

HGM_SCHEMA_VERSION = 1


class HGMError(ValueError):
    """An HGM tree the planner cannot use; the message is safe to print."""


def _finite(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HGMError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise HGMError(f"{name} must be finite")
    if positive and number <= 0:
        raise HGMError(f"{name} must be > 0")
    return number


@dataclass(frozen=True)
class HGMConfig:
    """The upstream control knobs, with HGM's defaults."""

    alpha: float = 0.5
    beta: float = 0.5
    cool_down: bool = False
    max_task_evals: int = 100
    n_pseudo_descendant_evals: int = 10
    eval_random_level: float = 0.5
    seed: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "alpha", _finite(self.alpha, "alpha"))
        object.__setattr__(self, "beta", _finite(self.beta, "beta", positive=True))
        if not isinstance(self.cool_down, bool):
            raise HGMError("cool_down must be a bool")
        if isinstance(self.max_task_evals, bool) or not isinstance(
                self.max_task_evals, int) or self.max_task_evals < 1:
            raise HGMError("max_task_evals must be an int >= 1")
        if isinstance(self.n_pseudo_descendant_evals, bool) or not isinstance(
                self.n_pseudo_descendant_evals, int) or self.n_pseudo_descendant_evals < 1:
            raise HGMError("n_pseudo_descendant_evals must be an int >= 1")
        level = _finite(self.eval_random_level, "eval_random_level")
        if not 0.0 <= level <= 1.0:
            raise HGMError("eval_random_level must be in [0, 1]")
        object.__setattr__(self, "eval_random_level", level)
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise HGMError("seed must be an int")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alpha": self.alpha, "beta": self.beta, "cool_down": self.cool_down,
            "max_task_evals": self.max_task_evals,
            "n_pseudo_descendant_evals": self.n_pseudo_descendant_evals,
            "eval_random_level": self.eval_random_level, "seed": self.seed,
        }


@dataclass(frozen=True)
class HGMNode:
    """One agent in the self-modification tree and its utility observations."""

    node_id: str
    parent_id: Optional[str] = None
    commit_id: str = ""
    utility_measures: Tuple[float, ...] = ()
    submitted_tasks: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise HGMError("node_id must be a non-empty string")
        if self.parent_id is not None:
            if not isinstance(self.parent_id, str) or not self.parent_id.strip():
                raise HGMError("parent_id must be a non-empty string or None")
        for value in self.utility_measures:
            number = _finite(value, "utility measure")
            if not 0.0 <= number <= 1.0:
                raise HGMError("utility measures must be in [0, 1]")
        object.__setattr__(self, "utility_measures",
                           tuple(float(value) for value in self.utility_measures))
        if isinstance(self.submitted_tasks, str):
            raise HGMError("submitted_tasks must be a sequence")
        object.__setattr__(self, "submitted_tasks",
                           tuple(str(task) for task in self.submitted_tasks))

    @property
    def num_evals(self) -> int:
        return len(self.utility_measures)

    @property
    def mean_utility(self) -> Optional[float]:
        if not self.utility_measures:
            return None
        return sum(self.utility_measures) / len(self.utility_measures)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "parent_id": self.parent_id,
            "commit_id": self.commit_id,
            "utility_measures": list(self.utility_measures),
            "submitted_tasks": list(self.submitted_tasks),
        }


class HGM:
    """A tree of nodes plus HGM's expand/evaluate policy over them."""

    def __init__(self, config: Optional[HGMConfig] = None,
                 total_tasks: Sequence[str] = (),
                 n_task_evals: int = 0,
                 *, rng: Optional[random.Random] = None) -> None:
        self.config = config or HGMConfig()
        if not isinstance(self.config, HGMConfig):
            raise HGMError("config must be an HGMConfig")
        if isinstance(n_task_evals, bool) or not isinstance(n_task_evals, int) \
                or n_task_evals < 0:
            raise HGMError("n_task_evals must be an int >= 0")
        self.total_tasks = tuple(dict.fromkeys(str(task) for task in total_tasks))
        self.n_task_evals = n_task_evals
        self.rng = rng or random.Random(self.config.seed)
        self._nodes: Dict[str, HGMNode] = {}
        self._children: Dict[str, List[str]] = {}
        self._add(HGMNode("initial"))

    def _add(self, node: HGMNode) -> None:
        if node.node_id in self._nodes:
            raise HGMError(f"node {node.node_id!r} already exists")
        if node.parent_id is not None:
            if node.parent_id not in self._nodes:
                raise HGMError(f"unknown parent {node.parent_id!r}")
            self._children.setdefault(node.parent_id, []).append(node.node_id)
        self._nodes[node.node_id] = node

    @property
    def nodes(self) -> Tuple[HGMNode, ...]:
        return tuple(self._nodes[key] for key in sorted(self._nodes))

    def get(self, node_id: str) -> HGMNode:
        try:
            return self._nodes[node_id]
        except KeyError:
            raise HGMError(f"unknown node {node_id!r}") from None

    def record_expansion(self, parent_id: str, child_id: str, *,
                         commit_id: str = "",
                         utility_measures: Sequence[float] = (),
                         submitted_tasks: Sequence[str] = ()) -> HGMNode:
        self.get(parent_id)
        node = HGMNode(
            child_id, parent_id=parent_id, commit_id=commit_id,
            utility_measures=tuple(utility_measures),
            submitted_tasks=tuple(submitted_tasks))
        self._add(node)
        return node

    def record_evaluation(self, node_id: str, task: str,
                          utility: float) -> HGMNode:
        node = self.get(node_id)
        task = str(task)
        if task not in self.total_tasks:
            raise HGMError(f"task {task!r} is not in total_tasks")
        if task in node.submitted_tasks:
            raise HGMError(f"node {node_id!r} already evaluated task {task!r}")
        value = _finite(utility, "utility")
        if not 0.0 <= value <= 1.0:
            raise HGMError("utility must be in [0, 1]")
        updated = HGMNode(
            **{**node.to_dict(), "utility_measures": node.utility_measures + (value,),
               "submitted_tasks": node.submitted_tasks + (task,)})
        self._nodes[node_id] = updated
        self.n_task_evals += 1
        return updated

    def _descendant_evals(self, node_id: str) -> List[float]:
        node = self.get(node_id)
        pseudo = self.config.n_pseudo_descendant_evals
        if node.num_evals < pseudo and node.utility_measures:
            own = list(node.utility_measures)
        elif node.mean_utility is None:
            own = []
        else:
            own = [node.mean_utility] * pseudo
        for child in self._children.get(node_id, ()):
            own.extend(self._descendant_evals(child))
        return own

    def _ts_sample(self, evals: Sequence[Sequence[float]]) -> int:
        if not evals:
            raise HGMError("no candidates to sample")
        alphas = [1.0 + sum(row) for row in evals]
        betas = [1.0 + len(row) - sum(row) for row in evals]
        if self.config.cool_down:
            remaining = self.config.max_task_evals - self.n_task_evals
            factor = (10000.0 if remaining <= 0 else
                      self.config.max_task_evals ** self.config.beta
                      / remaining ** self.config.beta)
            alphas = [value * factor for value in alphas]
            betas = [value * factor for value in betas]
        # A non-positive Beta parameter is invalid; clamp floating noise.
        alphas = [max(value, 1e-9) for value in alphas]
        betas = [max(value, 1e-9) for value in betas]
        draws = [self.rng.betavariate(a, b) for a, b in zip(alphas, betas)]
        return max(range(len(draws)), key=draws.__getitem__)

    def next_action(self) -> Dict[str, Any]:
        """Return ``expand``, ``evaluate`` or ``stop``; mutate nothing."""
        if self.n_task_evals >= self.config.max_task_evals:
            return {"action": "stop", "reason": "max_task_evals",
                    "n_task_evals": self.n_task_evals}
        if self.n_task_evals ** self.config.alpha >= len(self._nodes) - 1:
            eligible = [node for node in self.nodes
                        if node.mean_utility is not None and node.mean_utility > 0]
            if eligible:
                evals = [self._descendant_evals(node.node_id) for node in eligible]
                chosen = eligible[self._ts_sample(evals)]
                return {
                    "action": "expand",
                    "node_id": chosen.node_id,
                    "commit_id": chosen.commit_id,
                    "n_task_evals": self.n_task_evals,
                    "reason": "n_task_evals ** alpha >= nodes - 1",
                }
            expand_reason = "no expandable node (mean utility missing or <= 0)"
        else:
            expand_reason = "n_task_evals ** alpha < nodes - 1"
        candidates = [
            node for node in self.nodes
            if len(node.submitted_tasks) < len(self.total_tasks)]
        if not candidates:
            return {"action": "stop", "reason": "all tasks submitted",
                    "n_task_evals": self.n_task_evals}
        evals = [list(node.utility_measures) for node in candidates]
        # All-empty own evidence is valid upstream (uniform Beta(1,1)).
        chosen = candidates[self._ts_sample(evals)]
        available = [task for task in self.total_tasks
                     if task not in chosen.submitted_tasks]
        if not available:
            return {"action": "stop", "reason": "no available task",
                    "n_task_evals": self.n_task_evals}
        task = (self.rng.choice(available)
                if self.rng.random() < self.config.eval_random_level
                else available[0])
        return {
            "action": "evaluate",
            "node_id": chosen.node_id,
            "commit_id": chosen.commit_id,
            "task": task,
            "n_task_evals": self.n_task_evals,
            "reason": expand_reason,
        }

    def report(self) -> Dict[str, Any]:
        rows = []
        for node in self.nodes:
            rows.append({
                "node_id": node.node_id,
                "parent_id": node.parent_id,
                "commit_id": node.commit_id,
                "num_evals": node.num_evals,
                "mean_utility": node.mean_utility,
                "cmp": (lambda values: sum(values) / len(values) if values else None)(
                    self._descendant_evals(node.node_id)),
                "submitted_tasks": len(node.submitted_tasks),
            })
        return {
            "schema_version": HGM_SCHEMA_VERSION,
            "ok": True,
            "config": self.config.to_dict(),
            "n_task_evals": self.n_task_evals,
            "total_tasks": len(self.total_tasks),
            "nodes": rows,
        }

    def to_dict(self) -> Dict[str, Any]:
        ordered = []
        pending = list(self.nodes)
        emitted = set()
        while pending:
            progress = False
            for node in list(pending):
                if node.parent_id is None or node.parent_id in emitted:
                    ordered.append(node)
                    emitted.add(node.node_id)
                    pending.remove(node)
                    progress = True
            if not progress:
                raise HGMError("HGM tree has an unresolved parent cycle")
        return {
            "schema_version": HGM_SCHEMA_VERSION,
            "config": self.config.to_dict(),
            "total_tasks": list(self.total_tasks),
            "n_task_evals": self.n_task_evals,
            "nodes": [node.to_dict() for node in ordered],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "HGM":
        if not isinstance(payload, Mapping):
            raise HGMError("HGM tree must be a JSON object")
        try:
            version = int(payload.get("schema_version", 1))
        except (TypeError, ValueError):
            version = -1
        if version != HGM_SCHEMA_VERSION:
            raise HGMError("unsupported HGM tree schema")
        config_payload = payload.get("config") or {}
        if not isinstance(config_payload, Mapping):
            raise HGMError("config must be a JSON object")
        try:
            config = HGMConfig(**dict(config_payload))
        except (TypeError, ValueError) as error:
            raise HGMError(f"invalid HGM config: {error}") from None
        total_tasks = payload.get("total_tasks") or ()
        n_task_evals = payload.get("n_task_evals", 0)
        tree = cls(config, total_tasks, n_task_evals)
        rows = payload.get("nodes") or []
        if not isinstance(rows, list):
            raise HGMError("nodes must be a list")
        pending = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise HGMError("every node must be a JSON object")
            pending.append(HGMNode(
                node_id=row.get("node_id", ""),
                parent_id=row.get("parent_id"),
                commit_id=str(row.get("commit_id", "")),
                utility_measures=tuple(row.get("utility_measures") or ()),
                submitted_tasks=tuple(row.get("submitted_tasks") or ())))
        # Accept any input order: insert roots/ready nodes first, root first.
        while pending:
            progress = False
            for node in list(pending):
                if node.node_id == "initial":
                    tree._nodes["initial"] = node
                    pending.remove(node)
                    progress = True
                elif node.parent_id in tree._nodes:
                    tree._add(node)
                    pending.remove(node)
                    progress = True
            if not progress:
                raise HGMError("HGM tree has an unknown parent or cycle")
        measured = sum(len(node.submitted_tasks) for node in tree.nodes)
        if tree.n_task_evals != measured:
            raise HGMError(
                f"n_task_evals {tree.n_task_evals} does not match "
                f"submitted tasks {measured}")
        return tree


def load_hgm_tree(value: Any) -> HGM:
    """Load an HGM tree from a mapping or a JSON file."""
    if isinstance(value, Mapping):
        return HGM.from_dict(value)
    if isinstance(value, str):
        path = value
        try:
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except OSError as error:
            raise HGMError(f"HGM tree {value!r} cannot be read: {error}") from None
        except ValueError as error:
            raise HGMError(f"HGM tree {value!r} is not valid JSON: {error}") from None
        return HGM.from_dict(payload)
    raise HGMError("HGM tree must be a JSON object or a path")
