Added
`agentdescent demo --kind skill_library` runs the offline multi-file
`*/SKILL.md` library demo from an install (no source checkout, no key).
The default `demo` smoke note and README / quickstart-skill / usage now
point at that command; `python -m examples.skill_library_evolution` stays
as the source-checkout CLI (`--dry-run`, `--agent`, `--install-to`) (#878).
