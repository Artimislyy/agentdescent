# GitHub — publish a proposal branch, PR and check

`agentdescent github` is the external review surface for the local evolution
loop. The ledger stays the fast parameter server; this command turns one
accepted candidate into a **proposal branch**, a commit, a pull request and an
optional check run, so a human can review and merge it on GitHub.

```bash
agentdescent github publish --proposal proposal.json \
  --owner Birfy --repo agentdescent \
  --token-env AGENTDESCENT_GITHUB_TOKEN        # plan, no network

agentdescent github publish --proposal proposal.json \
  --owner Birfy --repo agentdescent --apply    # write branch + PR + check
```

Without `--apply` the command is a **plan**: it validates the proposal and
prints the branch, base, files and labels, but makes no API call and needs no
token. The token is read only from `--token-env` (default
`AGENTDESCENT_GITHUB_TOKEN`); it is never accepted on argv, stored in the
proposal or printed.

## Proposal JSON

```json
{
  "branch": "agent/skill-csv-total",
  "title": "feat(skill): improve csv total",
  "body": "Held-out evidence and the decision are below.",
  "base": "main",
  "labels": ["enhancement", "area:cli"],
  "run_id": "run-8",
  "artifact_id": "skill-csv-total",
  "files": {
    "skills/csv/SKILL.md": "# CSV\nExpress amounts in cents."
  },
  "evidence": {
    "decision": "promote",
    "artifact_hash": "sha256:41d8…",
    "evidence_hash": "…"
  },
  "check": {
    "conclusion": "success",
    "title": "held-out evidence",
    "summary": "delta +0.20, 50 tasks, clean"
  }
}
```

- `branch` must not be the base branch; the publisher never writes the base.
- `files` maps repo-relative paths to text; paths that are absolute or contain
  `..` are refused. A list of `{"path", "content"}` objects is also accepted.
- `labels`, `run_id`, `artifact_id` and `evidence` are optional; evidence is
  appended to the PR body so a reviewer sees what the loop saw.
- `check` creates a completed check run on the new commit. A failing gate can
  publish a `failure` check without pretending the change is green.

The publisher creates blobs, a tree over the base tree, a commit whose parent is
the base head, the proposal branch, the PR (or updates an existing PR for the
same head/base) and the labels/check. A second publish force-updates only the
proposal branch; the base branch is never touched. An existing PR's title and
body are refreshed, but its draft state is left alone. Label and check-run
failures after the branch/PR exist are reported under `warnings` instead of
aborting a half-written publish.

## Status

```bash
agentdescent github status --pr 757 --owner Birfy --repo agentdescent --json
```

Returns the PR state, head/base, draft/mergeable and every check run. It is
read-only.

## Security and boundaries

- **Token scope.** Use a fine-grained token with Contents (read/write), Pull
  requests (read/write), Checks (read/write), Issues (read/write) and Metadata
  (read). A classic token needs `repo`, but check-run creation may still require
  a fine-grained token or a GitHub App with Checks:write; without it, publish a
  proposal without a `check` or expect a `warnings` entry.
- **No merge, no approval.** The publisher does not approve, merge, enable
  auto-merge or change branch protection. Merging stays a human/owner action;
  the framework's own risk tiers still apply.
- **Untrusted code.** This surface only uploads file contents. Run candidate
  code in the existing sandbox/runner, never on the publisher host with secrets.
- **Secrets.** The token is read from the environment at request time. Do not put
  it in a proposal, a commit, a check summary or a log.
- **Base branch.** Only `proposal.branch` is created/force-updated; a proposal
  whose branch equals the base is refused.

## What this is not yet

This is not the whole GitHub control plane, but both halves are on this page: the
publisher, which `main` carries (merged as `27c43ee4dc03`), and review ingestion,
documented below. What is still missing is the merge queue, a live dashboard and
a visualization of the review packet. It is also not a GitHub App: a self-hosted
token is enough for one repository.

## Review ingestion and readiness

`agentdescent github review` reads a PR's reviews, inline comments and check
runs into one packet. It extracts **review constraints** — the actionable
requests in review bodies and inline comments — classifies them (`test`,
`security`, `api`, `docs`, `style`, `behavior`) and reports whether the PR is
ready for a human click:

```bash
agentdescent github review --pr 772 --owner Birfy --repo agentdescent --json
```

The packet contains:

- `reviews` — counts of approved / changes_requested / commented / dismissed,
  one per reviewer (that reviewer's decisive review wins, so a later plain
  comment does not erase a block);
- `checks_state` and `checks` — success, failure, pending or none;
- `constraints` — id, kind, text, source (`review:<id>` / `comment:<id>`), path,
  severity (`blocking` / `suggestion`) and `resolved`;
- `merge_readiness` — `ready`, `requires_human_click: true`, the blockers and
  the next step.

A `CHANGES_REQUESTED` review (and its inline comments) is blocking; any other
review or comment is a suggestion unless it uses an action word such as
`please`, `add` or `update`, which promotes it to blocking. Only a reviewer's
decisive review counts: the author's latest approval, change request or
dismissal, so a change request that reviewer later approved (or had dismissed)
no longer blocks and its constraints stay as suggestions, while a later
plain comment neither lifts nor weakens the block. A plain "thanks" is a
note and is not turned into a task. REST does not expose thread
resolution, so pass `--resolved review:1,comment:2` for ids you know are
resolved. This command **never writes, approves or merges**; `ready` only means
the evidence is green and no blocking constraint is known. The actual merge is
still an authorized human/owner action under the repo's risk-tier rule.
