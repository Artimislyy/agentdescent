"""Run one isolated skill trial through an already configured PDWeaver service.

The caller installs the candidate into the fresh workspace before calling this
module. No PDWeaver Python dependency, model credential, or source edit is needed.
"""

from __future__ import annotations

import ipaddress
import json
import math
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .harness import SKILL_NAME

ACTIVE = {"STARTING", "RUNNING", "WAITING_TOOL", "PAUSING", "RESUMING", "QUEUED"}
TERMINAL = {"COMPLETED", "WAITING_USER", "FAILED", "RECONCILE", "STOPPED", "PAUSED", "CANCELLED"}
DEFAULT_USER_PROMPT = """Use the innovus-eco-closure-mcp project skill for this task.
Before doing design work, call skill_tool with skill_name="innovus-eco-closure-mcp"
to read its complete SKILL.md from this workspace. Read ./task.md, solve only
this task, and produce ./repair.tcl. Keep all task constraints and required
checks. Do not edit the installed skill, inspect other tasks or hidden evaluator
files, or retrieve historical solutions.

Fixed PDWeaver transport mapping (the skill's older eda-sandbox names describe
the same operations; use the actual tools exposed by this PDWeaver service):
- create_session -> session_create(tool_kind="innovus", workspace_path=<absolute
  current workspace>). Do not supply session_id; use the returned session_id.
  PDWeaver manages the creation request identity.
- execute_in_session -> session_execute(session_id=<returned ID>, code=<Tcl>,
  request_id=<new unique ID>, timeout_ms=<optional positive milliseconds>).
  The old command argument becomes code. Retries of an accepted execution keep
  its original request_id, exact code and timeout. For asynchronous execution,
  session_submit has these arguments; session_wait(session_id, request_id)
  observes that same execution without submitting it again.
- destroy_sess  ion(instance_id=...) -> session_close(session_id=<returned ID>).
  CLOSING is pending; session_get must confirm CLOSED before a fresh replay.
- Execution previews/logs use output, log_path and log_complete, in place of
  the skill's output_preview/full_log_path. Check state and error as well.
Use MCP Runtime tools for every EDA launch and Tcl execution. Keep the default
PDWeaver system instructions. This task authorizes closing only EDA sessions
created for this workspace; release those sessions when finishing. Never close
another task's sessions. Deliver the repair file and a concise evidence summary.
"""


class PDWeaverInfrastructureError(RuntimeError):
    """An unavailable service or unconfirmed cleanup is not an EDA score of zero."""

    def __init__(self, message: str, *, result: dict | None = None):
        super().__init__(message)
        self.result = result or {}


