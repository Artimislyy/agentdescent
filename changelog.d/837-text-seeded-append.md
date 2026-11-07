Fixed
`kind=text` now uses `SeededAppendRules` so a one-sentence reflector proposal
appends under `# Learned rules` instead of replacing the whole seed prompt
via `SingleSlot` (#837). GEPA keeps `SingleSlot` with a full-rewrite propose
template.
