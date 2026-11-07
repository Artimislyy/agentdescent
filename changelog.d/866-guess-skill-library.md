Fixed
`agentdescent init <path>` and `agentdescent algorithms run NAME <path>` now
guess `kind=skill_library` for a directory with two or more `*/SKILL.md` and
no root `SKILL.md`, instead of falling through to `skill_dir` (#866).