def _origin(value: str) -> str:
    parsed = urlsplit(value)
    try:
        local = parsed.hostname == "localhost" or ipaddress.ip_address(parsed.hostname or "").is_loopback
        port = parsed.port
    except ValueError:
        local, port = False, None
    if (not local or not port or parsed.scheme != "http" or parsed.username or parsed.password
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
        raise ValueError("PDWeaver URLs must be loopback HTTP origins with an explicit port")
    return value.rstrip("/")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise PDWeaverInfrastructureError("Unexpected redirect from PDWeaver service")


class _JsonClient:
    def __init__(self, origin: str):
        self.origin = _origin(origin)
        self.opener = build_opener(ProxyHandler({}), _NoRedirect())

    def request(self, method: str, path: str, body: dict | None = None, *, timeout: float = 10.0) -> dict:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(self.origin + path, data=data, method=method,
                          headers={"Content-Type": "application/json"})
        # Retrying POST is safe here only because callers retain the exact
        # client_request_id/control_id. DELETE closes the same owned session.
        for attempt in range(2):
            try:
                with self.opener.open(request, timeout=timeout) as response:
                    value = json.load(response)
                if not isinstance(value, dict):
                    raise PDWeaverInfrastructureError("PDWeaver returned a non-object response")
                return value
            except HTTPError as exc:
                # Do not copy arbitrary HTTP bodies or credentials into evidence.
                raise PDWeaverInfrastructureError(f"PDWeaver HTTP request failed (status {exc.code})") from None
            except (URLError, TimeoutError, ConnectionError, json.JSONDecodeError, UnicodeError):
                if attempt:
                    raise PDWeaverInfrastructureError("PDWeaver transport or JSON response failed") from None
        raise AssertionError("unreachable")


def _save(directory: Path, name: str, value: object) -> None:
    target = directory / name
    pending = target.with_suffix(target.suffix + ".tmp")
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pending.replace(target)


def _public_service(identity: dict, ui: dict, runtime_identity: dict) -> dict:
    """Only public stable fields; active_models changes as tasks start and stop."""
    identity_keys = ("service", "pid", "state_root", "config_path")
    return {"identity": {key: identity[key] for key in identity_keys if key in identity},
            "ui": {key: ui[key] for key in ("model", "limits", "runtime_url")},
            "runtime": {key: runtime_identity[key] for key in identity_keys if key in runtime_identity}}


def _skill_reads(task: dict, workspace: Path) -> list[str]:
    expected = workspace / ".pdweaver" / "skills" / SKILL_NAME
    matches = []
    for call in task.get("calls", []):
        args = call.get("args") or {}
        payload = (call.get("result") or {}).get("structuredContent") or {}
        data = ((payload.get("result") or {}).get("data") or {})
        if (call.get("name") == "skill_tool" and call.get("phase") == "RESOLVED"
                and args.get("skill_name") == SKILL_NAME
                and args.get("relative_file_path") in {None, "", "SKILL.md"}
                and payload.get("state") == "SUCCEEDED"
                and data.get("skill_directory") == str(expected)):
            matches.append(call.get("id", ""))
    return matches


def _feedback(task: dict) -> str:
    """Give reflection actual bounded failures; full redacted calls stay on disk."""
    calls = task.get("calls", [])
    failures, recent = [], []
    for call in calls:
        payload = (call.get("result") or {}).get("structuredContent") or {}
        failed = payload.get("error") or payload.get("state") in {"FAILED", "TIMED_OUT", "LOST", "UNKNOWN"}
        if failed:
            failures.append(call)
        elif call.get("name") in {"session_execute", "session_submit", "session_wait", "session_result"}:
            if not str((call.get("args") or {}).get("request_id", "")).startswith(("tcl-source-", "tcl-procs-")):
                recent.append(call)
    rows, seen = [], set()
    for call in failures[-5:] + recent[-3:]:
        if call.get("id") in seen:
            continue
        seen.add(call.get("id"))
        payload = (call.get("result") or {}).get("structuredContent") or {}
        row = {"name": call.get("name"), "phase": call.get("phase"), "state": payload.get("state")}
        if payload.get("error"):
            row["error"] = str(payload["error"])[:1000]
        code = (call.get("args") or {}).get("code")
        if code:
            row["code_excerpt"] = str(code)[:1000]
        if payload.get("output"):
            row["output_excerpt"] = str(payload["output"])[:1000]
        rows.append(row)
    value = {"reason": str((task.get("result") or {}).get("reason", ""))[:1000], "tool_observations": rows}
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 6000 else text[:5940] + "\n[truncated; complete calls are in calls.json]"


def _export(client: _JsonClient, sid: str, tid: str | None, directory: Path) -> tuple[dict, dict]:
    session = client.request("GET", f"/api/agent-sessions/{sid}")
    task = client.request("GET", f"/api/tasks/{tid}") if tid else {}
    _save(directory, "session.json", session)
    _save(directory, "task.json", task)
    _save(directory, "calls.json", task.get("calls", []))
    _save(directory, "runs.json", task.get("runs", []))
    events, position, through = [], 0, None
    while True:
        query = {"after": position, "limit": 1000}
        if through is not None:
            query["through"] = through
        page = client.request("GET", f"/api/agent-sessions/{sid}/history?{urlencode(query)}")
        if through is None:
            through = page["through"]
        events.extend(page["events"])
        if not page["has_more"]:
            break
        next_position = page["next_after"]
        if next_position <= position:
            raise PDWeaverInfrastructureError("PDWeaver history pagination made no progress")
        position = next_position
    _save(directory, "events.json", {"through": through, "events": events})
    return task, session


def _stop(client: _JsonClient, tid: str, poll_interval: float) -> None:
    client.request("POST", f"/api/tasks/{tid}/stop",
                   {"control_id": uuid.uuid4().hex, "reason": "RSI trial ended; stop reasoning before cleanup"})
    deadline = time.monotonic() + 30
    while True:
        task = client.request("GET", f"/api/tasks/{tid}")
        if task.get("status") in TERMINAL:
            return
        if time.monotonic() >= deadline:
            raise PDWeaverInfrastructureError("PDWeaver reasoning stop was not confirmed")
        time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))


