Fixed
A run store that cannot be created (`--store`, `AGENTDESCENT_HOME` or the default
`~/.agentdescent/runs` on a read-only, missing, unwritable or file path) is now a
`RunStoreError`: the CLI exits 2 with one `error: cannot create run store ...`
line, or `{"ok": false, "error": ...}` under `--json`, instead of a raw
`FileNotFoundError` / `FileExistsError` / `PermissionError` traceback (#907).
