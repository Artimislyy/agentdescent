"""The run store's SSE progress stream.

The read-only JSON endpoint answers "what is the state now"; a panel or a
platform needs "tell me when the next round lands" without polling. These tests
drive a live server on an ephemeral port and read the event stream.
"""

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

from agentdescent import runstore
from agentdescent.evolution import RoundInfo

from tests.test_evolvespec import _dir_spec  # noqa: F401


def _round(index):
    return RoundInfo(round=index, held_out_reward=0.5 + index / 10.0,
                     n_items=1, committed=0, rejected=1)


def _read_events(url, headers=None, timeout=5):
    request = urllib.request.Request(url, headers=headers or {})
    events = []
    event = {}
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for raw in response:
            line = raw.decode("utf-8").rstrip("\n")
            if line == "":
                if event:
                    events.append(event)
                    event = {}
                continue
            if line.startswith(":"):
                continue
            if line.startswith("event: "):
                event["event"] = line[len("event: "):]
            elif line.startswith("id: "):
                event["id"] = line[len("id: "):]
            elif line.startswith("data: "):
                event["data"] = json.loads(line[len("data: "):])
    if event:
        events.append(event)
    return events


@pytest.fixture
def live(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "home"))
    store = str(tmp_path / "runs")
    rd = runstore.create(_dir_spec(str(tmp_path)).to_dict(), store=store)
    rd.update_status(state="running", rounds=3, pid=os.getpid())
    httpd = runstore.serve_http(
        host="127.0.0.1", port=0, store=store, serve_forever=False,
        event_poll=0.02,
    )
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", rd
    httpd.shutdown()
    httpd.server_close()


def test_stream_emits_rounds_then_terminal_status(live):
    base, rd = live

    def writer():
        time.sleep(0.1)
        rd.append_round(_round(0))
        time.sleep(0.1)
        rd.append_round(_round(1))
        time.sleep(0.1)
        rd.update_status(state="done", stop_reason="rounds")

    thread = threading.Thread(target=writer)
    thread.start()
    events = _read_events(f"{base}/api/runs/{rd.run_id}/events")
    thread.join()

    assert events[0]["event"] == "status"
    assert events[0]["data"]["state"] == "running"
    rounds = [event for event in events if event["event"] == "round"]
    assert [event["data"]["round"] for event in rounds] == [0, 1]
    assert [event["id"] for event in rounds] == ["0", "1"]
    assert events[-1]["event"] == "status"
    assert events[-1]["data"]["state"] == "done"


def test_a_stalled_run_closes_with_a_terminal_status(tmp_path, monkeypatch):
    """A run whose process died must end the stream, not leave it polling.

    ``status()`` already rewrites a ``running`` run whose pid is gone as
    ``failed``; the stream has to follow that terminal state and close, or a
    panel following a killed run keeps a dead connection open forever.
    """
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "home"))
    store = str(tmp_path / "runs")
    rd = runstore.create(_dir_spec(str(tmp_path)).to_dict(), store=store)
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    rd.update_status(state="running", rounds=3, pid=dead.pid)
    httpd = runstore.serve_http(
        host="127.0.0.1", port=0, store=store, serve_forever=False,
        event_poll=0.02,
    )
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        events = _read_events(
            f"http://127.0.0.1:{httpd.server_address[1]}"
            f"/api/runs/{rd.run_id}/events",
        )
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert events[-1]["event"] == "status"
    assert events[-1]["data"]["state"] == "failed"
    assert "without reporting" in events[-1]["data"]["error"]


def test_a_garbage_last_event_id_replays_every_round(live):
    base, rd = live
    rd.append_round(_round(0))
    rd.append_round(_round(1))
    rd.update_status(state="done", stop_reason="rounds")

    events = _read_events(f"{base}/api/runs/{rd.run_id}/events",
                          headers={"Last-Event-ID": "not-a-number"})
    rounds = [event["data"]["round"] for event in events
              if event["event"] == "round"]
    assert rounds == [0, 1]


def test_a_quiet_stream_sends_keep_alive_comments(live, monkeypatch):
    base, rd = live
    monkeypatch.setattr(runstore, "EVENT_KEEPALIVE_SECONDS", 0.05)
    request = urllib.request.Request(f"{base}/api/runs/{rd.run_id}/events")
    saw = False
    with urllib.request.urlopen(request, timeout=5) as response:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                line = response.readline()
            except socket.timeout:
                break
            if b": keep-alive" in line:
                saw = True
                break
    assert saw


def test_last_event_id_resumes_after_that_round(live):
    base, rd = live
    rd.append_round(_round(0))
    rd.append_round(_round(1))
    rd.update_status(state="done", stop_reason="rounds")

    events = _read_events(f"{base}/api/runs/{rd.run_id}/events",
                          headers={"Last-Event-ID": "0"})
    rounds = [event for event in events if event["event"] == "round"]
    assert [event["data"]["round"] for event in rounds] == [1]


def test_an_unknown_run_is_404(live):
    base, _ = live
    with pytest.raises(urllib.error.HTTPError) as error:
        _read_events(f"{base}/api/runs/nope/events")
    assert error.value.code == 404


def test_run_id_traversal_is_refused(live):
    base, _ = live
    with pytest.raises(urllib.error.HTTPError) as error:
        _read_events(f"{base}/api/runs/../events")
    assert error.value.code in (400, 404)
