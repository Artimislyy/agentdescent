Fixed
`init` / `algorithms run` writing an Ark (`*.volces.com`) `openai_compatible` block now set `"stream": true` by default so reasoning models like `deepseek-v4-flash` do not hit the 120s non-streaming propose timeout; `plan` warns when a hand-edited Ark block omits it, and the quickstart / plugins Ark examples match (#832).
