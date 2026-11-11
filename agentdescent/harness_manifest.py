"""A file-level component contract for harness evolution.

A harness is not one prompt: it is a system prompt, tool descriptions, tool
implementations, middleware, skills, sub-agents and memory. Letting a reflector
rewrite that tree as one opaque artifact makes two things impossible: attributing
an edit to a component, and freezing the safety-critical ones. This module is
the small contract that names the components, says which paths are editable and
which are frozen, and refuses an edit that crosses a budget.

    manifest = load_manifest("harness.json")
    plan = manifest.check({"system_prompt.md": "...", "tools/search.py": "..."})
    plan["ok"], plan["violations"]
    FileTree(tree, **manifest.tree_kwargs())

The responsibilities mirror the RRSI component vocabulary (``context_mgmt``,
``client_tool``, ``skill``, ``memory``, ``subagent``) and the safety
decomposition used by SHE: a system prompt, a rule bank, safety memory and a
tool policy can each have their own budget and editability.
"""

from __future__ import annotations

import fnmatch
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

__all__ = [
    "HARNESS_MANIFEST_SCHEMA_VERSION",
    "RESPONSIBILITIES",
    "HarnessManifestError",
    "HarnessComponent",
    "HarnessManifest",
    "load_manifest",
]

HARNESS_MANIFEST_SCHEMA_VERSION = 1
RESPONSIBILITIES = (
    "system_prompt", "tool_policy", "tool_impl", "rule_bank", "safety_memory",
    "skill", "subagent", "middleware", "context_mgmt", "client_tool",
    "memory", "other",
)


class HarnessManifestError(ValueError):
    """A manifest or edit the contract cannot accept; safe to print."""


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HarnessManifestError(f"{name} must be a non-empty string")
    return value


def _paths(value: Any, name: str) -> Tuple[str, ...]:
    if isinstance(value, str):
        value = (value,)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise HarnessManifestError(f"{name} must be a list of globs")
    out = []
    for item in value:
        text = _text(item, f"{name}[]")
        if text.startswith("/") or text.startswith("../") or "/../" in text:
            raise HarnessManifestError(
                f"{name} path {text!r} must be relative and stay in the tree")
        out.append(text)
    if not out:
        raise HarnessManifestError(f"{name} must not be empty")
    return tuple(out)


def _optional_int(value: Any, name: str) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise HarnessManifestError(f"{name} must be an int >= 1 or null")
    return value


def _clean_path(path: Any) -> str:
    text = _text(path, "change path").replace("\\", "/")
    if text.startswith("/") or text == ".." or text.startswith("../") or "/../" in text:
        raise HarnessManifestError(
            f"change path {path!r} must be relative and stay in the tree")
    if any(part in ("", ".", "..") for part in text.split("/")):
        raise HarnessManifestError(f"change path {path!r} is not clean")
    return text


@dataclass(frozen=True)
class HarnessComponent:
    """One named part of the harness and the paths that implement it."""

    name: str
    paths: Tuple[str, ...]
    editable: bool = True
    frozen: bool = False
    responsibility: str = "other"
    max_files: Optional[int] = None
    max_lines: Optional[int] = None
    risk: float = 0.0
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, "component name"))
        object.__setattr__(self, "paths", _paths(self.paths, "component paths"))
        if self.responsibility not in RESPONSIBILITIES:
            raise HarnessManifestError(
                f"responsibility must be one of {RESPONSIBILITIES}")
        object.__setattr__(self, "max_files", _optional_int(
            self.max_files, "max_files"))
        object.__setattr__(self, "max_lines", _optional_int(
            self.max_lines, "max_lines"))
        if isinstance(self.risk, bool) or not isinstance(self.risk, (int, float)):
            raise HarnessManifestError("risk must be a number")
        risk = float(self.risk)
        if not 0.0 <= risk <= 1.0:
            raise HarnessManifestError("risk must be in [0, 1]")
        object.__setattr__(self, "risk", risk)
        if self.frozen and self.editable:
            raise HarnessManifestError(
                f"component {self.name!r} cannot be both frozen and editable")
        if not isinstance(self.description, str):
            raise HarnessManifestError("description must be a string")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "paths": list(self.paths),
            "editable": bool(self.editable and not self.frozen),
            "frozen": bool(self.frozen),
            "responsibility": self.responsibility,
            "max_files": self.max_files,
            "max_lines": self.max_lines,
            "risk": self.risk,
            "description": self.description,
        }


