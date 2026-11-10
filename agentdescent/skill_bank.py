"""A lifecycle for the skills an evolution loop accumulates.

Appending a skill is the easy half. The hard half is the question Library Drift
and the skill-reliability audits ask: does this skill still help, and when should
it be quarantined or retired? This module keeps the outcome ledger and the
lifecycle decision in one place; it does not generate skills (EvoSkill/SkillOpt
do that) and does not decide acceptance (the merge/verification path does).

    bank = SkillBank("skills.json")
    bank.add("csv-cents", "Express monetary amounts as integer cents.")
    bank.observe("csv-cents", success=True)
    bank.observe("csv-cents", success=False)
    bank.audit(min_uses=2)            # -> keep/quarantine actions
    bank.search("money format", k=3)

A skill is a small text record plus its uses/successes/failures. ``audit``
compares each skill's success rate with the bank-wide baseline (a deterministic,
model-free proxy for contribution); a skill below the lift threshold is
quarantined, and a skill can be retired explicitly. The bank is a JSON snapshot
written atomically, so it is a single-writer file like the workspace registry,
not a multi-process database.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .artifact_graph import Artifact, ArtifactGraph

__all__ = [
    "SKILL_BANK_SCHEMA_VERSION",
    "SkillBankError",
    "SkillRecord",
    "SkillBank",
]

SKILL_BANK_SCHEMA_VERSION = 1
_STATUSES = ("active", "quarantined", "retired")


class SkillBankError(ValueError):
    """A skill-bank input the surface cannot use; safe to print."""


@dataclass(frozen=True)
class SkillRecord:
    """One skill and its observed outcomes."""

    skill_id: str
    text: str
    kind: str = "skill"
    uses: int = 0
    successes: int = 0
    failures: int = 0
    status: str = "active"
    created_at: float = 0.0
    last_used_at: float = 0.0
    tags: Tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.skill_id, str) or not self.skill_id.strip():
            raise SkillBankError("skill_id must be a non-empty string")
        if not isinstance(self.text, str) or not self.text.strip():
            raise SkillBankError("text must be a non-empty string")
        for name in ("uses", "successes", "failures"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise SkillBankError(f"{name} must be an int >= 0")
        if self.successes + self.failures != self.uses:
            raise SkillBankError("successes + failures must equal uses")
        if self.status not in _STATUSES:
            raise SkillBankError(f"status must be one of {_STATUSES}")
        if isinstance(self.tags, str):
            raise SkillBankError("tags must be a sequence, not a bare string")
        object.__setattr__(self, "tags", tuple(str(tag) for tag in self.tags))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def success_rate(self) -> Optional[float]:
        return None if not self.uses else self.successes / self.uses

    def lift(self, baseline: float) -> Optional[float]:
        rate = self.success_rate
        return None if rate is None else rate - baseline

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "text": self.text,
            "kind": self.kind,
            "uses": self.uses,
            "successes": self.successes,
            "failures": self.failures,
            "status": self.status,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SkillRecord":
        if not isinstance(payload, Mapping):
            raise SkillBankError("skill record must be a JSON object")
        return cls(
            skill_id=payload.get("skill_id", ""),
            text=payload.get("text", ""),
            kind=str(payload.get("kind", "skill")),
            uses=payload.get("uses", 0),
            successes=payload.get("successes", 0),
            failures=payload.get("failures", 0),
            status=str(payload.get("status", "active")),
            created_at=float(payload.get("created_at", 0.0) or 0.0),
            last_used_at=float(payload.get("last_used_at", 0.0) or 0.0),
            tags=payload.get("tags") or (),
            metadata=payload.get("metadata") or {},
        )


def _atomic(path: str, payload: Mapping[str, Any]) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".agentdescent-skill-bank-", dir=directory, text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True,
                      ensure_ascii=False, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


class SkillBank:
    """A durable, single-writer bank of skills and their outcome ledger."""

    def __init__(self, path: str, *, clock: Optional[Any] = None) -> None:
        if not isinstance(path, str) or not path.strip():
            raise SkillBankError("path must be a non-empty string")
        self.path = os.path.abspath(os.path.expanduser(path))
        self.clock = clock or time.time
        self._records: Dict[str, SkillRecord] = {}
        if os.path.isfile(self.path):
            self._load()

    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError) as error:
            raise SkillBankError(
                f"skill bank {self.path!r} cannot be read: {error}") from None
        if not isinstance(payload, Mapping):
            raise SkillBankError(f"skill bank {self.path!r} must be a JSON object")
        try:
            version = int(payload.get("schema_version", 1))
        except (TypeError, ValueError):
            version = -1
        if version != SKILL_BANK_SCHEMA_VERSION:
            raise SkillBankError(
                f"skill bank {self.path!r} has an unsupported schema")
        rows = payload.get("records", ())
        if not isinstance(rows, list):
            raise SkillBankError(f"skill bank {self.path!r}: records must be a list")
        try:
            self._records = {
                record.skill_id: record for record in
                (SkillRecord.from_dict(item) for item in rows)}
        except (TypeError, ValueError, SkillBankError) as error:
            raise SkillBankError(
                f"skill bank {self.path!r} has an invalid record: {error}") from None

    def save(self) -> None:
        _atomic(self.path, {
            "schema_version": SKILL_BANK_SCHEMA_VERSION,
            "records": [row.to_dict() for row in self.records],
        })

    @property
    def records(self) -> Tuple[SkillRecord, ...]:
        return tuple(self._records[key] for key in sorted(self._records))

    def get(self, skill_id: str) -> SkillRecord:
        try:
            return self._records[skill_id]
        except KeyError:
            raise SkillBankError(f"unknown skill {skill_id!r}") from None

    def add(self, skill_id: str, text: str, *, kind: str = "skill",
            tags: Sequence[str] = (),
            metadata: Optional[Mapping[str, Any]] = None,
            status: str = "active") -> SkillRecord:
        if skill_id in self._records:
            raise SkillBankError(f"skill {skill_id!r} already exists")
        now = float(self.clock())
        record = SkillRecord(
            skill_id=skill_id, text=text, kind=kind, status=status,
            created_at=now, last_used_at=now, tags=tags,
            metadata=dict(metadata or {}))
        self._records[skill_id] = record
        self.save()
        return record

    def observe(self, skill_id: str, *, success: bool,
                at: Optional[float] = None) -> SkillRecord:
        if not isinstance(success, bool):
            raise SkillBankError("success must be a bool")
        record = self.get(skill_id)
        now = float(self.clock() if at is None else at)
        updated = SkillRecord(
            **{**record.to_dict(), "successes": record.successes + int(success),
               "failures": record.failures + int(not success),
               "uses": record.uses + 1, "last_used_at": now})
        self._records[skill_id] = updated
        self.save()
        return updated

    def set_status(self, skill_id: str, status: str) -> SkillRecord:
        if status not in _STATUSES:
            raise SkillBankError(f"status must be one of {_STATUSES}")
        record = self.get(skill_id)
        updated = SkillRecord(**{**record.to_dict(), "status": status})
        self._records[skill_id] = updated
        self.save()
        return updated

    def retire(self, skill_id: str) -> SkillRecord:
        return self.set_status(skill_id, "retired")

    def activate(self, skill_id: str) -> SkillRecord:
        return self.set_status(skill_id, "active")

    def baseline(self) -> float:
        uses = sum(row.uses for row in self._records.values())
        successes = sum(row.successes for row in self._records.values())
        return successes / uses if uses else 0.0

    def audit(self, *, min_uses: int = 5, min_lift: float = 0.0,
              apply: bool = False) -> Dict[str, Any]:
        if isinstance(min_uses, bool) or not isinstance(min_uses, int) or min_uses < 1:
            raise SkillBankError("min_uses must be an int >= 1")
        if isinstance(min_lift, bool) or not isinstance(min_lift, (int, float)):
            raise SkillBankError("min_lift must be a number")
        if not math.isfinite(float(min_lift)):
            raise SkillBankError("min_lift must be finite")
        baseline = self.baseline()
        actions = []
        for record in self.records:
            lift = record.lift(baseline)
            if record.uses < min_uses:
                action = "insufficient"
            elif lift is not None and lift < float(min_lift):
                action = "quarantine"
            else:
                action = "keep"
            row = {
                "skill_id": record.skill_id,
                "status": record.status,
                "uses": record.uses,
                "success_rate": record.success_rate,
                "lift": lift,
                "action": action,
            }
            if apply and action == "quarantine" and record.status == "active":
                self.set_status(record.skill_id, "quarantined")
                row["status"] = "quarantined"
            actions.append(row)
        return {
            "schema_version": SKILL_BANK_SCHEMA_VERSION,
            "ok": True,
            "store": self.path,
            "baseline": baseline,
            "min_uses": min_uses,
            "min_lift": float(min_lift),
            "applied": bool(apply),
            "actions": actions,
            "counts": {
                "skills": len(actions),
                "keep": sum(1 for row in actions if row["action"] == "keep"),
                "quarantine": sum(1 for row in actions
                                  if row["action"] == "quarantine"),
                "insufficient": sum(1 for row in actions
                                    if row["action"] == "insufficient"),
            },
        }


    def report(self) -> Dict[str, Any]:
        """Shape of the bank: statuses, baseline and the best/worst lifts."""
        baseline = self.baseline()
        rows = []
        for record in self.records:
            rows.append({
                "skill_id": record.skill_id,
                "status": record.status,
                "uses": record.uses,
                "success_rate": record.success_rate,
                "lift": record.lift(baseline),
            })
        ranked = sorted(
            (row for row in rows if row["lift"] is not None),
            key=lambda row: (row["lift"], row["skill_id"]))
        return {
            "schema_version": SKILL_BANK_SCHEMA_VERSION,
            "ok": True,
            "store": self.path,
            "baseline": baseline,
            "counts": {
                "skills": len(rows),
                "active": sum(1 for row in rows if row["status"] == "active"),
                "quarantined": sum(1 for row in rows
                                   if row["status"] == "quarantined"),
                "retired": sum(1 for row in rows if row["status"] == "retired"),
            },
            "best": ranked[-3:][::-1],
            "worst": ranked[:3],
        }

    def search(self, query: str, *, k: int = 5) -> Dict[str, Any]:
        if not isinstance(query, str) or not query.strip():
            raise SkillBankError("query must be a non-empty string")
        if isinstance(k, bool) or not isinstance(k, int) or k < 1:
            raise SkillBankError("k must be an int >= 1")
        graph = ArtifactGraph()
        for record in self.records:
            if record.status != "active":
                continue
            graph.add(Artifact(
                record.skill_id, record.text, kind=record.kind,
                score=record.success_rate or 0.0, tags=record.tags))
        hits = graph.search(query, k=k)
        return {
            "schema_version": SKILL_BANK_SCHEMA_VERSION,
            "ok": True,
            "store": self.path,
            "query": query,
            "hits": [{
                "skill_id": hit.artifact.artifact_id,
                "score": hit.score,
                "matched_terms": list(hit.matched_terms),
                "kind": hit.artifact.kind,
            } for hit in hits],
        }
