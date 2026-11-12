Fixed
`agentdescent demo --algorithm rrsi` printed what it learned as the internal
state mapping (`state -> {'ra4bfacbc48': 'COLUMN: amount'}`) in the human footer
and in the `--json` `learned` field; both now name the rule text
(`rules -> 'COLUMN: amount'`), join several rules with ` | ` and count any
beyond the first two, so no internal id or Python repr reaches the reader and
the line matches what `show` renders (#927).
