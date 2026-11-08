Fixed
Algorithm parameter values that declare `choices` now fold case and `-`/`_`
(`sigmoid-novelty` → `sigmoid_novelty`, `KEEP_ALL` → `keep_all`) and a
near-miss typo ends with "did you mean 'novelty'?", matching how
parameter names already resolve (#888).
