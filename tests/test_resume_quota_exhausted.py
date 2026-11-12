"""`resume` refuses a run whose last failure was a provider quota exhaustion (#926).

`diagnose latest` already tells the user to wait for the reset the provider
names, and `resume` is the natural next command -- but it relaunched the
detached worker, flipped the status back to ``running`` and burned another
start into the same 429. #900 gated a solved run for the same reason: a
rejected resume must not rewrite the status it read.
"""

import io
import os
from contextlib import redirect_stderr, redirect_stdout

import pytest

from agentdescent import cli, runstore
from agentdescent.mcp import Tools

QUOTA_ERROR = (
    "QuotaExhausted: https://ark.cn-beijing.volces.com/api/coding/v3 returned "
    "HTTP 429 for model 'deepseek-v4-flash': {\"error\":{\"code\":"
    "\"AccountQuotaExceeded\",\"message\":\"You have exceeded the monthly usage "
    "quota. It will reset at 2026-11-12 23:59:59 +0800 CST. For more "
    "information, please visit the documentation.\"}} -- the account's quota "
    "for this model is used up: wait for the reset the provider names"
)
RESET = "2026-11-12 23:59:59 +0800 CST"


def _failed_run(tmp_path, error=QUOTA_ERROR, state="failed"):
    store = str(tmp_path / "runs")
    rd = runstore.create({"kind": "text", "target": "hi"}, store=store)
    rd.update_status(state=state, error=error, finished=1.0)
    return store, rd


def _snapshot(rd):
    files = {}
    for name in sorted(os.listdir(rd.path)):
        path = os.path.join(rd.path, name)
        if os.path.isfile(path):
            with open(path, "rb") as fh:
                files[name] = fh.read()
    return files


@pytest.fixture
def launches(monkeypatch):
    calls = []

    def spy(rd, **kw):
        calls.append((rd.run_id, kw))
        return rd.update_status(state="running", pid=os.getpid())

    monkeypatch.setattr(runstore, "launch", spy)
    return calls


def test_cli_resume_refuses_a_quota_exhausted_run(tmp_path, launches):
    store, rd = _failed_run(tmp_path)
    before = _snapshot(rd)
    err = io.StringIO()
    with redirect_stdout(io.StringIO()), redirect_stderr(err):
        code = cli.main(["--store", store, "resume", rd.run_id])
    text = err.getvalue()
    assert code == 2
    assert f"cannot resume {rd.run_id}" in text
    assert "QuotaExhausted" in text
    assert "deepseek-v4-flash" in text
    assert RESET in text          # the provider's own reset time, not a guess
    assert "--force" in text      # the way out, named
    assert launches == []         # nothing was relaunched
    assert _snapshot(rd) == before  # status/pid/spec/ledger untouched


def test_force_relaunches_the_same_run(tmp_path, launches):
    store, rd = _failed_run(tmp_path)
    out = io.StringIO()
    with redirect_stdout(out), redirect_stderr(io.StringIO()):
        code = cli.main(["--store", store, "resume", rd.run_id, "--force"])
    assert code == 0
    assert [c[0] for c in launches] == [rd.run_id]
    assert rd.status().state == "running"


def test_an_unparseable_reset_still_refuses_and_still_names_force(tmp_path, launches):
    store, rd = _failed_run(
        tmp_path, error="QuotaExhausted: HTTP 429 for model 'm' -- quota is used up")
    err = io.StringIO()
    with redirect_stdout(io.StringIO()), redirect_stderr(err):
        code = cli.main(["--store", store, "resume", rd.run_id])
    text = err.getvalue()
    assert code == 2 and "cannot resume" in text and "--force" in text
    assert "reset at" not in text  # no invented time when the body has none
    assert launches == []


def test_a_non_quota_failure_still_resumes(tmp_path, launches):
    store, rd = _failed_run(
        tmp_path, error="ProviderConfigError: HTTP 500 -- the provider fell over")
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        code = cli.main(["--store", store, "resume", rd.run_id])
    assert code == 0
    assert [c[0] for c in launches] == [rd.run_id]


def test_a_cancelled_run_with_a_quota_error_in_history_still_resumes(tmp_path, launches):
    # The gate is about *why this attempt ended*, not about any error ever
    # recorded: a cancelled run is resumable (#926 acceptance).
    store, rd = _failed_run(tmp_path, state="cancelled")
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        code = cli.main(["--store", store, "resume", rd.run_id])
    assert code == 0
    assert [c[0] for c in launches] == [rd.run_id]


def test_mcp_resume_reports_the_same_refusal(tmp_path, launches):
    store, rd = _failed_run(tmp_path)
    out = Tools(store).resume(rd.run_id)
    assert "error" in out
    assert f"cannot resume {rd.run_id}" in out["error"]
    assert RESET in out["error"] and "--force" in out["error"]
    assert launches == []


def test_mcp_resume_force_relaunches(tmp_path, launches):
    store, rd = _failed_run(tmp_path)
    assert Tools(store).resume(rd.run_id, force=True)["state"] == "running"
    assert [c[0] for c in launches] == [rd.run_id]
