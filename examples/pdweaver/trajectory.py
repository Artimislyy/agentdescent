"""Index training evidence for on-demand reading; keep the original files intact."""
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path

from agentdescent.trace_digest import TraceEvent, digest_traces, drilldown

from .harness import read_text
from .records import RunRecords


def analysis_paths(repo):
    """Locate the seed analysis guide and its Markdown references."""
    directory = Path(repo) / "skills" / "pdweaver-trajectory-analysis"
    paths = [directory / "SKILL.md", *sorted((directory / "references").rglob("*.md"))]
    return {path.relative_to(directory).as_posix(): path for path in paths}


def analysis_context(repo, state=None):
    if state is not None:
        prefix = "pdweaver-trajectory-analysis/"
        return "\n\n".join("--- reflection_skill/{} ---\n{}".format(key[len(prefix):], text)
                              for key, text in sorted(state.items()) if key.startswith(prefix))
    return "\n\n".join("--- reflection_skill/{} ---\n{}".format(key, read_text(path))
                          for key, path in analysis_paths(repo).items())


def _timestamp(value):
    """Accept epoch seconds and zoned ISO dates; unknown times stay unknown."""
    try:
        at = float(value)
    except (TypeError, ValueError):
        if not isinstance(value, str):
            return 0
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return 0
            at = parsed.timestamp()
        except (ValueError, OverflowError, OSError):
            return 0
    return at if math.isfinite(at) else 0


def trace_events(raw, trial):
    """Map PDWeaver data to TraceEvent; concatenate only adjacent stream fragments."""
    groups = []
    for index, event in enumerate(raw):
        kind, data = event.get("type", "unknown"), event.get("data", {})
        # Streaming fragments are not separate model decisions. Real retries stay separate.
        if (groups and kind in {"llm_output", "llm_reasoning"}
                and isinstance(data.get("content"), str)
                and groups[-1]["kind"] == kind and groups[-1]["run"] == event.get("run_id")):
            groups[-1]["data"]["content"] += data["content"]
            groups[-1]["last"] = index
        else:
            groups.append(dict(kind=kind, data=dict(data), first=index, last=index,
                               run=event.get("run_id")))
    starts = {}
    events = []
    for step, group in enumerate(groups):
        kind, data = group["kind"], group["data"]
        at = _timestamp(data.get("timestamp"))
        result = data.get("result")
        result = result if isinstance(result, dict) else {}
        status = result.get("state") or result.get("status") or data.get("status") or ""
        failed = (data.get("failed") is True or data.get("error") or result.get("error")
                  or result.get("ok") is False or str(status).upper() in {"FAIL", "FAILED", "ERROR", "TIMEOUT"})
        payload = {"source": "raw/agent/events.json", "event_indices": [group["first"], group["last"]],
                   "event_seq": [raw[group["first"]].get("event_seq"), raw[group["last"]].get("event_seq")],
                   "original_kind": kind, "status": status, "phase": data.get("phase", ""),
                   "call_id": data.get("id"), "detail": f"steps/{step:05d}.txt"}
        key = (group["run"], data.get("id")) if kind == "tool" else (group["run"], "model")
        if kind == "model.start" or (kind == "tool" and data.get("phase") == "SENT"):
            starts[key] = at
        if kind == "model.end" or (kind == "tool" and data.get("phase") == "RESOLVED"):
            start = starts.pop(key, None)
            if start and at >= start:
                payload["elapsed_seconds"] = round(at - start, 3)
        # Construct directly: load_trace_events() would shorten text to 600 characters.
        body = data.get("content") if kind in {"llm_output", "llm_reasoning"} else None
        body = body if isinstance(body, str) else json.dumps(data, ensure_ascii=False, indent=2)
        if failed:
            # Put the explicit error before potentially huge arguments for native signature grouping.
            body = json.dumps(data.get("error") or result.get("error") or status or "failed",
                              ensure_ascii=False) + "\n" + body
        events.append(TraceEvent(f"event-{step}", trial["trial_id"], trial.get("task_id", ""), step,
                                "error" if failed else kind, data.get("name", kind),
                                body, at=at, payload=payload))
    events.append(TraceEvent("trial-result", trial["trial_id"], trial.get("task_id", ""), len(events),
                            "result", "official_verification", json.dumps(trial, ensure_ascii=False, indent=2),
                            reward=trial.get("score"), payload={"source": "raw/output.json"}))
    return events


