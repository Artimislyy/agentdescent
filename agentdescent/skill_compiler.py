"""Compile a textual skill into a tested function, with a text fallback.

A skill document is interpreted by a model on every use; the same procedure can
produce different code, and a mistake is only visible after the rollout. The
compile-away-uncertainty idea (arXiv:2610.39508) turns a well-specified procedure
into a deterministic program and verifies it, keeping the text as the fallback.

This module is the seam, not a code generator:

* ``compiler`` is any ``text -> code`` callable (a model adapter, a template,
  a deterministic extractor);
* the returned source must define exactly one function ``fn`` and pass the
  existing AST gate (no imports, dunder access, exec/eval/open, ...);
* every caller-supplied test must pass;
* optional ``reference`` + ``cases`` check behavioural equivalence;
* anything that fails verification returns ``status="text"`` and the reason, so
  the agent keeps using the skill document.

    skill = compile_skill("csv-cents", text, compiler,
                          tests=[is_int_cents],
                          reference=reference_impl, cases=[("1.20",)]) 
    skill.status, skill.code, skill.reason
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

from .self_modify import _compile_fn, evaluate_source, gate_source

__all__ = [
    "SKILL_COMPILER_SCHEMA_VERSION",
    "SkillCompilerError",
    "CompiledSkill",
    "compile_skill",
]

SKILL_COMPILER_SCHEMA_VERSION = 1


class SkillCompilerError(ValueError):
    """A compiler input the surface cannot use; safe to print."""


@dataclass(frozen=True)
class CompiledSkill:
    """The outcome of one compilation attempt."""

    skill_id: str
    source: str
    status: str
    code: str = ""
    tests_passed: int = 0
    tests_total: int = 0
    equivalence: Optional[bool] = None
    reason: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.skill_id, str) or not self.skill_id.strip():
            raise SkillCompilerError("skill_id must be a non-empty string")
        if self.status not in ("compiled", "text"):
            raise SkillCompilerError("status must be 'compiled' or 'text'")
        for name in ("tests_passed", "tests_total"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise SkillCompilerError(f"{name} must be an int >= 0")
        if self.tests_passed > self.tests_total:
            raise SkillCompilerError("tests_passed cannot exceed tests_total")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def compiled(self) -> bool:
        return self.status == "compiled"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": SKILL_COMPILER_SCHEMA_VERSION,
            "skill_id": self.skill_id,
            "status": self.status,
            "code": self.code,
            "tests_passed": self.tests_passed,
            "tests_total": self.tests_total,
            "equivalence": self.equivalence,
            "reason": self.reason,
            "metadata": dict(self.metadata),
        }


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SkillCompilerError(f"{name} must be a non-empty string")
    return value


def _fallback(skill_id: str, source: str, *, code: str,
              passed: int, total: int, equivalence: Optional[bool],
              reason: str) -> CompiledSkill:
    return CompiledSkill(
        skill_id=skill_id, source=source, status="text", code=code,
        tests_passed=passed, tests_total=total, equivalence=equivalence,
        reason=reason)


def compile_skill(skill_id: str, source: str,
                  compiler: Callable[[str], str], *,
                  tests: Sequence[Callable[[Callable], Any]] = (),
                  reference: Optional[Callable[..., Any]] = None,
                  cases: Sequence[Any] = (),
                  max_source_chars: int = 12000) -> CompiledSkill:
    """Compile one skill and return a verified function or a text fallback."""
    skill_id = _text(skill_id, "skill_id")
    source = _text(source, "source")
    if not callable(compiler):
        raise SkillCompilerError("compiler must be callable")
    if isinstance(max_source_chars, bool) or not isinstance(
            max_source_chars, int) or max_source_chars < 1:
        raise SkillCompilerError("max_source_chars must be an int >= 1")
    if len(source) > max_source_chars:
        raise SkillCompilerError(
            f"source is longer than {max_source_chars} characters")
    if isinstance(tests, (str, bytes)):
        raise SkillCompilerError("tests must be a sequence of callables")
    tests = tuple(tests)
    for test in tests:
        if not callable(test):
            raise SkillCompilerError("every test must be callable")
    if not tests:
        return _fallback(skill_id, source, code="", passed=0, total=0,
                         equivalence=None,
                         reason="no tests; a compiled skill needs verification")
    try:
        code = compiler(source)
    except Exception as error:  # noqa: BLE001 - the compiler is caller code
        return _fallback(skill_id, source, code="", passed=0,
                         total=len(tests), equivalence=None,
                         reason=f"compiler failed: {type(error).__name__}: {error}")
    if not isinstance(code, str) or not code.strip():
        return _fallback(skill_id, source, code="", passed=0,
                         total=len(tests), equivalence=None,
                         reason="compiler returned no source")
    if len(code) > max_source_chars:
        return _fallback(skill_id, source, code="", passed=0,
                         total=len(tests), equivalence=None,
                         reason=f"compiled source is longer than {max_source_chars}")
    try:
        gate_source(code, function_name="fn")
    except Exception as error:  # noqa: BLE001 - the gate is the candidate boundary
        return _fallback(skill_id, source, code=code, passed=0,
                         total=len(tests), equivalence=None,
                         reason=f"gate refused the compiled source: {error}")
    passed, total, _ = evaluate_source(
        code, tests, lambda fn: 1.0, function_name="fn")
    if passed != total:
        return _fallback(skill_id, source, code=code, passed=passed,
                         total=total, equivalence=None,
                         reason=f"{passed}/{total} tests passed")
    equivalence = None
    if reference is not None or cases:
        if reference is None or not callable(reference):
            return _fallback(skill_id, source, code=code, passed=passed,
                             total=total, equivalence=None,
                             reason="reference and cases must be supplied together")
        if not cases:
            return _fallback(skill_id, source, code=code, passed=passed,
                             total=total, equivalence=None,
                             reason="reference supplied without cases")
        try:
            fn = _compile_fn(code, function_name="fn")
            for case in cases:
                expected = reference(case)
                actual = fn(case)
                if expected != actual:
                    equivalence = False
                    return _fallback(
                        skill_id, source, code=code, passed=passed,
                        total=total, equivalence=False,
                        reason=f"case {case!r}: reference {expected!r} != "
                               f"compiled {actual!r}")
            equivalence = True
        except Exception as error:  # noqa: BLE001 - the candidate is user code
            return _fallback(skill_id, source, code=code, passed=passed,
                             total=total, equivalence=False,
                             reason=f"equivalence check failed: "
                                    f"{type(error).__name__}: {error}")
    return CompiledSkill(
        skill_id=skill_id, source=source, status="compiled", code=code,
        tests_passed=passed, tests_total=total, equivalence=equivalence,
        reason="tests passed" + (
            "; equivalent on cases" if equivalence else ""))
