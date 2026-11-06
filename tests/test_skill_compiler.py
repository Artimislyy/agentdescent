"""Skill compilation: verified function or a text fallback."""

import json

import pytest

from agentdescent import cli
from agentdescent.skill_compiler import (
    CompiledSkill, SkillCompilerError, compile_skill,
)


def double_compiler(text):
    return "def fn(x):\n    return x * 2\n"


def failing_compiler(text):
    return "def fn(x):\n    return x + 1\n"


def triple_compiler(text):
    return "def fn(x):\n    return x * 3\n"


def always_true(fn):
    return callable(fn)


def unsafe_compiler(text):
    return "import os\ndef fn(x):\n    return x\n"


def empty_compiler(text):
    return ""


def raising_compiler(text):
    raise RuntimeError("model unavailable")


def is_double(fn):
    return fn(2) == 4 and fn(-3) == -6


def is_identity(fn):
    return fn(2) == 2


def reference_double(x):
    return x * 2


def test_compiled_status_and_equivalence():
    result = compile_skill(
        "double", "multiply by two", double_compiler,
        tests=[is_double], reference=reference_double, cases=[2, -3])
    assert result.status == "compiled"
    assert result.compiled is True
    assert result.tests_passed == 1 and result.tests_total == 1
    assert result.equivalence is True
    assert "return x * 2" in result.code


def test_failing_test_falls_back_to_text():
    result = compile_skill("double", "multiply", double_compiler,
                           tests=[is_identity])
    assert result.status == "text"
    assert result.tests_passed == 0 and result.tests_total == 1
    assert "tests passed" in result.reason


def test_unsafe_source_is_refused_by_the_gate():
    result = compile_skill("unsafe", "do something", unsafe_compiler,
                           tests=[is_identity])
    assert result.status == "text"
    assert "gate refused" in result.reason


def test_no_tests_or_no_code_falls_back():
    no_tests = compile_skill("x", "text", double_compiler, tests=[])
    assert no_tests.status == "text"
    assert "no tests" in no_tests.reason
    empty = compile_skill("x", "text", empty_compiler, tests=[is_double])
    assert empty.status == "text"
    assert "no source" in empty.reason


def test_compiler_exception_and_reference_mismatch():
    failed = compile_skill("x", "text", raising_compiler, tests=[is_double])
    assert failed.status == "text"
    assert "RuntimeError" in failed.reason
    mismatch = compile_skill(
        "x", "text", triple_compiler, tests=[always_true],
        reference=reference_double, cases=[2])
    assert mismatch.status == "text"
    assert mismatch.equivalence is False
    assert "reference" in mismatch.reason


def test_bad_inputs_are_refused():
    with pytest.raises(SkillCompilerError):
        compile_skill("x", "text", double_compiler, tests=[is_double],
                      max_source_chars=0)
    with pytest.raises(SkillCompilerError):
        compile_skill("", "text", double_compiler, tests=[is_double])
    with pytest.raises(SkillCompilerError):
        CompiledSkill("x", "text", "other")


def test_cli_compiles_and_writes_code(tmp_path, capsys):
    skill = tmp_path / "double.md"
    skill.write_text("multiply by two", encoding="utf-8")
    out = tmp_path / "double.py"
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps([2, -3]), encoding="utf-8")
    assert cli.main([
        "compile-skill", "--skill", str(skill), "--skill-id", "double",
        "--compiler", "tests.test_skill_compiler:double_compiler",
        "--test", "tests.test_skill_compiler:is_double",
        "--reference", "tests.test_skill_compiler:reference_double",
        "--cases", str(cases), "--out", str(out), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "compiled"
    assert payload["equivalence"] is True
    assert "return x * 2" in out.read_text()


def test_cli_missing_skill_is_an_input_error(tmp_path, capsys):
    assert cli.main([
        "compile-skill", "--skill", str(tmp_path / "missing.md"),
        "--compiler", "tests.test_skill_compiler:double_compiler",
        "--test", "tests.test_skill_compiler:is_double",
        "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False
