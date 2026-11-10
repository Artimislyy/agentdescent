"""Skill-bank lifecycle: outcome ledger, drift audit and retrieval."""

import json

import pytest

from agentdescent import cli
from agentdescent.skill_bank import SkillBank, SkillBankError, SkillRecord


def _bank(tmp_path):
    bank = SkillBank(str(tmp_path / "skills.json"))
    bank.add("good", "Always verify the total in cents.", tags=("money",))
    bank.add("bad", "Guess the total from the first number.")
    bank.add("mid", "Use a calculator for arithmetic.")
    for _ in range(5):
        bank.observe("good", success=True)
        bank.observe("bad", success=False)
    for index in range(5):
        bank.observe("mid", success=index < 3)
    return bank


def test_observe_and_reload(tmp_path):
    bank = _bank(tmp_path)
    record = bank.get("good")
    assert record.uses == 5
    assert record.successes == 5
    assert record.success_rate == 1.0
    assert record.last_used_at >= record.created_at

    again = SkillBank(str(tmp_path / "skills.json"))
    assert again.get("good").successes == 5
    assert again.get("bad").failures == 5


def test_audit_quarantines_below_the_baseline(tmp_path):
    bank = _bank(tmp_path)
    report = bank.audit(min_uses=5, apply=False)
    actions = {row["skill_id"]: row for row in report["actions"]}
    assert actions["good"]["action"] == "keep"
    assert actions["bad"]["action"] == "quarantine"
    assert actions["mid"]["action"] == "keep"
    assert report["applied"] is False
    assert bank.get("bad").status == "active"

    applied = bank.audit(min_uses=5, apply=True)
    assert applied["applied"] is True
    assert bank.get("bad").status == "quarantined"
    assert bank.get("mid").status == "active"
    assert bank.get("good").status == "active"


def test_insufficient_uses_is_reported_not_quarantined(tmp_path):
    bank = SkillBank(str(tmp_path / "skills.json"))
    bank.add("new", "A brand new skill.")
    bank.observe("new", success=True)
    report = bank.audit(min_uses=5)
    assert report["actions"][0]["action"] == "insufficient"


def test_search_skips_inactive_skills(tmp_path):
    bank = _bank(tmp_path)
    bank.set_status("bad", "quarantined")
    hits = bank.search("total", k=5)
    ids = [row["skill_id"] for row in hits["hits"]]
    assert "good" in ids
    assert "bad" not in ids


def test_bad_inputs_are_refused(tmp_path):
    bank = SkillBank(str(tmp_path / "skills.json"))
    with pytest.raises(SkillBankError):
        bank.add("x", "")
    with pytest.raises(SkillBankError):
        bank.observe("missing", success=True)
    with pytest.raises(SkillBankError):
        SkillRecord("x", "text", uses=1, successes=0, failures=0)
    with pytest.raises(SkillBankError):
        bank.audit(min_uses=0)
    bank.add("dup", "text")
    with pytest.raises(SkillBankError):
        bank.add("dup", "other")


def test_cli_report_audit_and_search(tmp_path, capsys):
    bank = _bank(tmp_path)
    store = bank.path

    assert cli.main(["skills", "report", "--store", store, "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["counts"]["skills"] == 3
    assert report["baseline"] == pytest.approx(8 / 15)

    assert cli.main(["skills", "audit", "--store", store,
                     "--min-uses", "5", "--json"]) == 0
    audit = json.loads(capsys.readouterr().out)
    assert audit["counts"]["quarantine"] == 1

    assert cli.main(["skills", "audit", "--store", store, "--min-uses", "5",
                     "--apply", "--json"]) == 0
    capsys.readouterr()
    assert SkillBank(store).get("bad").status == "quarantined"

    assert cli.main(["skills", "search", "--store", store,
                     "--query", "total", "--json"]) == 0
    search = json.loads(capsys.readouterr().out)
    assert search["hits"][0]["skill_id"] == "good"

    assert cli.main(["skills", "report", "--store",
                     str(tmp_path / "missing.json"), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["counts"]["skills"] == 0


def test_malformed_store_is_an_input_error(tmp_path, capsys):
    path = tmp_path / "skills.json"
    path.write_text("not json", encoding="utf-8")
    assert cli.main(["skills", "report", "--store", str(path), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_non_object_store_is_an_input_error(tmp_path, capsys):
    for text in ("[]", "null", "1"):
        path = tmp_path / f"bad-{text}.json"
        path.write_text(text, encoding="utf-8")
        assert cli.main(["skills", "report", "--store", str(path), "--json"]) == 2
        assert json.loads(capsys.readouterr().out)["ok"] is False
