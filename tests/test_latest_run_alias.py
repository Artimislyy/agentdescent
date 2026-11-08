"""`latest` / `last` stand for the newest run id on run-id commands (#892, #896)."""

import json
import os

import pytest

from agentdescent import cli, runstore


def _mk(store, rid):
    return runstore.create({"kind": "text", "target": "x.txt"}, run_id=rid, store=store)


def test_latest_resolves_to_newest_run(tmp_path, capsys):
    store = str(tmp_path / "runs")
    _mk(store, "20260101-000000-aaaaaa")
    _mk(store, "20260202-000000-bbbbbb")
    for word in ("latest", "last", "LATEST"):
        assert cli.main(["--store", store, "--json", "status", word]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["run_id"] == "20260202-000000-bbbbbb"


def test_real_run_named_latest_wins(tmp_path, capsys):
    store = str(tmp_path / "runs")
    _mk(store, "latest")
    _mk(store, "20990101-000000-cccccc")
    assert cli.main(["--store", store, "--json", "status", "latest"]) == 0
    assert json.loads(capsys.readouterr().out)["run_id"] == "latest"


def test_latest_on_empty_store_is_clear(tmp_path, capsys):
    store = str(tmp_path / "empty")
    assert cli.main(["--store", store, "--json", "show", "latest"]) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert "no runs under" in out["error"] and "agentdescent demo" in out["error"]
    assert not os.path.exists(os.path.join(store, "latest"))


def test_other_ids_untouched(tmp_path, capsys):
    store = str(tmp_path / "runs")
    _mk(store, "20260101-000000-aaaaaa")
    assert cli.main(["--store", store, "status", "nope"]) == 2
    assert "no run 'nope'" in capsys.readouterr().err


def test_payload_helpers_resolve_latest(tmp_path):
    store = str(tmp_path / "runs")
    _mk(store, "20260101-000000-aaaaaa")
    _mk(store, "20260202-000000-bbbbbb")
    shown = cli.show_payload("latest", store=store)
    assert shown["run_id"] == "20260202-000000-bbbbbb"
    st = cli.status_payload("LAST", store=store)
    assert st["run_id"] == "20260202-000000-bbbbbb"
    with pytest.raises(runstore.RunStoreError, match="20260202-000000-bbbbbb"):
        cli.apply_payload("latest", store=store)


def test_mcp_tools_resolve_latest(tmp_path):
    from agentdescent.mcp import Tools

    store = str(tmp_path / "runs")
    _mk(store, "20260101-000000-aaaaaa")
    _mk(store, "20260202-000000-bbbbbb")
    t = Tools(store)
    assert t.show("latest")["run_id"] == "20260202-000000-bbbbbb"
    assert t.status("last")["run_id"] == "20260202-000000-bbbbbb"
    assert t.diagnose("LATEST")["run_id"] == "20260202-000000-bbbbbb"
    err = t.apply("latest")
    assert "error" in err
    assert "20260202-000000-bbbbbb" in err["error"]
    assert "no run 'latest'" not in err["error"]
    cancelled = t.cancel("latest")
    assert cancelled.get("run_id") == "20260202-000000-bbbbbb" or (
        "error" in cancelled and "no run 'latest'" not in cancelled["error"])


def test_mcp_empty_store_latest_is_clear(tmp_path):
    from agentdescent.mcp import Tools

    store = str(tmp_path / "empty")
    t = Tools(store)
    for fn in (t.show, t.diagnose, t.cancel, t.resume, t.apply):
        out = fn("latest")
        assert "error" in out
        assert "no runs under" in out["error"] and "agentdescent demo" in out["error"]
    out = t.status("latest")
    assert "error" in out
    assert "no runs under" in out["error"]
