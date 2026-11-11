"""The review gate: does a pull request's tip carry a reviewer PASS?

A PASS is what lets a T0/T1 PR auto-merge and what a T2/T3 PR needs before
Danyang's click (AGENTS.md › Merge policy), so the parser must not accept a
PASS for another commit or a PASS a later FAIL replaced. A PASS with no
evidence still counts, but it is marked ``weak: no Ran:/Not run:`` so an
evidence-less PASS is visible in the result and in the rendered report.
"""

import importlib.util
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "review-gate.yml"
POLICY = json.loads((ROOT / ".github" / "agent" / "review-policy.json").read_text())
HEAD = "0123456789abcdef0123456789abcdef01234567"
WEAK = "no Ran:/Not run:"


def _mod():
    spec = importlib.util.spec_from_file_location("review_gate", ROOT / ".github" / "scripts" / "review_gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rg = _mod()


def report(verdict="PASS", tip=HEAD[:12], ran=("pytest -q → pass",), not_run=True):
    lines = [f"Tip SHA: `{tip}`", "Ran:"] + [f"  - {r}" for r in ran]
    if not_run:
        lines += ["Not run:", "  - Ark real-model run — no code path to a model changed"]
    return "\n".join(lines + [f"**Verdict: {verdict}**"])


def c(body, login="Birfy", at="2026-10-19T10:00:00Z", kind="comment"):
    return {"login": login, "body": body, "at": at, "kind": kind}


def test_policy_names_birfy_with_self_review():
    assert POLICY["reviewers"] == ["Birfy"] and POLICY["selfReview"] == ["Birfy"]


def test_parse_report_takes_the_last_block_and_strips_markdown():
    body = report("FAIL", tip="aaaaaaa") + "\n\nUpdated:\n" + report("PASS")
    p = rg.parse_report(body)
    assert p == {"tip": HEAD[:12], "verdict": "PASS", "ran": ["- pytest -q → pass"], "hasNotRun": True}
    assert rg.parse_report("just a comment") == {"tip": None, "verdict": None, "ran": [], "hasNotRun": False}


def test_a_self_pass_at_the_tip_counts():
    r = rg.decide(HEAD, "Birfy", [c(report())], POLICY)
    assert r["ok"] and r["by"] == "Birfy"


def test_a_pass_for_another_commit_does_not_count():
    r = rg.decide(HEAD, "Birfy", [c(report(tip="fedcba9876"))], POLICY)
    assert not r["ok"] and "not the tip" in r["reason"]


def test_only_listed_reviewers_count_and_authors_need_self_review():
    assert not rg.decide(HEAD, "HugoXK", [c(report(), login="someone")], POLICY)["ok"]
    assert rg.decide(HEAD, "HugoXK", [c(report(), login="Birfy")], POLICY)["ok"]
    no_self = dict(POLICY, selfReview=[])
    r = rg.decide(HEAD, "Birfy", [c(report())], no_self)
    assert not r["ok"] and "own author" in r["reason"]


def test_newest_report_at_the_tip_wins():
    early_pass = c(report("PASS"), at="2026-10-19T10:00:00Z")
    later_fail = c(report("FAIL"), at="2026-10-19T11:00:00Z")
    assert not rg.decide(HEAD, "Birfy", [early_pass, later_fail], POLICY)["ok"]
    assert rg.decide(HEAD, "Birfy", [later_fail, c(report("PASS"), at="2026-10-19T12:00:00Z")], POLICY)["ok"]
    # Same timestamp: the later one in API order wins.
    same = "2026-10-19T10:00:00Z"
    assert not rg.decide(HEAD, "Birfy", [c(report("PASS"), at=same), c(report("INC"), at=same)], POLICY)["ok"]


def test_a_pass_without_evidence_counts_but_is_marked_weak():
    for body in (report(ran=()), report(not_run=False)):
        r = rg.decide(HEAD, "Birfy", [c(body)], POLICY)
        assert r["ok"] and r["weak"] == WEAK
        assert WEAK in rg.render(r, 7, HEAD, "Birfy")
    strong = rg.decide(HEAD, "Birfy", [c(report())], POLICY)
    assert strong["ok"] and not strong["weak"]


def test_a_verdict_above_the_tip_line_counts():
    # #774, 2026-11-09: Verdict first, then the Tip SHA it is about.
    body = "\n".join([
        "**Verdict: PASS**",
        "",
        f"Tip SHA: `{HEAD}`",
        "Ran:",
        "  - pytest -q → pass",
        "Not run:",
        "  - Ark real-model run — no code path to a model changed",
    ])
    parsed = rg.parse_report(body)
    assert parsed["tip"] == HEAD and parsed["verdict"] == "PASS"
    r = rg.decide(HEAD, "Birfy", [c(body)], POLICY)
    assert r["ok"] and r["by"] == "Birfy"


def test_a_verdict_carrying_its_tip_inline_counts():
    # #776/#782, 2026-11-09: `Verdict: PASS (tip b0a30224)`, no Tip SHA line.
    head = "b0a30224" + HEAD[8:]
    body = "\n".join([
        "Ran:",
        "  - pytest -q → pass",
        "Not run:",
        "  - Ark real-model run — no code path to a model changed",
        "",
        "**Verdict: PASS (tip b0a30224)**",
    ])
    parsed = rg.parse_report(body)
    assert parsed["tip"] == "b0a30224" and parsed["verdict"] == "PASS"
    r = rg.decide(head, "HugoXK", [c(body)], POLICY)
    assert r["ok"] and r["by"] == "Birfy" and r["tip"] == "b0a30224"


def test_a_verdict_above_a_bare_tip_label_counts():
    # #905, 2026-11-09: `Verdict: PASS`, then a `Tip: <sha>` line of its own, and
    # `What I ran (...)` as the evidence list.
    body = "\n".join([
        "Verdict: PASS",
        "",
        f"Tip: {HEAD}",
        "",
        "What I ran (shared venv):",
        "- tests/test_mcp.py",
        "- tests/test_demo.py",
        "",
        "Not run:",
        "  - Ark real-model run — no model path changed",
    ])
    parsed = rg.parse_report(body)
    assert parsed["tip"] == HEAD and parsed["verdict"] == "PASS"
    assert parsed["ran"] == ["- tests/test_mcp.py", "- tests/test_demo.py"]
    r = rg.decide(HEAD, "HugoXK", [c(body)], POLICY)
    assert r["ok"] and r["by"] == "Birfy" and not r["weak"]


def test_a_seven_hex_tip_that_is_not_the_head_stays_not_pass():
    body = "\n".join([
        "Ran:",
        "  - pytest -q → pass",
        "Not run:",
        "  - Ark real-model run — no code path to a model changed",
        "",
        "**Verdict: PASS (tip abcdef0)**",
    ])
    assert not rg.decide(HEAD, "HugoXK", [c(body)], POLICY)["ok"]


def test_a_tip_in_another_comment_does_not_count():
    # The verdict and its tip must be in one report: no cross-body stitching.
    reports = [
        c("**Verdict: PASS**", at="2026-11-09T10:00:00Z"),
        c(f"Tip SHA: `{HEAD}`", at="2026-11-09T10:01:00Z"),
    ]
    assert not rg.decide(HEAD, "HugoXK", reports, POLICY)["ok"]


def test_review_bodies_count_like_comments():
    assert rg.decide(HEAD, "HugoXK", [c(report(), kind="review")], POLICY)["ok"]


def test_render_is_report_only():
    r = rg.decide(HEAD, "Birfy", [c(report())], POLICY)
    text = rg.render(r, 7, HEAD, "Birfy")
    assert "PASS at 0123456789ab" in text and "Report only" in text


def test_the_workflow_stays_report_only():
    text = WORKFLOW.read_text(encoding="utf-8")
    wf = yaml.safe_load(text)
    on = wf.get("on", wf.get(True))
    assert set(on) == {"pull_request", "pull_request_review", "issue_comment"}, "never pull_request_target"
    assert wf["permissions"] == {"contents": "read", "issues": "read", "pull-requests": "read"}
    job = wf["jobs"]["report"]
    assert job["continue-on-error"] is True
    assert job["steps"][-1]["continue-on-error"] is True
    assert "${{ secrets." not in text
    assert "${{" not in job["steps"][-1]["run"], "values reach the shell only through env"


def test_the_pr_template_has_the_verifier_lines():
    tpl = (ROOT / ".github" / "pull_request_template.md").read_text()
    for needle in ("Fixes #", "Tip SHA:", "Ran:", "Not run:"):
        assert needle in tpl
