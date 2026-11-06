"""Predict an edit's effect before measuring it, then falsify the prediction.

A proposal that says *what* it changes but not *what it expects* is hard to
audit: a lucky edit and a reasoned one look identical after the fact. AHE's
decision observability closes that gap by pairing every edit with a prediction
that the next evaluation verifies or falsifies. This module is the small,
dependency-free record for that loop:

    log = PredictionLog("predictions.jsonl")
    pid = log.predict("skill-csv", "d1",
                      ProposalPrediction(expected_delta=0.05,
                                         expected_tasks=("t7", "t8"),
                                         confidence=0.7,
                                         rationale="the cents rule covers both"))
    # ... run the held-out evaluation ...
    log.observe(pid, observed_delta=0.04, observed_tasks=("t7", "t8"))
    log.report()   # hit rate, Brier score, calibration buckets

The log is append-only JSONL: a prediction is written before the measurement and
an observation is appended later, so the proposer cannot rewrite the expectation
after seeing the result. A missing observation stays ``pending``. No model or
network call is made.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "PREDICTION_SCHEMA_VERSION",
    "PredictionError",
    "ProposalPrediction",
    "PredictionRecord",
    "PredictionLog",
]

PREDICTION_SCHEMA_VERSION = 1


class PredictionError(ValueError):
    """A prediction input the log cannot use; the message is safe to print."""


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PredictionError(f"{name} must be a number, not bool")
    number = float(value)
    if not math.isfinite(number):
        raise PredictionError(f"{name} must be finite")
    return number


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PredictionError(f"{name} must be a non-empty string")
    return value


def _tasks(value: Any, name: str) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",") if part.strip()]
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        parts = [str(part) for part in value]
    else:
        raise PredictionError(f"{name} must be a list or comma-separated string")
    if any(not part.strip() for part in parts):
        raise PredictionError(f"{name} task ids must be non-empty")
    return tuple(parts)


@dataclass(frozen=True)
class ProposalPrediction:
    """What a proposer expects its edit to do, declared before evaluation."""

    expected_delta: float
    confidence: float
    expected_tasks: Tuple[str, ...] = ()
    rationale: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "expected_delta",
                           _finite(self.expected_delta, "expected_delta"))
        confidence = _finite(self.confidence, "confidence")
        if not 0.0 <= confidence <= 1.0:
            raise PredictionError("confidence must be in [0, 1]")
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "expected_tasks",
                           _tasks(self.expected_tasks, "expected_tasks"))
        if not isinstance(self.rationale, str):
            raise PredictionError("rationale must be a string")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "expected_delta": self.expected_delta,
            "confidence": self.confidence,
            "expected_tasks": list(self.expected_tasks),
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class PredictionRecord:
    """A prediction joined with its observation and the resulting scores."""

    prediction_id: str
    artifact_id: str
    diff_id: str
    prediction: ProposalPrediction
    created_at: float
    observed_delta: Optional[float] = None
    observed_tasks: Tuple[str, ...] = ()
    observed_at: Optional[float] = None
    tolerance: float = 0.0
    note: str = ""

    @property
    def pending(self) -> bool:
        return self.observed_delta is None

    @property
    def delta_error(self) -> Optional[float]:
        if self.pending:
            return None
        return float(self.observed_delta) - self.prediction.expected_delta

    @property
    def abs_error(self) -> Optional[float]:
        error = self.delta_error
        return None if error is None else abs(error)

    @property
    def task_overlap(self) -> Optional[float]:
        if self.pending:
            return None
        wanted = set(self.prediction.expected_tasks)
        got = set(self.observed_tasks)
        union = wanted | got
        if not union:
            return 1.0
        return len(wanted & got) / len(union)

    @property
    def hit(self) -> Optional[bool]:
        if self.pending:
            return None
        if self.abs_error > self.tolerance + 1e-12:
            return False
        if self.prediction.expected_tasks:
            return set(self.prediction.expected_tasks) == set(self.observed_tasks)
        return True

    @property
    def brier(self) -> Optional[float]:
        hit = self.hit
        if hit is None:
            return None
        return (self.prediction.confidence - float(hit)) ** 2

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": PREDICTION_SCHEMA_VERSION,
            "prediction_id": self.prediction_id,
            "artifact_id": self.artifact_id,
            "diff_id": self.diff_id,
            "prediction": self.prediction.to_dict(),
            "created_at": self.created_at,
            "observed_delta": self.observed_delta,
            "observed_tasks": list(self.observed_tasks),
            "observed_at": self.observed_at,
            "tolerance": self.tolerance,
            "note": self.note,
            "pending": self.pending,
            "delta_error": self.delta_error,
            "abs_error": self.abs_error,
            "task_overlap": self.task_overlap,
            "hit": self.hit,
            "brier": self.brier,
        }


_LOCKS: Dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(path, threading.Lock())


class PredictionLog:
    """Append-only predictions and observations in one JSONL file."""

    def __init__(self, path: str) -> None:
        self.path = os.path.abspath(os.path.expanduser(path))
        self._lock = _lock_for(self.path)

    def _events(self) -> Iterator[Dict[str, Any]]:
        try:
            with open(self.path, encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except (TypeError, ValueError):
                        continue
                    if isinstance(row, dict):
                        yield row
        except FileNotFoundError:
            return

    def _append(self, payload: Mapping[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(payload), sort_keys=True,
                                    ensure_ascii=False, default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _parsed(self) -> Tuple[Dict[str, Any], Dict[str, Any], int]:
        predictions: Dict[str, Tuple[Dict[str, Any], ProposalPrediction]] = {}
        observations: Dict[str, Dict[str, Any]] = {}
        skipped = 0
        for row in self._events():
            key = row.get("prediction_id")
            if not isinstance(key, str) or not key:
                skipped += 1
                continue
            if row.get("event") == "prediction":
                if key in predictions:
                    continue
                payload = row.get("prediction") or {}
                try:
                    prediction = ProposalPrediction(
                        expected_delta=payload.get("expected_delta", 0.0),
                        confidence=payload.get("confidence", 0.0),
                        expected_tasks=tuple(payload.get("expected_tasks") or ()),
                        rationale=str(payload.get("rationale", "")))
                    float(row.get("created_at", 0.0) or 0.0)
                except (TypeError, ValueError, PredictionError):
                    skipped += 1
                    continue
                predictions[key] = (row, prediction)
            elif row.get("event") == "observation":
                if key in observations:
                    continue
                try:
                    delta = float(row.get("observed_delta"))
                    tolerance = float(row.get("tolerance", 0.0) or 0.0)
                    tasks = tuple(str(task) for task in
                                  (row.get("observed_tasks") or ()))
                    float(row.get("observed_at", 0.0) or 0.0)
                except (TypeError, ValueError):
                    skipped += 1
                    continue
                if not math.isfinite(delta) or not math.isfinite(tolerance) \
                        or tolerance < 0:
                    skipped += 1
                    continue
                observations[key] = row
        return predictions, observations, skipped

    def _build_record(self, base: Mapping[str, Any],
                      prediction: ProposalPrediction,
                      observed: Optional[Mapping[str, Any]]) -> PredictionRecord:
        return PredictionRecord(
            prediction_id=str(base.get("prediction_id", "")),
            artifact_id=str(base.get("artifact_id", "")),
            diff_id=str(base.get("diff_id", "")),
            prediction=prediction,
            created_at=float(base.get("created_at", 0.0) or 0.0),
            observed_delta=(None if observed is None else float(
                observed.get("observed_delta", 0.0) or 0.0)),
            observed_tasks=tuple((observed or {}).get("observed_tasks") or ()),
            observed_at=(None if observed is None else float(
                observed.get("observed_at", 0.0) or 0.0)),
            tolerance=float((observed or {}).get("tolerance", 0.0) or 0.0),
            note=str((observed or {}).get("note", "")),
        )

    def predict(self, artifact_id: str, diff_id: str,
                prediction: ProposalPrediction, *,
                prediction_id: Optional[str] = None) -> str:
        artifact_id = _text(artifact_id, "artifact_id")
        diff_id = str(diff_id or "")
        if not isinstance(prediction, ProposalPrediction):
            raise PredictionError("prediction must be a ProposalPrediction")
        pid = prediction_id or uuid.uuid4().hex
        with self._lock:
            predictions, _, _ = self._parsed()
            if pid in predictions:
                raise PredictionError(f"prediction {pid!r} already exists")
            self._append({
                "event": "prediction", "schema_version": PREDICTION_SCHEMA_VERSION,
                "prediction_id": pid, "artifact_id": artifact_id,
                "diff_id": diff_id, "created_at": time.time(),
                "prediction": prediction.to_dict(),
            })
        return pid

    def observe(self, prediction_id: str, *, observed_delta: float,
                observed_tasks: Any = (), tolerance: float = 0.0,
                note: str = "") -> PredictionRecord:
        prediction_id = _text(prediction_id, "prediction_id")
        observed_delta = _finite(observed_delta, "observed_delta")
        tolerance = _finite(tolerance, "tolerance")
        if tolerance < 0:
            raise PredictionError("tolerance must be >= 0")
        if not isinstance(note, str):
            raise PredictionError("note must be a string")
        tasks = _tasks(observed_tasks, "observed_tasks")
        with self._lock:
            predictions, observations, _ = self._parsed()
            if prediction_id not in predictions:
                raise PredictionError(f"unknown prediction {prediction_id!r}")
            if prediction_id in observations:
                raise PredictionError(
                    f"prediction {prediction_id!r} already has an observation")
            self._append({
                "event": "observation", "schema_version": PREDICTION_SCHEMA_VERSION,
                "prediction_id": prediction_id, "observed_at": time.time(),
                "observed_delta": observed_delta,
                "observed_tasks": list(tasks), "tolerance": tolerance,
                "note": note,
            })
            predictions, observations, _ = self._parsed()
        base, prediction = predictions[prediction_id]
        return self._build_record(base, prediction, observations.get(prediction_id))

    def records(self) -> Tuple[PredictionRecord, ...]:
        predictions, observations, _ = self._parsed()
        return tuple(
            self._build_record(base, prediction, observations.get(key))
            for key, (base, prediction) in predictions.items())

    def pending(self) -> Tuple[PredictionRecord, ...]:
        return tuple(row for row in self.records() if row.pending)

    def report(self) -> Dict[str, Any]:
        predictions, observations, skipped = self._parsed()
        rows = tuple(
            self._build_record(base, prediction, observations.get(key))
            for key, (base, prediction) in predictions.items())
        observed = [row for row in rows if not row.pending]
        briers = [row.brier for row in observed if row.brier is not None]
        abs_errors = [row.abs_error for row in observed if row.abs_error is not None]
        hits = [bool(row.hit) for row in observed]
        buckets: List[Dict[str, Any]] = []
        for index in range(5):
            low = index * 0.2
            high = 1.0 if index == 4 else (index + 1) * 0.2
            group = [row for row in observed
                     if min(int(row.prediction.confidence * 5), 4) == index]
            if not group:
                continue
            buckets.append({
                "low": low, "high": high, "count": len(group),
                "mean_confidence": sum(row.prediction.confidence
                                       for row in group) / len(group),
                "hit_rate": sum(1 for row in group if row.hit) / len(group),
            })
        with_tasks = [row for row in observed if row.prediction.expected_tasks]
        return {
            "schema_version": PREDICTION_SCHEMA_VERSION,
            "ok": True,
            "store": self.path,
            "predictions": len(rows),
            "observed": len(observed),
            "pending": len(rows) - len(observed),
            "skipped": skipped,
            "hit_rate": (sum(hits) / len(hits) if hits else None),
            "mean_brier": (sum(briers) / len(briers) if briers else None),
            "mean_abs_error": (sum(abs_errors) / len(abs_errors)
                               if abs_errors else None),
            "mean_delta_error": (sum(row.delta_error for row in observed) /
                                 len(observed) if observed else None),
            "task_exact_rate": (
                sum(1 for row in with_tasks
                    if set(row.prediction.expected_tasks)
                    == set(row.observed_tasks)) / len(with_tasks)
                if with_tasks else None),
            "falsified": sum(1 for row in observed if row.hit is False),
            "calibration": buckets,
            "last": observed[-1].to_dict() if observed else None,
        }
