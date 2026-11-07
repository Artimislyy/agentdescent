"""`agentdescent demo`: the one command a newcomer runs before anything else.

If this breaks, the first thing a new user sees is a failure, so it is tested
like a feature rather than a sample.
"""

import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stdout

import pytest

from agentdescent import cli, demo, runstore

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_build_writes_a_skill_that_is_wrong_on_purpose(tmp_path):
    spec = demo.build(str(tmp_path))
    rules = tmp_path / demo.DEMO_SKILL / "references" / "rules.md"
    assert (tmp_path / demo.DEMO_SKILL / "SKILL.md").exists()
    assert rules.read_text().strip() == "COLUMN: id"     # the run has to fix this
    rows = [json.loads(l) for l in (tmp_path / "cases.jsonl").read_text().splitlines()]
    assert len(rows) == 12
    assert "data.csv" in rows[0]["fixtures"] and rows[0]["gold"].isdigit()
    assert json.loads((tmp_path / "spec.json").read_text()) == spec


def test_the_demo_spec_needs_no_credentials_and_no_allowlist_widening(tmp_path):
    spec = demo.build(str(tmp_path))
    # both refs live inside the package, so `allow` stays empty -- a newcomer
    # never has to widen the import allowlist to run the demo
    assert spec["agent"]["ref"].startswith("agentdescent.")
    assert spec["reflect"]["ref"].startswith("agentdescent.")
    assert "allow" not in spec
    from agentdescent import EvolveSpec, compose

    comp = compose(EvolveSpec.from_dict(spec))
    assert comp.kwargs["rounds"] == 4 and len(comp.tasks) == 12


def test_the_offline_agent_obeys_the_skill_it_is_given(tmp_path):
    """It is a real workspace agent: the skill on disk changes its answer."""
    from agentdescent import Task
    from agentdescent.filetree import load_tree
    from agentdescent.runners import tree_runner
    from agentdescent.treestrategy import FileTree

    demo.build(str(tmp_path))
    tree = load_tree(str(tmp_path / demo.DEMO_SKILL))
    strategy = FileTree(tree)
    run = tree_runner(demo.offline_agent(), layout="claude_skill",
                      name=demo.DEMO_SKILL, prompt_template="{prompt}")
    task = Task(id="t", prompt="What is the total?",
                meta={"gold": "30", "fixtures": {"data.csv": "id,amount\n1,10\n2,20\n"}})
    assert run(strategy.render(tree), task) == "3"          # sums `id`: 1 + 2
    fixed = dict(tree, **{"references/rules.md": "COLUMN: amount\n"})
    assert run(strategy.render(fixed), task) == "30"        # sums `amount`


def test_the_offline_reflector_proposes_the_fix_from_what_it_was_shown():
    prompt = ("--- references/rules.md ---\nCOLUMN: id\n"
              "--- other ---\nTASK THE AGENT WAS GIVEN: ...")
    out = demo.offline_reflector(prompt)
    assert out.startswith("<EDITS>") and out.endswith("</EDITS>")
    payload = json.loads(out[len("<EDITS>"):-len("</EDITS>")])
    assert payload["edits"] == [{"path": "references/rules.md",
                                 "content": "COLUMN: amount\n"}]
    # it reads the prompt rather than emitting a constant, so a prompt without
    # the file still yields a valid edit
    assert "COLUMN: amount" in demo.offline_reflector("nothing here")


def test_the_demo_command_runs_a_real_evolution_and_fixes_the_skill(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "home"))
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(["--store", str(tmp_path / "runs"), "demo",
                         "--dir", str(tmp_path / "work")])
    out = buf.getvalue()
    assert code == 0, out
    # #708: seed starts wrong (COLUMN: id) so the printed line shows the lift.
    assert "held-out reward: 0.000 -> 1.000" in out, out
    assert "'COLUMN: amount'" in out, out
    assert "agentdescent apply" in out and "--dry-run" in out
    # the next-step footer must name a spec path that the init line it shows
    # actually writes (#484): bare init writes .agentdescent/<name>.evolve.json
    assert "agentdescent plan spec.json" in out
    assert "--out spec.json" in out

    # the run is in the store, and the user's skill on disk is untouched
    runs = runstore.list_runs(store=str(tmp_path / "runs"))
    assert len(runs) == 1 and runs[0].state == "done"
    rules = tmp_path / "work" / demo.DEMO_SKILL / "references" / "rules.md"
    assert rules.read_text().strip() == "COLUMN: id"


