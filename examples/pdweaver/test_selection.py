"""Offline checks for correctness-first selection and retained successful traces."""
import json

import pytest

from agentdescent import AggregatorConfig, Task, evolve
from agentdescent.policies import Policies

from .experiment import TrialRunner, evaluate_final, reward
from .harness import LoggedFileTree, SKILL_KEY
from .records import RunRecords
from .selection import SuccessThenSpeed, compare_trials


SKILL = "---\nname: innovus-eco-closure-mcp\ndescription: Repair and verify timing.\n---\nRead task.md.\n"


def row(task, score, seconds):
    return {"task_id": task, "score": score, "agent_elapsed_seconds": seconds}


@pytest.mark.parametrize("before,after,expected", [
    ([row("a", 0, 1)], [row("a", 1, 100)], True),
    ([row("a", 1, 100)], [row("a", 0, 1)], False),
    ([row("a", 1, 100)], [row("a", 1, 50)], True),
    ([row("a", 1, 50)], [row("a", 1, 100)], False),
    ([row("a", 1, 50)], [row("a", 1, 50)], False),
    ([row("a", 0, 100)], [row("a", 0, 1)], False),
    ([row("a", 1, None)], [row("a", 1, 1)], False),
    ([row("a", 1, 5)], [row("a", 1, float("nan"))], False),
    ([row("a", 1, 5)], [row("a", 1, -1)], False),
    ([row("a", 1, 10), row("b", 0, 10)],
     [row("a", 0, 1), row("b", 1, 1)], False),
])
def test_correctness_before_speed(before, after, expected):
    assert compare_trials(before, after)["passed"] is expected


def test_explicit_score_gain_still_required():
    assert not compare_trials([row("a", 1, 100)], [row("a", 1, 1)], min_gain=0.1)["passed"]
    with pytest.raises(ValueError, match="same tasks"):
        compare_trials([row("a", 1, 100)], [row("b", 1, 1)])


def test_speed_is_not_compared_across_different_passed_tasks(tmp_path):
    from types import SimpleNamespace

    artifact = SimpleNamespace(apply=lambda diff: diff.diff_id)
    cards = [SimpleNamespace(diff=SimpleNamespace(diff_id=name, author=name)) for name in ("first", "second")]
    policy = SuccessThenSpeed(None, [Task("a", "a"), Task("b", "b")], RunRecords(tmp_path))

    def measure(value):
        scores = [0, 0] if value is artifact else ([1, 0] if value == "first" else [0, 1])
        return [{**row(task, score, 100 if value == "first" else 1),
                 "skill_sha256": "hash", "trial_id": task}
                for task, score in zip(("a", "b"), scores)]

    policy.measure = measure
    survivors, dropped = policy.resolve(artifact, cards)
    assert survivors == [cards[0]] and dropped == 1


