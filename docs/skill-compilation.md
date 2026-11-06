# Skill compilation — a tested function, with the text as fallback

A skill document is re-interpreted by a model on every use. The same procedure
can produce different code, and a mistake is only visible after the rollout.
Compiling a well-specified procedure into a deterministic function removes that
variance and makes it independently testable (the "compile away uncertainty"
idea, arXiv:2610.39508). The text remains the fallback.

```bash
agentdescent compile-skill \
  --skill skills/csv-cents/SKILL.md --skill-id csv-cents \
  --compiler mypkg.compile:to_function \
  --test  tests.skill_checks:is_int_cents \
  --reference tests.skill_checks:reference_cents \
  --cases cases.json \
  --out compiled/csv_cents.py --json
```

`--compiler` is any `text -> source` callable (a model adapter, a template, a
deterministic extractor); `--test` is repeatable; `--cases` is a JSON array of
single-argument cases.

## What must be true to compile

- the compiler returns a non-empty source string;
- the source defines exactly one function `fn` and passes the framework's AST
  gate (no imports, dunder access, `exec`/`eval`/`open`, ...);
- every caller-supplied test passes when run against `fn`;
- if `--reference` and `--cases` are supplied, the compiled function returns the
  same value as the reference on every case.

Anything else returns `status: "text"` with a reason and no `--out` file. That
is a normal result, not a crash: the agent keeps using the skill document.

## The result

```json
{
  "schema_version": 1,
  "skill_id": "csv-cents",
  "status": "compiled",
  "code": "def fn(value):\n    return int(round(float(value) * 100))\n",
  "tests_passed": 1,
  "tests_total": 1,
  "equivalence": true,
  "reason": "tests passed; equivalent on cases"
}
```

`equivalence` is `null` when no reference was supplied, `true` when the cases
match, and `false` when they do not (which forces the text fallback).

## Boundaries

- The module does not call a model: the compiler is the caller's completion or
  extractor. No network call is made by `compile_skill`.
- The compiled function runs in the same safe namespace as the other self-edit
  paths; this is a policy gate, not a full OS sandbox. Run untrusted compilers
  and tests in the existing sandbox if they are not yours.
- Compilation is one skill at a time; batching, skill-bank lifecycle and
  retrieval are separate surfaces.
