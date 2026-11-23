"""Native acceptance for new runs; legacy comparison only for old evidence."""
import math

from types import SimpleNamespace

from agentdescent import AggregatorConfig
from agentdescent.defaults import DefaultAcceptance, DefaultConflict
from agentdescent.policies import MergeContext

from .records import harness_sha256



RULE = "no task regression; more passes first; equal passes require every successful task to be faster"


def summarize_trials(rows):
    scores = [r["score"] for r in rows]
    if not scores or any(isinstance(s, bool) or s not in (0, 1) for s in scores):
        raise ValueError("comparison requires completed binary verifier scores")
    times = [r.get("agent_elapsed_seconds") for r in rows if r["score"] == 1]
    timed = bool(times) and all(isinstance(t, (int, float)) and not isinstance(t, bool)
                               and math.isfinite(t) and t >= 0 for t in times)
    return {"passed_count": sum(scores), "mean": sum(scores) / len(scores),
            "passed_seconds": sum(times) if timed else None}


def compare_trials(before, after, *, min_gain=0.0):
    """Legacy gate for schema 1–3 evidence; never used to select new candidates."""
    if [r["task_id"] for r in before] != [r["task_id"] for r in after]:
        raise ValueError("compare the same tasks in the same order")
    if not math.isfinite(min_gain) or min_gain < 0:
        raise ValueError("minimum gain must be finite and nonnegative")
    base, candidate = summarize_trials(before), summarize_trials(after)
    per_task = [{"task_id": old["task_id"], "baseline_score": old["score"],
                 "candidate_score": new["score"],
                 "baseline_seconds": old.get("agent_elapsed_seconds"),
                 "candidate_seconds": new.get("agent_elapsed_seconds")}
                for old, new in zip(before, after)]
    no_loss = all(new["score"] >= old["score"] for old, new in zip(before, after))
    quality = candidate["mean"] > base["mean"] + min_gain
    faster = (no_loss and candidate["passed_count"] == base["passed_count"]
              and base["passed_seconds"] is not None and candidate["passed_seconds"] is not None
              and all(row["candidate_seconds"] < row["baseline_seconds"]
                      for row in per_task if row["baseline_score"] == 1))
    passed = no_loss and (quality or (min_gain == 0 and faster))
    return {"baseline_mean": base["mean"], "candidate_mean": candidate["mean"],
            "baseline_passed_seconds": base["passed_seconds"],
            "candidate_passed_seconds": candidate["passed_seconds"],
            "no_task_regression": no_loss, "speed_improved": faster,
            "per_task": per_task, "min_gain": min_gain, "passed": passed, "rule": RULE}


DEFAULT_RULE = "agentdescent_default"


class RejectTrainingRegression:
    def __init__(self, runner, strategy):
        self.runner = runner
        self.strategy = strategy

    def screen(self, card):
        # With binary rewards, a negative delta means PASS -> FAIL on the same task.
        if card.before_after_delta < 0:
            return "training regression: candidate failed a previously passing task"
        sha, worker = self.strategy.candidate_keys[card.diff.diff_id]
        with self.runner._lock:
            if any(self.runner.training_results.get((sha, task.id, worker), {}).get("status") == "NO_SUBMISSION"
                   for task in card.trajectory_refs):
                return "candidate training retest produced no repair.tcl or an empty file"


class SingleCandidate(DefaultConflict):
    """Keep one complete proposal; let native acceptance judge the winner."""

    def __init__(self, runner, tasks):
        super().__init__()
        self.runner, self.tasks = runner, tuple(tasks)

    def resolve(self, artifact, cards):
        if not cards:
            return [], 0

        def rank(card):
            candidate = artifact.apply(card.diff)
            score = self.verifier.full_eval(candidate)
            sha = harness_sha256(candidate.state)
            with self.runner._lock:
                rows = [self.runner.search_results.get((sha, task.id), {}) for task in self.tasks]
            times = [r.get("agent_elapsed_seconds") for r in rows if r.get("score") == 1]
            # Missing/invalid timings cannot establish a speed advantage.
            seconds = (sum(times) if times and all(r.get("score") in (0, 1) for r in rows)
                       and all(isinstance(t, (int, float)) and not isinstance(t, bool)
                       and math.isfinite(t) and t >= 0 for t in times) else math.inf)
            return score, -seconds

        chosen = max(cards, key=rank)
        return [chosen], len(cards) - 1


def compare_default_trials(before, after):
    """Use DefaultAcceptance on fresh test evidence, without training pseudo-counts."""
    if [r["task_id"] for r in before] != [r["task_id"] for r in after]:
        raise ValueError("compare the same tasks in the same order")
    base, candidate = summarize_trials(before), summarize_trials(after)
    decision = DefaultAcceptance.from_config(AggregatorConfig()).accept(MergeContext(
        artifact=SimpleNamespace(version=1), candidate=None, cards=(),
        base_counts=(base["passed_count"], len(before) - base["passed_count"]),
        cand_counts=(candidate["passed_count"], len(after) - candidate["passed_count"])))
    return {"rule": DEFAULT_RULE, "passed": decision.accept,
            "p_improve": decision.p_improve, "detail": decision.detail,
            "baseline_mean": base["mean"], "candidate_mean": candidate["mean"],
            "baseline_passed_seconds": base["passed_seconds"],
            "candidate_passed_seconds": candidate["passed_seconds"],
            "per_task": [{"task_id": old["task_id"], "baseline_score": old["score"],
                          "candidate_score": new["score"],
                          "baseline_seconds": old.get("agent_elapsed_seconds"),
                          "candidate_seconds": new.get("agent_elapsed_seconds")}
                         for old, new in zip(before, after)],
            "no_task_regression": all(new["score"] >= old["score"] for old, new in zip(before, after)),
            "speed_improved": (base["passed_seconds"] is not None
                               and candidate["passed_seconds"] is not None
                               and candidate["passed_count"] == base["passed_count"]
                               and candidate["passed_seconds"] < base["passed_seconds"])}
