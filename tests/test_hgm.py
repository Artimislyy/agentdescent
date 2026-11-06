"""HGM's expand-vs-evaluate scheduler over a pure JSON tree."""

import json

import pytest

from agentdescent import cli
from agentdescent.hgm import HGM, HGMConfig, HGMError, HGMNode, load_hgm_tree


def _tree(**overrides):
    config = HGMConfig(alpha=0.5, max_task_evals=10, seed=0,
                       eval_random_level=0.0, **overrides)
    return HGM(config, ["t1", "t2", "t3", "t4", "t5"])


def test_initial_tree_evaluates_when_nothing_is_eligible():
    tree = _tree()
    action = tree.next_action()
    assert action["action"] == "evaluate"
    assert action["node_id"] == "initial"
    assert action["task"] == "t1"


def test_expand_when_budget_allows_and_a_node_is_eligible():
    tree = _tree()
    tree.record_evaluation("initial", "t1", 1.0)
    # n_task_evals=1, nodes=1 -> 1**0.5 >= 0 -> expand
    action = tree.next_action()
    assert action["action"] == "expand"
    assert action["node_id"] == "initial"


def test_evaluate_after_a_child_is_added_and_task_is_not_reused():
    tree = _tree()
    tree.record_evaluation("initial", "t1", 1.0)
    tree.record_expansion("initial", "child", utility_measures=(1.0,),
                          submitted_tasks=("t2",))
    # 1**0.5 = 1 < len(nodes)-1 = 1? equal -> expand; grow one more node.
    tree.record_expansion("initial", "child2")
    action = tree.next_action()
    assert action["action"] == "evaluate"
    node = tree.get(action["node_id"])
    assert action["task"] not in node.submitted_tasks
    tree.record_evaluation(action["node_id"], action["task"], 0.0)
    assert tree.n_task_evals == 2


def test_task_and_utility_are_validated():
    tree = _tree()
    with pytest.raises(HGMError):
        tree.record_evaluation("initial", "unknown", 1.0)
    with pytest.raises(HGMError):
        tree.record_evaluation("initial", "t1", 1.5)
    tree.record_evaluation("initial", "t1", 1.0)
    with pytest.raises(HGMError):
        tree.record_evaluation("initial", "t1", 0.0)
    with pytest.raises(HGMError):
        HGMNode("x", utility_measures=(2.0,))


def test_stop_at_budget_and_report_cmp():
    tree = HGM(HGMConfig(max_task_evals=1, seed=0), ["t1", "t2"])
    tree.record_evaluation("initial", "t1", 1.0)
    assert tree.next_action()["action"] == "stop"
    report = tree.report()
    assert report["n_task_evals"] == 1
    assert report["nodes"][0]["num_evals"] == 1
    assert report["nodes"][0]["cmp"] == 1.0


def test_json_round_trip_and_cli(tmp_path, capsys):
    tree = _tree()
    tree.record_evaluation("initial", "t1", 1.0)
    tree.record_expansion("initial", "child", utility_measures=(0.0,))
    path = tmp_path / "hgm.json"
    path.write_text(json.dumps(tree.to_dict()), encoding="utf-8")

    loaded = load_hgm_tree(str(path))
    assert loaded.report()["nodes"] == tree.report()["nodes"]

    assert cli.main(["hgm", "next", "--tree", str(path), "--json"]) == 0
    action = json.loads(capsys.readouterr().out)
    assert action["action"] in ("expand", "evaluate", "stop")

    assert cli.main(["hgm", "report", "--tree", str(path), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["schema_version"] == 1
    assert len(report["nodes"]) == 2


def test_bad_tree_is_an_input_error(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    assert cli.main(["hgm", "next", "--tree", str(path), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_nested_round_trip_with_child_before_parent():
    tree = _tree()
    tree.record_evaluation("initial", "t1", 1.0)
    tree.record_expansion("initial", "zebra", utility_measures=(1.0,))
    tree.record_expansion("zebra", "apple", utility_measures=(0.0,))
    loaded = HGM.from_dict(tree.to_dict())
    assert loaded.get("apple").parent_id == "zebra"
    assert loaded.n_task_evals == tree.n_task_evals


def test_n_task_evals_mismatch_and_bad_cool_down_are_refused():
    with pytest.raises(HGMError):
        HGM.from_dict({"schema_version": 1, "config": {},
                       "total_tasks": ["t1"], "n_task_evals": 5,
                       "nodes": [{"node_id": "initial", "parent_id": None}]})
    with pytest.raises(HGMError):
        HGMConfig(cool_down="yes")


def test_expand_fallthrough_reason_names_the_real_cause():
    tree = _tree()
    tree.record_evaluation("initial", "t1", 0.0)
    action = tree.next_action()
    assert action["action"] == "evaluate"
    assert "no expandable node" in action["reason"]