def _close_owned(runtime: _JsonClient, session: dict, workspace: Path, poll_interval: float) -> list[dict]:
    records = []
    for sid in dict.fromkeys(session.get("eda_sessions", [])):
        try:
            path = "/sessions/" + quote(sid, safe="")
            observed = runtime.request("GET", path)
            # Public IDs can be redacted aliases. Refuse a missing/mismatched ID;
            # never guess its private Runtime mapping or close an unrelated design.
            if (observed.get("session_id") != sid
                    or Path(observed.get("workspace_path", "")).resolve() != workspace):
                raise PDWeaverInfrastructureError("Cannot confirm ownership of a linked EDA session")
            if observed.get("state") != "CLOSED":
                observed = runtime.request("DELETE", path)
            if observed.get("session_id") != sid:
                raise PDWeaverInfrastructureError("EDA close returned a different session identity")
            deadline = time.monotonic() + 30
            while observed.get("state") != "CLOSED":
                if time.monotonic() >= deadline:
                    raise PDWeaverInfrastructureError("EDA session closure was not confirmed")
                time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
                observed = runtime.request("GET", path)
                if observed.get("session_id") != sid:
                    raise PDWeaverInfrastructureError("EDA session identity changed during cleanup")
            records.append({"session_id": sid, "state": "CLOSED"})
        except PDWeaverInfrastructureError as exc:
            records.append({"session_id": sid, "state": "UNCONFIRMED", "error": str(exc)})
    for call in session.get("unresolved_calls", []):
        if call.get("name") in {"session_create", "checkpoint_restore", "checkpoint_restore_result"}:
            records.append({"call_id": call.get("id"), "state": "UNCONFIRMED",
                            "error": "An unresolved EDA creation may still own an untracked process"})
    if any(item["state"] != "CLOSED" for item in records):
        raise PDWeaverInfrastructureError("EDA cleanup is incomplete; inspect runner.json",
                                          result={"cleanup": records})
    return records


