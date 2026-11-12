"""Compare fixed tasks by verified success first, then measured solving time."""
import math

from agentdescent.policies import AcceptDecision

from .harness import SKILL_KEY
from .records import sha256_text


RULE = "no task regression; more passes first; equal passes prefer shorter successful solve time"


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
    """Speed only breaks ties on the same passed tasks; missing timing never wins."""
    if [r["task_id"] for r in before] != [r["task_id"] for r in after]:
        raise ValueError("compare the same tasks in the same order")
    if not math.isfinite(min_gain) or min_gain < 0:
        raise ValueError("minimum gain must be finite and nonnegative")
    base, candidate = summarize_trials(before), summarize_trials(after)
    no_loss = all(new["score"] >= old["score"] for old, new in zip(before, after))
    quality = candidate["mean"] > base["mean"] + min_gain
    faster = (no_loss and candidate["passed_count"] == base["passed_count"]
              and base["passed_seconds"] is not None and candidate["passed_seconds"] is not None
              and candidate["passed_seconds"] < base["passed_seconds"])
    passed = no_loss and (quality or (min_gain == 0 and faster))
    return {"baseline_mean": base["mean"], "candidate_mean": candidate["mean"],
            "baseline_passed_seconds": base["passed_seconds"],
            "candidate_passed_seconds": candidate["passed_seconds"],
            "no_task_regression": no_loss, "speed_improved": faster,
            "min_gain": min_gain, "passed": passed, "rule": RULE}


class SuccessThenSpeed:
    """Single-file conflict selection and acceptance, using the full validation set."""

    def __init__(self, runner, tasks, records):
        self.runner, self.tasks, self.records = runner, list(tasks), records

    def measure(self, artifact):
        # Use the engine's evaluator/cache, so budgets and trial records stay intact.
        artifact.score(self.tasks)# 已完成评测
        sha = sha256_text(artifact.state[SKILL_KEY])
        with self.runner._lock:
            return [dict(self.runner.search_results[(sha, task.id)]) for task in self.tasks]

    def resolve(self, artifact, cards):
        if not cards:
            return [], 0
        #评估当前版本
        baseline = self.measure(artifact)
        # 评估所有候选，candidates：依次保存 H1、H2、H3 的逐题评测结果。
        candidates = [self.measure(artifact.apply(card.diff)) for card in cards]
        comparisons = [compare_trials(baseline, rows) for rows in candidates]
        eligible = [i for i, c in enumerate(comparisons) if c["no_task_regression"]]

        # Even an entirely regressing batch reaches accept(), which records its rejection.
        #先选通过题数最多的候选
        chosen = max(eligible or range(len(cards)),
                     key=lambda i: summarize_trials(candidates[i])["passed_count"])
        #通过情况相同时，继续比较耗时
        for i in eligible:
            # Equal pass counts on DIFFERENT tasks do not establish a speed improvement.
            if compare_trials(candidates[chosen], candidates[i])["passed"]:
                chosen = i  
        #保存选择记录
        self.records.append("selection.jsonl", {
            "stage": "rank", "rule": RULE, "task_ids": [t.id for t in self.tasks],
            "selected_index": chosen,
            "candidates": [{"author": card.diff.author, "diff_id": card.diff.diff_id,
                            "skill_sha256": rows[0]["skill_sha256"],
                            "trial_ids": [r["trial_id"] for r in rows],
                            **summarize_trials(rows), **comparison}
                           for card, rows, comparison in zip(cards, candidates, comparisons)],
        })
        #返回选中的证据卡
        return [cards[chosen]], len(cards) - 1

    def accept(self, ctx):
        before, after = self.measure(ctx.artifact), self.measure(ctx.candidate)
        decision = compare_trials(before, after)
        accepted = ctx.comparable() and decision["passed"]
        self.records.append("selection.jsonl", {
            "stage": "accept", "accepted": accepted, **decision,
            "baseline_trials": [r["trial_id"] for r in before],
            "candidate_trials": [r["trial_id"] for r in after],
        })
        return AcceptDecision(accepted, category="committed" if accepted else "below-threshold",
                              detail=RULE, p_improve=float(accepted),
                              observed_delta=decision["candidate_mean"] - decision["baseline_mean"])
