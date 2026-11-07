Fixed
SkillOpt `LRScheduler` clamps the anneal fraction to `[0, 1]` so the edit
budget stays at `min_lr` after `total_steps` instead of climbing back (#840).
