"""``resume`` refuses a run that already reached its target (#900).

Relaunching a solved run spent calls again and rewrote its status with the
no-op rerun, so ``show``/``diagnose`` lost what the run had learned.
"""

import io
import os
from contextlib import redirect_stderr, redirect_stdout

import pytest

from agentdescent import cli, runstore
from agentdescent.mcp import Tools

from test_plugin_host_cli import _clis
from test_resume_host_cli import _snapshot, _stopped_run


@pytest.fixture
def launches(monkeypatch):
    calls = []

    def spy(rd, **kw):
        calls.append(rd.run_id)
        return rd.update_status(state="running", pid=os.getpid())

    monkeypatch.setattr(runstore, "launch", spy)
    return calls


def _solved(tmp_path):
    store, rd = _stopped_run(tmp_path)
    rd.update_status(state="done", stop_reason="target_reward")
    return store, rd


def test_cli_resume_refuses_solved_run_without_launch(tmp_path, monkeypatch, launches):
    _clis(monkeypatch, "opencode", "claude")
    store, rd = _solved(tmp_path)
    before = _snapshot(rd)
    err = io.StringIO()
    with redirect_stdout(io.StringIO()), redirect_stderr(err):
        code = cli.main(["--store", store, "resume", rd.run_id])
    assert code != 0
    assert "already reached its target" in err.getvalue()
    assert f"agentdescent show {rd.run_id}" in err.getvalue()
    assert launches == []
    assert _snapshot(rd) == before


def test_mcp_resume_refuses_solved_run_without_launch(tmp_path, monkeypatch, launches):
    _clis(monkeypatch, "opencode", "claude")
    store, rd = _solved(tmp_path)
    before = _snapshot(rd)
    out = Tools(store).resume(rd.run_id)
    assert "already reached its target" in (out.get("error") or "")
    assert launches == []
    assert _snapshot(rd) == before


@pytest.mark.parametrize("state,reason", [("done", "max_iters"),
                                          ("cancelled", "cancelled"),
                                          ("failed", "error")])
def test_resume_still_relaunches_unsolved_runs(tmp_path, monkeypatch, launches,
                                               state, reason):
    _clis(monkeypatch, "opencode", "claude")
    store, rd = _stopped_run(tmp_path)
    rd.update_status(state=state, stop_reason=reason)
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        assert cli.main(["--store", store, "resume", rd.run_id]) == 0
    assert launches == [rd.run_id]
