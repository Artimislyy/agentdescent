Fixed
The review gate now counts a `Verdict: PASS` written above its `Tip SHA:` line,
above a bare `Tip: <sha>` line, or carrying `(tip <sha>)` inline, so a PASS at
the right tip is no longer read as "says nothing at this tip"; `What I ran (...)`
counts as the `Ran:` list. A PASS with no `Ran:`/`Not run:` is still counted but
marked `weak: no Ran:/Not run:` (#915).
