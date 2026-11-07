Fixed
`evoskill` on `kind=skill_library` writes top-level `<slug>/SKILL.md` (with
Agent Skills frontmatter) instead of nested `skills/<slug>/SKILL.md`, so apply
into a host skills root stays loadable and edits reuse the seed path (#838).
