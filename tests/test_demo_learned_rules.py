"""#927: `demo --algorithm rrsi` must say what it learned in words.

The rrsi demo state is a mapping of internal rule ids to rule text, and the
human footer (and ``--json``'s ``learned``) printed that mapping as a Python
dict -- ``state -> {'ra4bfacbc48': 'COLUMN: amount'}`` -- so a reader sees an
internal id instead of the rule, while ``show`` renders the same run as text.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

from agentdescent import cli, demo


def _run_demo(tmp_path, *extra):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    buf = io.StringIO()
    argv = ["--store", str(tmp_path / "runs"), "demo",
            "--dir", str(tmp_path / "work"), "--algorithm", "rrsi", *extra]
    with redirect_stdout(buf):
        code = cli.main(argv)
    return code, buf.getvalue()


def test_rrsi_demo_learned_line_names_the_rule_not_the_state(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "home"))
    code, out = _run_demo(tmp_path)
    assert code == 0, out
    learned_line = [ln for ln in out.splitlines() if ln.startswith("what it learned:")]
    assert learned_line, out
    line = learned_line[0]
    assert line == "what it learned:  rules -> 'COLUMN: amount'", line
    # the internal rule id and the dict repr must not reach the reader
    assert "ra4bfacbc48" not in out, out
    assert "state -> {" not in out, out
    assert "'COLUMN: amount'" in out


def test_rrsi_demo_json_learned_names_the_rule_not_the_state(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "home"))
    code, out = _run_demo(tmp_path, "--json")
    assert code == 0, out
    payload = json.loads(out)
    assert payload["learned"] == "rules -> 'COLUMN: amount'", payload["learned"]
    assert "ra4bfacbc48" not in json.dumps(payload), payload["learned"]


def test_learned_summary_joins_several_rules_without_ids():
    state = {"ra4bfacbc48": "COLUMN: amount", "r0011223344": "COLUMN: id"}
    summary = demo.learned_summary(state, kind="text")
    assert summary == "rules -> 'COLUMN: amount | COLUMN: id'", summary
    assert "ra4bfacbc48" not in summary
    assert "{" not in summary


def test_learned_summary_caps_a_long_rule_list_with_a_count():
    state = {"r%010d" % i: "RULE: %d" % i for i in range(5)}
    summary = demo.learned_summary(state, kind="text")
    assert summary == "rules -> 'RULE: 0 | RULE: 1 (+3 more)'", summary
    assert "r0000000000" not in summary