def _readable(text):
    """Wrap a display copy so file tools' per-line limits cannot hide long JSON strings."""
    return "\n".join(line[i:i + 1000] for line in text.split("\n")
                     for i in range(0, max(1, len(line)), 1000))


def prepare_evidence(output, records, task, state):
    """A digest, timeline, native drilldowns and full raw copies of ONE training trial."""
    trial = json.loads(output)
    if trial.get("split") != "train":
        raise ValueError("only training trajectories may enter reflection")
    directory = records.root / "trials" / trial["trial_id"]
    if directory.resolve().parent != records.root / "trials":
        raise ValueError("invalid reflection trial id")
    workspace = RunRecords(directory / "reflection")
    workspace.write_text("task.md", task.prompt)
    workspace.write_text("raw/output.json", output)
    for name, content in state.items():
        workspace.write_text(Path("current") / name, content)
    inventory = ["raw/output.json"]
    for name in ("agent_summary.json", "verdict.json", "verifier/result.json",
                 "verifier/submission.tcl", "verifier/innovus.log",
                 "agent/events.json", "agent/calls.json", "agent/task.json",
                 "agent/runs.json", "agent/session.json", "agent/runner.json"):
        path = directory / name
        if path.resolve() != path.absolute():
            raise ValueError("reflection evidence must not follow symlinks")
        if path.is_file():
            content = read_text(path)  # Preserve original line endings in raw/.
            workspace.write_text("raw/" + name, content)
            workspace.write_text("readable/" + name + ".txt", _readable(content))
            inventory.append("raw/" + name)
    path = workspace.root / "raw/agent/events.json"
    raw = json.loads(path.read_text(encoding="utf-8"))["events"] if path.exists() else []
    events = trace_events(raw, trial)
    workspace.write_text("events.jsonl", "\n".join(json.dumps(e.to_dict(), ensure_ascii=False) for e in events))
    digest = digest_traces(events)
    workspace.write_json("digest.json", digest.to_dict())
    workspace.write_text("digest.txt", digest.text)
    for signature in digest.signatures:
        expanded = drilldown(events, signature=signature.id, limit=len(events))
        workspace.write_text(f"signatures/{signature.id}.txt", _readable(json.dumps(expanded, ensure_ascii=False, indent=2)))
    timeline = ["step\tkind\tname\tstatus\tphase\tseconds\tdetail"]
    for event in events:
        p = event.payload
        detail = p.get("detail", "readable/output.json.txt")
        workspace.write_text(detail, _readable(json.dumps(event.to_dict(), ensure_ascii=False, indent=2)))
        timeline.append("\t".join(str(v) for v in (event.step, p.get("original_kind", event.kind), event.name,
                        p.get("status", ""), p.get("phase", ""), p.get("elapsed_seconds", ""), detail)))
    workspace.write_text("timeline.tsv", "\n".join(timeline))
    slow = sorted((e for e in events if "elapsed_seconds" in e.payload),
                  key=lambda e: e.payload["elapsed_seconds"], reverse=True)[:10]
    overview = (f"Training trial {trial['trial_id']}; score={trial.get('score')}; "
                f"observed Agent seconds={trial.get('agent_elapsed_seconds')}\n"
                f"Raw events={len(raw)}; indexed steps={len(events)}; "
                f"kinds={dict(Counter(e.kind for e in events))}\n\n"
                "Start: task.md, raw/output.json, digest.txt, timeline.tsv.\n"
                "Current editable files: current/ (proposal paths are relative to current/).\n"
                "digest.json lists failure signatures; signatures/<id>.txt contains native drilldown results.\n"
                "timeline.tsv includes successes and failures, with links to full steps/*.txt.\n"
                "Each step links to raw/agent/events.json array indices (zero-based, inclusive) and event_seq.\n"
                "raw/ files are complete originals; readable/<original path>.txt only wraps long lines.\n"
                "Use read offset/limit to page, grep to search; do not read everything in sequence.\n"
                "Compare reports and actions before/after repairs. A failure digest is not a root-cause analysis.\n"
                "Missing timestamps mean unknown duration. Observed spans include waiting, may overlap; do not sum them.\n"
                "Only this trial is available: no H1/H0 comparison exists until a real retest.\n\n"
                "Longest observed model/tool spans:\n"
                + "\n".join(f"- {e.name}: {e.payload['elapsed_seconds']}s; {e.payload['detail']}" for e in slow)
                + "\n\nAvailable raw files (missing exports are unavailable, not proof an action never happened):\n"
                + "\n".join(inventory))
    workspace.write_text("INDEX.md", overview)
    return workspace.root