@dataclass(frozen=True)
class HarnessManifest:
    """The component contract for one harness tree."""

    components: Tuple[HarnessComponent, ...]
    max_files: Optional[int] = None
    max_lines: Optional[int] = None
    allowed_paths: Tuple[str, ...] = ("**",)
    forbidden_paths: Tuple[str, ...] = ()
    version: int = HARNESS_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.components, Sequence) or isinstance(
                self.components, (str, bytes)) or not self.components:
            raise HarnessManifestError("manifest needs at least one component")
        object.__setattr__(self, "components", tuple(self.components))
        names = [component.name for component in self.components]
        if len(set(names)) != len(names):
            raise HarnessManifestError("component names must be unique")
        object.__setattr__(self, "max_files", _optional_int(
            self.max_files, "max_files"))
        object.__setattr__(self, "max_lines", _optional_int(
            self.max_lines, "max_lines"))
        object.__setattr__(self, "allowed_paths", _paths(
            self.allowed_paths, "allowed_paths"))
        forbidden = self.forbidden_paths or ()
        if isinstance(forbidden, str):
            forbidden = (forbidden,)
        object.__setattr__(self, "forbidden_paths", tuple(
            _text(path, "forbidden_paths[]") for path in forbidden))
        if self.version != HARNESS_MANIFEST_SCHEMA_VERSION:
            raise HarnessManifestError(
                f"unsupported manifest schema {self.version!r}")

    def component_for(self, path: str) -> Optional[HarnessComponent]:
        clean = _clean_path(path)
        for component in self.components:
            if any(fnmatch.fnmatch(clean, pattern) for pattern in component.paths):
                return component
        return None

    def tree_kwargs(self) -> Dict[str, Any]:
        """The ``FileTree`` keyword arguments this manifest resolves to."""
        editable = []
        frozen = []
        for component in self.components:
            # `editable: false` is the same contract as `frozen: true` for the
            # projection; neither may silently fall back to a catch-all.
            if component.frozen or not component.editable:
                frozen.extend(component.paths)
            else:
                editable.extend(component.paths)
        return {
            "editable": tuple(dict.fromkeys(editable)),
            "frozen": tuple(dict.fromkeys(frozen)),
        }

    def check(self, changes: Any) -> Dict[str, Any]:
        """Validate a path->content mapping (or a path sequence) against the contract."""
        if isinstance(changes, Mapping):
            rows = {_clean_path(path): content for path, content in changes.items()}
        elif isinstance(changes, Sequence) and not isinstance(changes, (str, bytes)):
            rows = {_clean_path(path): None for path in changes}
        else:
            raise HarnessManifestError("changes must be a mapping or a path list")
        violations = []
        component_files: Dict[str, int] = {}
        component_lines: Dict[str, int] = {}
        total_lines = 0
        for path, content in rows.items():
            if not any(fnmatch.fnmatch(path, pattern)
                       for pattern in self.allowed_paths):
                violations.append(f"{path}: outside allowed_paths")
            if any(fnmatch.fnmatch(path, pattern)
                   for pattern in self.forbidden_paths):
                violations.append(f"{path}: matched forbidden_paths")
            component = self.component_for(path)
            if component is None:
                violations.append(f"{path}: no component owns this path")
                continue
            if component.frozen or not component.editable:
                why = "frozen" if component.frozen else "not editable"
                violations.append(
                    f"{path}: component {component.name!r} is {why}")
                continue
            component_files[component.name] = component_files.get(
                component.name, 0) + 1
            if content is not None:
                lines = len(str(content).splitlines())
                component_lines[component.name] = component_lines.get(
                    component.name, 0) + lines
                total_lines += lines
        for component in self.components:
            files = component_files.get(component.name, 0)
            lines = component_lines.get(component.name, 0)
            if component.max_files is not None and files > component.max_files:
                violations.append(
                    f"{component.name}: {files} files > max_files "
                    f"{component.max_files}")
            if component.max_lines is not None and lines > component.max_lines:
                violations.append(
                    f"{component.name}: {lines} lines > max_lines "
                    f"{component.max_lines}")
        if self.max_files is not None and len(rows) > self.max_files:
            violations.append(
                f"{len(rows)} files > manifest max_files {self.max_files}")
        if self.max_lines is not None and total_lines > self.max_lines:
            violations.append(
                f"{total_lines} lines > manifest max_lines {self.max_lines}")
        return {
            "schema_version": HARNESS_MANIFEST_SCHEMA_VERSION,
            "ok": not violations,
            "files": len(rows),
            "lines": total_lines,
            "components": [
                {"name": name, "files": component_files.get(name, 0),
                 "lines": component_lines.get(name, 0)}
                for name in sorted(component_files)],
            "violations": violations,
            "tree": self.tree_kwargs(),
        }

    def require_valid(self, changes: Any) -> Dict[str, Any]:
        report = self.check(changes)
        if not report["ok"]:
            raise HarnessManifestError("; ".join(report["violations"]))
        return report

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.version,
            "max_files": self.max_files,
            "max_lines": self.max_lines,
            "allowed_paths": list(self.allowed_paths),
            "forbidden_paths": list(self.forbidden_paths),
            "components": [component.to_dict() for component in self.components],
        }


