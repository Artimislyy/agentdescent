Fixed

- `doctor` keeps tipping Grok Bot operators to save the scaffold skill as a user skill when `user_skill` is missing (and appends the same follow-up on a stale/partial scaffold problem). The Bot loads the saved user skill, not the scaffold alone (#825).