def test_demo_is_reachable_from_a_bare_install():
    """A newcomer's first command must work from the console script alone."""
    proc = subprocess.run([sys.executable, "-m", "agentdescent.cli", "--help"],
                          capture_output=True, text=True, cwd=ROOT, timeout=120)
    assert proc.returncode == 0
    assert "demo" in proc.stdout


def test_init_says_what_to_do_when_the_cases_file_is_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "s").mkdir()
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert cli.main(["init", str(tmp_path / "s"), "--out", "spec.json"]) == 0
    out = buf.getvalue()
    assert "create" in out and "cases.jsonl" in out
    assert "agentdescent demo" in out          # the way to see a working one


def test_the_demo_skill_is_a_valid_agent_skill(tmp_path):
    # #453: hosts drop a skill without name/description frontmatter, and a
    # skill_dir run on it turns the SKILL.md structural gate off.
    from agentdescent.skillspec import parse_skill_frontmatter, validate_skill_tree
    demo.build(str(tmp_path))
    text = (tmp_path / demo.DEMO_SKILL / "SKILL.md").read_text()
    assert validate_skill_tree({"SKILL.md": text}, root_name=demo.DEMO_SKILL) == []
    fm = parse_skill_frontmatter(text)
    assert fm["name"] == demo.DEMO_SKILL and fm["description"].strip()


def test_plan_on_the_demo_keeps_the_structural_gate_on(tmp_path):
    from agentdescent import EvolveSpec
    from agentdescent.cli import plan_payload
    spec = demo.build(str(tmp_path))
    payload = plan_payload(EvolveSpec.from_dict(spec).absolutise())
    blob = json.dumps(payload)
    assert "no-frontmatter" not in blob and "structural gate is off" not in blob


@pytest.mark.parametrize("name", demo.OFFLINE_ALGORITHMS)
def test_demo_algorithm_runs_each_offline_algorithm_end_to_end(tmp_path, monkeypatch, name):
    # #719: every name the demo accepts must actually fix the skill offline
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "home"))
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(["--store", str(tmp_path / "runs"), "demo",
                         "--dir", str(tmp_path / "work"), "--algorithm", name])
    out = buf.getvalue()
    assert code == 0, out
    assert f"algorithm: {name}" in out, out
    assert "held-out reward: 0.000 -> 1.000" in out, out
    spec = json.loads((tmp_path / "work" / "spec.json").read_text())
    assert spec["algorithm"] == name


def test_demo_algorithm_accepts_an_alias(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "home"))
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(["--store", str(tmp_path / "runs"), "demo",
                         "--dir", str(tmp_path / "work"),
                         "--algorithm", "Archive-Selection"])
    assert code == 0, buf.getvalue()
    assert "algorithm: archive_selection" in buf.getvalue()



def test_demo_json_emits_a_parseable_result(tmp_path, monkeypatch):
    # #862: --json was advertised but cmd_demo always printed human text.
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "home"))
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(["--store", str(tmp_path / "runs"), "demo",
                         "--dir", str(tmp_path / "work"),
                         "--algorithm", "ace", "--json"])
    out = buf.getvalue()
    assert code == 0, out
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["kind"] == "text"
    assert payload["algorithm"] == "ace"
    assert payload["initial_reward"] == 0.0
    assert payload["final_reward"] == 1.0
    assert payload["outcomes"].get("committed", 0) >= 1
    assert "COLUMN: amount" in payload["learned"]
    assert payload["run_id"]
    assert payload["plan"]["tasks"] == 12
    assert payload["plan"]["agent_calls_upper_bound"] >= 1
    assert any("show" in step for step in payload["next"])
    # human narrative must not leak into the JSON document
    assert "A text prompt that totals" not in out