@pytest.mark.parametrize("broken_fast", [False, True])
def test_three_successful_workers_choose_fastest_on_same_validation_tasks(tmp_path, broken_fast):
    records = RunRecords(tmp_path / "records")
    initial = {SKILL_KEY: SKILL}
    strategy = LoggedFileTree(initial, records)
    runner = TrialRunner(records, tmp_path / "workspaces", offline=True)
    durations = {"baseline": 100, "slow": 80, "fast": 20, "medium": 50}

    def execute(task, skill, workspace, evidence, output):
        label = next((name for name in durations if "\n" + name in skill), "baseline")
        passed = not (broken_fast and label == "fast" and task.id == "val-3")
        output.update(status="PASS" if passed else "FAIL", score=float(passed), skill_read=True,
                      agent_elapsed_seconds=durations[label], feedback="verified")

    runner._execute = execute
    train = [Task(name, "repair", {"split": "train"}) for name in ("slow", "fast", "medium")]
    val = [Task("val-" + str(i), "repair", {"split": "val"}) for i in range(4)]
    policy = SuccessThenSpeed(runner, val, records)

    def propose(rendered, task, output, score):
        assert score == 1.0  # Successful workers must still get to propose speed improvements.
        return "<EDITS>" + json.dumps({"edits": [{"path": SKILL_KEY, "content": SKILL + "\n" + task.id}]}) + "</EDITS>"

    result = evolve(train + val, reward, run=runner, propose=propose, strategy=strategy,
                    artifact_id="pdweaver-skill", repo_path=str(records.root / "ledger"),
                    rounds=1, n_workers=3, max_concurrency=3, eval_concurrency=2,
                    held_out_frac=4 / 7, shuffle=False, self_verify=False, solved_threshold=1.1,
                    cheap_eval_tasks=len(val), policies=Policies(conflict=policy, acceptance=policy),
                    agg_config=AggregatorConfig(batch_trigger=1, max_wait_rounds=1,
                                                trust_region_ops=1), verbose=False)
    assert not result.error
    assert result.state[SKILL_KEY] == SKILL + ("\nmedium" if broken_fast else "\nfast")
    choices = [json.loads(line) for line in (records.root / "selection.jsonl").read_text().splitlines()]
    selection = next(item for item in choices if item["stage"] == "rank")
    assert len(selection["candidates"]) == 3
    assert selection["candidates"][selection["selected_index"]]["passed_seconds"] == (200 if broken_fast else 80)
    successes = [json.loads(line) for line in (records.root / "successful_trials.jsonl").read_text().splitlines()]
    assert len(successes) >= 19 - int(broken_fast)  # 3 train + 4 versions x 4 fixed validation tasks.
    assert all((records.root / item["skill_file"]).is_file() for item in successes)
    trials = [json.loads(line) for line in (records.root / "trials.jsonl").read_text().splitlines()]
    evaluations = [(r["skill_sha256"], r["task_id"]) for r in trials if r["split"] == "val"]
    assert len(evaluations) == len(set(evaluations)) == 16  # Ranking/acceptance reuse paid evaluations.
    test = [Task("test", "repair", {"split": "test"})]
    final = evaluate_final(runner, strategy, initial, result.state, test)
    assert final["passed"] and final["speed_improved"] and not final["adoption_eligible"]


def test_speed_adoption_rechecks_sealed_timings(tmp_path):
    from .release import _verify_test_gate, seal_evidence

    records = RunRecords(tmp_path)
    rows = [{"task_id": "a"}]
    for role, seconds, sha in (("baseline", 100, "old"), ("candidate", 50, "new")):
        value = {**row("a", 1, seconds), "trial_id": role, "phase": "test_" + role,
                 "skill_sha256": sha}
        rows[0][role] = value
        records.write_json("trials/" + role + "/output.json", value)
    assessment = {**compare_trials([rows[0]["baseline"]], [rows[0]["candidate"]]),
                  "rows": rows, "offline": False, "adoption_eligible": True, "baseline_sha256": "old"}
    manifest = {"plan": {"offline": False}, "split": {"test": ["a"], "train": [], "val": []}}
    seal_evidence(tmp_path)
    _verify_test_gate(tmp_path, manifest, assessment, "old", "new")
    assessment["rows"][0]["candidate"]["agent_elapsed_seconds"] = 1
    with pytest.raises(ValueError, match="recorded trial"):
        _verify_test_gate(tmp_path, manifest, assessment, "old", "new")