def _component(value: Mapping[str, Any]) -> HarnessComponent:
    frozen = bool(value.get("frozen", False))
    return HarnessComponent(
        name=value.get("name", ""),
        paths=value.get("paths") or (),
        editable=bool(value.get("editable", not frozen)),
        frozen=frozen,
        responsibility=str(value.get("responsibility", "other")),
        max_files=value.get("max_files"),
        max_lines=value.get("max_lines"),
        risk=value.get("risk", 0.0),
        description=str(value.get("description", "")),
    )


def load_manifest(value: Any) -> HarnessManifest:
    """Load a manifest from a mapping or a JSON file."""
    if isinstance(value, Mapping):
        payload = dict(value)
    elif isinstance(value, str):
        path = os.path.abspath(os.path.expanduser(value))
        try:
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except OSError as error:
            raise HarnessManifestError(
                f"manifest {value!r} cannot be read: {error}") from None
        except ValueError as error:
            raise HarnessManifestError(
                f"manifest {value!r} is not valid JSON: {error}") from None
        if not isinstance(payload, Mapping):
            raise HarnessManifestError("manifest must be a JSON object")
        payload = dict(payload)
    else:
        raise HarnessManifestError("manifest must be a JSON object or a path")
    rows = payload.get("components")
    if not isinstance(rows, list) or not rows:
        raise HarnessManifestError("manifest needs a non-empty components list")
    try:
        components = tuple(_component(row) for row in rows
                           if isinstance(row, Mapping))
    except (TypeError, ValueError) as error:
        raise HarnessManifestError(f"invalid component: {error}") from None
    if len(components) != len(rows):
        raise HarnessManifestError("every component must be a JSON object")
    try:
        return HarnessManifest(
            components=components,
            max_files=payload.get("max_files"),
            max_lines=payload.get("max_lines"),
            allowed_paths=tuple(payload.get("allowed_paths") or ("**",)),
            forbidden_paths=tuple(payload.get("forbidden_paths") or ()),
            version=int(payload.get("schema_version", HARNESS_MANIFEST_SCHEMA_VERSION)))
    except (TypeError, ValueError) as error:
        raise HarnessManifestError(f"invalid manifest: {error}") from None