def test_demo_algorithm_refuses_one_that_needs_a_real_model(tmp_path, capsys):
    # #845: evoskill has an explicit skip_reason (proposer protocol); other
    # unknown-to-offline names still use the generic refusal.
    code = cli.main(["--store", str(tmp_path / "runs"), "demo",
                     "--dir", str(tmp_path / "work"), "--algorithm", "evoskill"])
    err = capsys.readouterr().err
    assert code == 2
    assert "evoskill" in err and ("real model" in err or "offline demo" in err)
    assert "agentdescent algorithms run evoskill" in err
    assert not (tmp_path / "work").exists()
    assert not (tmp_path / "runs").exists() or not os.listdir(tmp_path / "runs")


def test_demo_algorithm_unknown_name_lists_the_real_ones(tmp_path, capsys):
    code = cli.main(["--store", str(tmp_path / "runs"), "demo",
                     "--dir", str(tmp_path / "work"), "--algorithm", "nope"])
    err = capsys.readouterr().err
    assert code == 2
    assert "unknown algorithm 'nope'" in err and "archive_selection" in err


def test_offline_text_agent_uses_last_column_match():
    # ACE/DGM keep the seed and append lessons; the last COLUMN wins (#845).
    prompt = (
        "COLUMN: id\n\n# Playbook\n## general\n- COLUMN: amount\n\n"
        "What is the total?\n```csv\nid,amount\n1,10\n2,20\n```"
    )
    assert demo.offline_text_agent(prompt) == "30"
    assert demo.offline_text_agent(
        "COLUMN: id\n\nWhat is the total?\n```csv\nid,amount\n1,10\n2,20\n```"
    ) == "3"


def test_offline_text_reflector_returns_rule_or_skillopt_json():
    assert demo.offline_text_reflector("propose a rule") == "COLUMN: amount"
    out = demo.offline_text_reflector('Return ONLY a JSON object with "edits"')
    payload = json.loads(out)
    assert payload["edits"] == [{
        "op": "replace", "target": "COLUMN: id", "content": "COLUMN: amount",
    }]


def test_build_text_fixture_for_text_only_cards(tmp_path):
    spec = demo.build(str(tmp_path), algorithm="gepa")
    assert spec["kind"] == "text" and spec["algorithm"] == "gepa"
    assert (tmp_path / "prompt.txt").read_text().strip() == "COLUMN: id"
    assert not (tmp_path / demo.DEMO_SKILL).exists()
    rows = [json.loads(l) for l in (tmp_path / "cases.jsonl").read_text().splitlines()]
    assert "```csv" in rows[0]["prompt"] and "fixtures" not in rows[0]


def test_demo_algorithm_refuses_evoskill_with_skip_reason(tmp_path, capsys):
    code = cli.main(["--store", str(tmp_path / "runs"), "demo",
                     "--dir", str(tmp_path / "work"), "--algorithm", "evoskill"])
    err = capsys.readouterr().err
    assert code == 2
    assert "evoskill" in err and "real model" in err
    assert "proposer/generator" in err or "algorithms run evoskill" in err
    assert not (tmp_path / "work").exists()


def test_skip_reason_only_for_listed_skips():
    assert demo.skip_reason("evoskill")
    assert demo.skip_reason("gepa") is None
    assert set(demo.OFFLINE_TEXT_ALGORITHMS).issubset(set(demo.OFFLINE_ALGORITHMS))


def test_demo_labels_itself_smoke_and_points_at_library_example(tmp_path, monkeypatch):
    """#847: demo stays a one-commit smoke; multi-round lives in skill_library."""
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "home"))
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(["--store", str(tmp_path / "runs"), "demo",
                         "--dir", str(tmp_path / "work")])
    out = buf.getvalue()
    assert code == 0, out
    assert "smoke trajectory" in out
    assert "skill_library_evolution" in out