def run_pdweaver(server_url: str, workspace: Path, evidence_dir: Path, *, timeout: float,
                 poll_interval: float = 2.0, user_prompt: str = DEFAULT_USER_PROMPT) -> dict:
    """Execute once, export traces, and release owned EDA sessions.

    Ordinary agent failure returns a record with healthy=True and its actual
    status. Infrastructure/cleanup failures write runner.json and raise
    PDWeaverInfrastructureError(result=record), so the caller cannot score them
    as a candidate regression. PDWeaver must share this host/filesystem.
    """
    if not math.isfinite(timeout) or timeout <= 0 or not math.isfinite(poll_interval) or poll_interval <= 0:
        raise ValueError("timeout and poll_interval must be finite positive values")
    workspace, evidence_dir = Path(workspace).resolve(), Path(evidence_dir).resolve()
    candidate = workspace / ".pdweaver" / "skills" / SKILL_NAME / "SKILL.md"
    if not candidate.is_file() or not (workspace / "task.md").is_file():
        raise ValueError("Trial workspace must contain task.md and the installed project SKILL.md")
    #创建证据目录和 HTTP 客户端。
    evidence_dir.mkdir(parents=True, exist_ok=True)
    client, runtime = _JsonClient(server_url), None
    sid = tid = None
    task, session = {}, {}
    failure = None
    result = {"status": "NOT_STARTED", "session_id": None, "task_id": None, "healthy": True,
              "skill_read": False, "skill_read_call_ids": [], "summary": "", "cleanup": []}
    started = time.monotonic()
    solve_started = None
    try:
        identity = client.request("GET", "/identity")
        if identity.get("service") != "pdweaver-agent":
            raise PDWeaverInfrastructureError("Endpoint is not a PDWeaver Agent service")
        ui = client.request("GET", "/api/ui")
        runtime = _JsonClient(ui["runtime_url"])
        runtime_identity = runtime.request("GET", "/identity")
        if runtime_identity.get("service") != "pdweaver-runtime":
            raise PDWeaverInfrastructureError("Endpoint is not a PDWeaver Runtime service")
        result["service"] = _public_service(identity, ui, runtime_identity)
        _save(evidence_dir, "service.json", result["service"])
        # 创建一个新的 PDWeaver 会话并提交任务。
        session = client.request("POST", "/api/agent-sessions",
                                 {"workspace": str(workspace), "client_request_id": uuid.uuid4().hex})
        if Path(session.get("workspace", "")).resolve() != workspace or session.get("tasks"):
            raise PDWeaverInfrastructureError("PDWeaver did not create a fresh session in the trial workspace")
        sid = session["id"]
        result["session_id"] = sid
        #提交做题要求
        solve_started = time.monotonic()
        task = client.request("POST", f"/api/agent-sessions/{sid}/tasks",
                              {"client_request_id": uuid.uuid4().hex, "goal": user_prompt, "inputs": {}})
        tid = task["id"]
        result["task_id"] = tid
        #6. 循环查询，等待任务结束
        while True:
            status = task.get("status")
            if status in TERMINAL:
                result["status"] = status
                break
            if status not in ACTIVE:
                raise PDWeaverInfrastructureError("Unrecognized PDWeaver task status")
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                result["status"] = "TIMED_OUT"
                break
            time.sleep(min(poll_interval, remaining))
            task = client.request("GET", f"/api/tasks/{tid}", timeout=min(10.0, max(0.1, remaining)))
    except (PDWeaverInfrastructureError, KeyError, TypeError, ValueError) as exc:
        failure = exc if isinstance(exc, PDWeaverInfrastructureError) else PDWeaverInfrastructureError("Invalid PDWeaver API response")
    finally:
        # Timing stops before evidence export/cleanup; local trial semaphore wait is excluded.
        result["solve_seconds"] = (time.monotonic() - solve_started if solve_started is not None else None)
        # 已创建 Agent 会话时，核对任务、导出记录并清理本次资源。
        if sid:
            try:
                # 1. 找到这次任务
                session = client.request("GET", f"/api/agent-sessions/{sid}")
                if tid is None and session.get("tasks"):
                    tid = session["tasks"][-1]["id"]
                    result["task_id"] = tid
                if tid:
                    # 确认 Agent 已经停止
                    task = client.request("GET", f"/api/tasks/{tid}")
                    if task.get("status") in ACTIVE or task.get("status") == "WAITING_USER":
                        _stop(client, tid, poll_interval)
                session = client.request("GET", f"/api/agent-sessions/{sid}")
                try:
                    # 保存本次解题过程，导出到：
                    # trials/<trial_id>/agent/
                    # ├── session.json
                    # ├── task.json
                    # ├── calls.json     # 调用了哪些工具、传了什么 Tcl、返回什么
                    # ├── runs.json
                    # └── events.json    # 模型输出、工具事件等
                    # _export() 不会调用 trajectory.py。它先把轨迹保存到磁盘；后面需要反思时，trajectory.py 才读取这些文件。
                    task, session = _export(client, sid, tid, evidence_dir)
                except (PDWeaverInfrastructureError, KeyError, TypeError, ValueError) as exc:
                    failure = failure or (exc if isinstance(exc, PDWeaverInfrastructureError)
                                          else PDWeaverInfrastructureError("Invalid evidence export response"))
                if runtime:
                    # 关闭本次拥有的 EDA 会话
                    result["cleanup"] = _close_owned(runtime, session, workspace, poll_interval)
            except (PDWeaverInfrastructureError, KeyError, TypeError, ValueError) as exc:
                cleanup_error = str(exc) if isinstance(exc, PDWeaverInfrastructureError) else "Invalid cleanup or evidence response"
                result["cleanup_error"] = cleanup_error
                if isinstance(exc, PDWeaverInfrastructureError) and exc.result.get("cleanup"):
                    result["cleanup"] = exc.result["cleanup"]
                failure = failure or PDWeaverInfrastructureError(cleanup_error)
        if runtime and result.get("service"):
            try:
                after = _public_service(client.request("GET", "/identity"), client.request("GET", "/api/ui"),
                                        runtime.request("GET", "/identity"))
                _save(evidence_dir, "service_after.json", after)
                # 检查服务配置是否变化
                if after != result["service"]:
                    raise PDWeaverInfrastructureError("PDWeaver public service configuration changed during the trial")
            except (PDWeaverInfrastructureError, KeyError, TypeError, ValueError) as exc:
                failure = failure or (exc if isinstance(exc, PDWeaverInfrastructureError)
                                      else PDWeaverInfrastructureError("Invalid final service identity response"))
        # 确认模型读取了指定 Skill
        result["skill_read_call_ids"] = _skill_reads(task, workspace)
        result["skill_read"] = bool(result["skill_read_call_ids"])
        # 整理回答、反馈、状态和耗时
        result["summary"] = (task.get("result") or {}).get("answer", "")
        result["feedback"] = _feedback(task)
        result["task_status"] = task.get("status")
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        # 标记基础设施故障并保存摘要
        if failure:
            result["healthy"] = False
            result["infrastructure_error"] = str(failure)
        _save(evidence_dir, "runner.json", result)
    if failure:
        raise PDWeaverInfrastructureError(str(failure), result=result) from None
    return result