@pytest.mark.parametrize("score", [0.0, 1.0])
def test_proposal_prioritizes_success_and_uses_timeline(tmp_path, monkeypatch, score):
    from . import pdweaver_skill_rsi as entry

    records = RunRecords(tmp_path)
    events = {"events": [
        {"event_seq": 1, "type": "model.start", "data": {"turn_id": "m1"}},
        {"event_seq": 2, "type": "llm_output", "data": {"content": "Check timing before ECO"}},
        {"event_seq": 3, "type": "tool", "data": {"name": "session_execute",
                                                    "args": {"code": "report_timing"},
                                                    "result": "SUCCEEDED"}},
        {"event_seq": 4, "type": "model.end", "data": {"turn_id": "m1"}},
    ]}
    records.write_json("trials/trial-1/agent/events.json", events)
    # Private acceptance internals must stay out of reflection.
    records.write_text("trials/trial-1/verifier/innovus.log", "PRIVATE_JUDGE_INTERNALS")
    prompts = []

    def complete(prompt):
        prompts.append(prompt)
        return "<EDITS>{\"edits\": []}</EDITS>"

    monkeypatch.setattr(entry, "openai_compatible", lambda *args, **kwargs: complete)
    args = entry.build_parser().parse_args(["--reflect-model", "fake-model"])
    strategy = LoggedFileTree({SKILL_KEY: SKILL}, records)
    proposer = entry._build_proposer(args, strategy, entry.Usage())
    output = json.dumps({**row("a", score, 70), "trial_id": "trial-1", "split": "train",
                         "agent_feedback": "agent details " * 1000, "feedback": "TRUSTED_TIMING_CHECK"})
    proposer(strategy.render(strategy.initial()), Task("a", "repair"), output, score)
    prompt = prompts[0]
    assert prompt.index("Primary goal:") < prompt.index("Secondary goal:")
    assert "pass official verification (reward=1)" in prompt
    assert "reduce solving time while preserving reward=1" in prompt
    assert "did poorly" not in prompt
    assert ("Preserve correctness" if score == 1 else "Fix correctness first") in prompt
    assert "70" in prompt
    assert prompt.index("Check timing before ECO") < prompt.index("report_timing")
    assert "session_execute" in prompt and "SUCCEEDED" in prompt
    assert "PRIVATE_JUDGE_INTERNALS" not in prompt
    assert "TRUSTED_TIMING_CHECK" in prompt
    assert (tmp_path / "trials/trial-1/reflection_input.txt").is_file()
    assert json.loads((tmp_path / "trials/trial-1/agent/events.json").read_text()) == events


def test_trajectory_excerpt_is_bounded_and_test_is_excluded(tmp_path):
    from .trajectory import reflection_input

    records = RunRecords(tmp_path)
    events = {"events": [{"event_seq": i, "type": "llm_output", "data": {"content": str(i) * 10000}}
                         for i in range(50)]}
    records.write_json("trials/t/agent/events.json", events)
    value = {"trial_id": "t", "split": "train", "score": 1}
    text = reflection_input(json.dumps(value), records)
    assert len(text) <= 24000 and "middle events omitted" in text
    with pytest.raises(ValueError, match="test trajectories"):
        reflection_input(json.dumps({**value, "split": "test"}), records)


def test_runner_measures_solving_before_export_and_cleanup(tmp_path, monkeypatch):
    from . import runner
    # Reuse the existing offline HTTP fixture without changing files outside this example.
    from tests.test_pdweaver_runner import FakeServices

    workspace = tmp_path / "workspace"
    skill = workspace / ".pdweaver/skills/innovus-eco-closure-mcp/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(SKILL)
    (workspace / "task.md").write_text("Repair")
    fake = FakeServices(workspace)
    original = fake.request

    def request(origin, method, path, body=None, **kwargs):
        if method == "POST" and path.endswith("/tasks"):
            fake.clock += 30
        if "/history?" in path or method == "DELETE":
            fake.clock += 100
        return original(origin, method, path, body, **kwargs)

    fake.request = request
    monkeypatch.setattr(runner, "_JsonClient", fake.client)
    monkeypatch.setattr(runner.time, "monotonic", lambda: fake.clock)
    result = runner.run_pdweaver("http://127.0.0.1:8877", workspace, tmp_path / "evidence", timeout=600)
    assert result["solve_seconds"] == 30
    assert result["elapsed_seconds"] > 400
