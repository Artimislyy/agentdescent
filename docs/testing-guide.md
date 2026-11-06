# Set it up and test it

One page, in order: install, prove it works offline, wire it into your agents,
drive it in plain language, then the checks for each piece (the MCP server, the
web panel and the test suite) and what no automated test can confirm. Every
command here was run against the real CLIs; where something is known not to
work, it says so rather than leaving you to find out.

New to AgentDescent? [Start here — the plugin, step by step](plugin-quickstart.md)
is the shorter walk-through; this page is the complete checklist.

---

## 1. Install

One command does all of it — AgentDescent, and the wiring for every agent CLI
you already have:

```bash
git clone https://github.com/ThinkFlowLab/agentdescent && cd agentdescent
bash scripts/setup-hosts.sh
```

Don't have the agent CLIs yet? Add `--with-clis` and it tries to npm-install
them first. `--dry-run` prints what it would do and changes nothing.

All four are public npm packages: `@anthropic-ai/claude-code`, `@openai/codex`,
`opencode-ai`, `@deepseek-ai/dsh`. The script prints npm's own error for
anything that fails, because the fixes are completely different:

| npm says | What it means | Fix |
|---|---|---|
| `ENOSPC` | the disk is full | free space; nothing else will work either |
| `ENOTEMPTY ... rename` | a half-installed copy is in the way | `rm -rf` the path npm printed, re-run |
| `EACCES` | npm's global prefix is not yours | see below |
| `ETIMEDOUT` / `ECONNREFUSED` | registry unreachable | check your proxy |

For `EACCES`, point npm somewhere you own (the script checks this up front):

```bash
npm config set prefix ~/.npm-global
export PATH="$HOME/.npm-global/bin:$PATH"    # add this to your shell rc
```

None of the CLIs are required — `agentdescent demo` runs with none of them
installed, and the script wires up whichever ones it finds.

The script is safe to re-run: config blocks it already owns are left alone
unless their content is out of date.

!!! warning "Two things that bite"
    **`agentdescent` must be on `PATH`** — hosts start it as a *subprocess*, so
    it must be on the PATH of whatever launches your agent, not just your
    interactive shell. The script warns if it isn't. `python3 -m
    agentdescent.cli` works regardless.

    **Python 3.10+ for the MCP server.** The `mcp` package requires it while
    AgentDescent supports 3.9. On 3.9 you get the CLI and the skill; the tools
    are unavailable and `agentdescent mcp` says exactly that.

The script installs from the checkout it is run in, or from PyPI
(`agentdescent[mcp]`) when it is not in one.

## 2. Prove it works, offline

```bash
agentdescent demo
```

No key, no cost, ~10 seconds. It builds a skill whose `references/rules.md`
names the **wrong** column, twelve CSVs with known totals, and an agent that is
a local program reading that skill off disk — then runs the real loop:

```
plan: 12 tasks, 4 rounds x 2 workers, up to 64 agent calls
running (20260905-134121-1c695b)...
  round  0  reward=1.000  +1/-0

held-out reward: 1.000   outcomes: {'committed': 1}
what it learned:  rules.md -> 'COLUMN: amount'
```

Nobody told it the column was `amount`. Only the *model* is replaced here —
staging, the ledger, the parallel workers, the merge and the held-out gate are
the same code a real run uses. **If this fails, the problem is the install, not
your host.**

Your files are untouched until you say so:

```bash
agentdescent show  <run_id>            # the diff
agentdescent apply <run_id> --dry-run  # what it would write
agentdescent apply <run_id>            # writes it, keeping a backup
```

`agentdescent demo --dir /tmp/ad-demo` keeps the files. It writes a spec
pointing at `agentdescent.demo:offline_agent` — a subprocess that reads the
skill off disk — so anything less than the output above exits 1 and names the
run directory to open. `apply` without `--dry-run` leaves a backup at
`csv-total.bak-0`. To rehearse *your own* spec against the same free pair,
point its `agent` and `reflect` at `agentdescent.demo:offline_agent` and
`{"ref": "agentdescent.demo:offline_reflector", "call": false}` — both are
public and inside the ref allowlist.

### What `doctor` reports

Lists which agent CLIs are on `PATH`, which provider keys are set (every key
variable the installers forward -- `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
`DEEPSEEK_API_KEY`, `ARK_API_KEY` -- in `provider_keys_present`; one is enough, and
a key that is not OpenAI's or Anthropic's comes with a hint on using it through
`openai_compatible` with `api_key_env` and `default_base_url`), whether a
container engine and the `mcp` package are present, and where the run store is.
Every "problem" line it prints is something that will make a real run fail. It
also prints the AgentDescent `version` (also `agentdescent --version`) and the
interpreter `executable` it runs on.

## 3. Check each host

The script already wired them. Confirm each one sees it:

| Host | Confirm with | Expect |
|---|---|---|
| **Claude Code** | `claude plugin validate ~/.agentdescent/plugins/claude-code` | `✓ Validation passed` |
| **OpenCode** | `opencode mcp list` | `✓ agentdescent connected` |
| **Codex** | `codex mcp list` | `agentdescent ... enabled` |
| **DSH** | `dsh --profile web --dump-config \| grep agentdescent` | two rows |
| **Grok Bot** | `agentdescent doctor` | `host grok-bot: ok` with `mcp n/a` |

One quirk worth knowing before you debug anything: `codex doctor` reports "no
MCP servers configured" even when a plugin-provided server is live. It counts
only `config.toml`. Trust `codex mcp list`.

### Per host, in detail

`install` is idempotent and `--dry-run` prints what it would write, so it is
safe to inspect first. Use `--home` to keep a probe out of your real setup:
it wins over an exported `CODEX_HOME`, `DSH_HOME` or `XDG_CONFIG_HOME`, so
nothing outside it is read or written.

```bash
agentdescent install dsh --dry-run --home /tmp/probe
agentdescent doctor --home /tmp/probe   # same --home: host lines are not forever missing
```

#### Claude Code

```bash
agentdescent install claude-code
claude plugin validate ~/.agentdescent/plugins/claude-code     # structural check
claude --plugin-dir ~/.agentdescent/plugins/claude-code        # interactive
```

Headless, which is what a CI check would run — note the tool names a **plugin**
gets (`mcp__plugin_<plugin>_<server>__<tool>`), and that `--allowedTools` is
variadic so the prompt goes on stdin:

```bash
echo "Call the agentdescent doctor tool and print its run_store field." | \
  claude -p --plugin-dir ~/.agentdescent/plugins/claude-code \
    --permission-mode acceptEdits \
    --allowedTools mcp__plugin_agentdescent_agentdescent__doctor
```

Expected: the run-store path. Ask for the `version` and `executable` fields
too and compare them with `agentdescent doctor` in your shell: the host starts
its own `agentdescent mcp`, often through the interpreter `install` pinned, and
when a plugin run behaves differently from a shell run, a different install is
the first thing to rule out. If it says the server failed to connect, the
usual cause is `agentdescent` not being on `PATH` for the process that started
Claude Code, or the `[mcp]` extra missing — `agentdescent mcp` then exits 3 and
says so. Claude Code caches a failed connection for ~15 minutes; a different
`--plugin-dir` path is the quickest way to retry.

#### DeepSeek Harness

Either the files or the native plugin, not both.

```bash
agentdescent install dsh
dsh --profile web --dump-config | grep -n agentdescent      # two rows compose
```

```bash
dsh plugin --profile web add link:$PWD/integrations/dsh-agentdescent
dsh --profile web --dump-config | grep -n agentdescent
```

Expected: rows `mcp-agentdescent` (and `dsh-agentdescent` for the plugin) under
a `# == ...` heading. **`patch: entry "..." not found` means the rows were
written without `- insert:`** — a dsh patch file overrides by id, it does not
append. **A `declares no dsh.bundle` warning on install** means the package is
inert; it needs `"dsh": {"bundle": {"patch": "./cordis.patch.yml"}}`.

#### Codex

Two routes. The plugin is one command and brings the MCP server with it; Codex
reads the same plugin format and marketplace as Claude Code:

```bash
codex plugin marketplace add /path/to/agentdescent   # or ThinkFlowLab/agentdescent
codex plugin add agentdescent@agentdescent
codex plugin list                 # agentdescent@agentdescent  installed, enabled
codex mcp list                    # agentdescent ... enabled
```

Or the file route, which needs no marketplace:

```bash
agentdescent install codex
codex mcp list                    # agentdescent ... enabled
```

Codex and dsh both scrub the environment an MCP server starts with; the
forwarded key list, and how to add one, is in
[Use it from your agent](plugins.md#deepseek-harness-a-native-plugin-or-the-files).
Check the `Env` column of `codex mcp list` for the names you rely on.

#### OpenCode

```bash
agentdescent install opencode
opencode mcp list                 # ✓ agentdescent connected
```

`connected` here really did start the server; `Executable not found in $PATH`
means `agentdescent` is not on the `PATH` OpenCode inherited.

**`MCP error -32000: Connection closed` in some directories only** (any host,
not just OpenCode): the launcher is an older `<python> -m agentdescent.cli mcp`,
and the host was started in a directory that contains a folder named
`agentdescent/` — typically the parent of a source checkout. `python -m` puts the
current directory first on `sys.path`, so that folder shadows the installed
package. Run `agentdescent install <host>` again: it rewrites the launcher to
`<python> -P -m agentdescent.cli mcp` (Python ≥ 3.11) or to the absolute path of
the `agentdescent` console script (older Pythons), neither of which looks at the
current directory. Running the old command by hand now prints one line naming the
shadowing directory instead of a traceback.

#### Grok Bot

```bash
agentdescent install grok-bot      # scaffold: SKILL.md, HOST.md, mcp.example.json
agentdescent doctor                # host grok-bot: ok (skill ok, mcp n/a; ...)
```

There is no host config to check: Grok Bot has no public plugin API for a local
skill directory or a stdio MCP server, so `install` only writes the scaffold
under `~/.agentdescent/plugins/grok-bot/`. Save the skill in the Bot and drive
runs with the CLI, or serve the tools with
`agentdescent mcp --transport streamable-http` behind an HTTPS tunnel and add
the tunnel URL (ending in `/mcp`) as a custom MCP server — see
[the plugin quickstart](plugin-quickstart.md#grok-bot).

### Driving each host without a terminal session

The plain-language test below is the real one, but each host also has a
non-interactive form worth having in a script. All three were run end to end
against a real endpoint; each carries one thing that is not obvious.

**Claude Code.** `--permission-mode bypassPermissions` is refused by the safety
classifier when an automated caller asks for it, so name the tools:

```bash
P=mcp__plugin_agentdescent_agentdescent
claude -p "improve ./prompt.txt against ./cases.jsonl" \
  --plugin-dir ~/.agentdescent/plugins/claude-code \
  --allowedTools "Read,Glob,Grep,${P}__doctor,${P}__plan,${P}__start,${P}__status,${P}__show,${P}__apply"
```

`-p` is stateless. It stops for your yes as the contract requires; continue
with `claude -c -p "yes, start it"`.

**Codex.** The sandbox flag matters more than anything else here:

```bash
codex exec --skip-git-repo-check -s workspace-write \
  -c 'sandbox_workspace_write.network_access=true' \
  "improve ./prompt.txt against ./cases.jsonl, run it to completion"
```

Without `network_access=true` the run *starts*, burns a full round and then
dies with `URLError: [Errno 8] nodename nor servname provided`. The Seatbelt
sandbox blocks the network, the MCP server is a child of `codex`, and the
detached run inherits that — the same "a detached run inherits its launcher's
environment" trap as §8, wearing a different hat. Nothing about the message
points at the sandbox.

**DSH.** `dsh --profile headless "<task>"` answers one task and exits. Its
default provider is `deepseek-official`, so without `DEEPSEEK_API_KEY` you get
`MISSING_CREDENTIAL` before anything else happens. To point it at another
OpenAI-compatible endpoint, override the provider by id in a patch overlay —
a bare row is an override, which is why there is no `- insert:` here:

```yaml
# ark.patch.yml
- id: llm-deepseek
  config:
    baseURL: https://your-endpoint/v3
    apiKeyEnv: YOUR_KEY_VAR
```

```bash
dsh --profile headless --patch ./ark.patch.yml "improve ./prompt.txt against ./cases.jsonl"
```

The `headless` profile installs its own dependencies on first boot through
corepack, which must be new enough for the pnpm the profile pins — the same
corepack requirement the dsh tests in §9 skip on.

## 4. Drive it in plain language

This is the actual test. Make a target and some examples:

!!! tip "No cases yet? Skip the next block and just ask."
    Drafting them is step one of the procedure, not a prerequisite for it — the
    skill's own description says so. Point it at a bare `prompt.txt` and it
    writes 8–20 cases into `eval/cases.jsonl` and **stops for you to read
    them**. Measured on a support-agent prompt with no data and no spec: twelve
    cases, whose `gold` came back as behavioural rubrics ("acknowledges the
    frustration without grovelling; does not promise a refund; asks for the
    invoice number") rather than keyword strings, followed by the observation
    that `contains` cannot score that and an offer of `{"cmd": "./grade.sh"}`
    instead. Reviewing those cases is the one step you cannot skip: the search
    optimises whatever you scored it on, very efficiently.

```bash
mkdir -p /tmp/try && cd /tmp/try
cat > prompt.txt <<'EOF'
Answer the question.
EOF
python3 - <<'EOF'
import json
rows = [("What is the capital of France?", "FINAL Paris"),
        ("What is the capital of Japan?", "FINAL Tokyo"),
        ("What is the chemical symbol for gold?", "FINAL Au"),
        ("What is the capital of Italy?", "FINAL Rome"),
        ("What is the chemical symbol for iron?", "FINAL Fe"),
        ("What is the capital of Egypt?", "FINAL Cairo"),
        ("What is the chemical symbol for sodium?", "FINAL Na"),
        ("What is the capital of Canada?", "FINAL Ottawa"),
        ("What is the chemical symbol for potassium?", "FINAL K"),
        ("What is the capital of Spain?", "FINAL Madrid"),
        ("What is the chemical symbol for silver?", "FINAL Ag"),
        ("What is the capital of Greece?", "FINAL Athens")]
open("cases.jsonl", "w").write(
    "\n".join(json.dumps({"prompt": p, "gold": g}) for p, g in rows) + "\n")
EOF
```

The prompt scores **zero** — every gold answer is prefixed `FINAL` and the
prompt never says so. Nothing states the rule anywhere; it is discoverable only
from the failures.

Now open your agent in that directory and say:

> Improve `/tmp/try/prompt.txt` against the examples in `/tmp/try/cases.jsonl`.

What should happen, in order — this is the skill's whole contract:

1. it runs **`doctor`** and reports anything missing;
2. it writes a spec and runs **`plan`**, and **shows you the call count before
   starting**;
3. it waits for your yes;
4. it starts, polls, and reports what changed;
5. it **does not apply** without asking, and names the backup path when it does.

The run typically ends at reward `1.0` having learned something equivalent to
*"Start your final response with FINAL followed by the answer."* It is a search,
not a guarantee — of five runs of this exact task, four reached 1.0 in the first
round and one proposed nothing at all, for the reason in the next paragraph.

**If it finishes with reward 0 and `outcomes: {}`, read `considered` in the
rounds, not the reward.** `considered: 0` every round means no evidence card
was ever proposed — the reflector could not run, which is a configuration
problem, not a failed search. The commonest cause is a spec with
`"reflect": {"ref": "host_model"}` resumed from a shell instead of from the
agent: `host_model` borrows *the host that started the run*, and a shell is not
one. `evolve` and `resume` warn about this now; a run that predates the warning
just goes quiet.

### Things worth trying deliberately

| Try saying | What should happen |
|---|---|
| "improve this skill" with **no examples** | it offers to draft 8–20 cases and **stops for you to check them** |
| "use 60 rounds and 32 workers" | it quotes the cost **before** starting, even if you said not to ask |
| "apply it" | it names the file it would overwrite, then backs up and reports the path |
| "stop the run" | `cancel` kills the workers too, and it tells you what you lose |
| ask it to evolve **a plugin** | it sets `host`, and refuses to start a nested run from inside a worker |

!!! note "Add `reflective_merge`, or the workers are not merging"
    `prompt.txt` is a one-key artifact, and under the **shipped** conflict rule
    its worker proposals contradict by construction: they collapse to a single
    candidate and no fusion is ever built. Four workers there are per-round
    best-of-N selection. `plan` warns when a spec is in that shape.

    Installing the reflective pair is what makes it a merge, and it is what you
    want by default:

    ```json
    "policies": {
      "reflective_merge": {
        "ref": "reflective_merge",
        "complete": {"ref": "openai_compatible", "model": "your-model"}
      }
    }
    ```

    Measured on this exact scenario, with and without. Default: four proposals,
    three dropped as conflicts, `n_candidates: 1`, `single-candidate`, no
    fusion. With `reflective_merge`: `conflicts_dropped: 0`, `n_candidates: 4`,
    `fused: 1`, and the ledger reads
    `merge synth(w0:value:1+w1:value:1+w2:value:1+w3:value:1)` -- all four
    workers synthesised into the committed candidate. Same on a multi-file
    skill directory, where one round also came back `synthesis-failed` and fell
    back to the best single, which is the fallback working rather than a fault.

    Read `contested` in `fusion_stats()`, or `fusion_trials` in `result.json`,
    rather than inferring the merge from the worker count.

## 5. Using a real model

Two ways, neither needing a spec change beyond one field.

**A provider key.** For an OpenAI-compatible endpoint:

```bash
export OPENAI_API_KEY=...
export OPENAI_BASE_URL=https://your-endpoint/v1     # if not OpenAI itself
```

`doctor` reports the base URL back, because a non-OpenAI endpoint has its own
model names — the agent will **ask you which model** rather than guessing, and
that is correct behaviour, not a stall.

**The host's own model**, no key at all:

```json
"reflect": {"ref": "host_model"}
```

`host_model` uses MCP sampling where the host supports it and otherwise runs
that host's CLI with your real configuration. Measured: **no host implements
sampling today** — Claude Code declares `roots` and `elicitation`, OpenCode
`roots`, dsh nothing — so in practice it takes the CLI route. `start` reports
`host_model_route` so you can see which one you got.

!!! warning "Worker isolation and logins"
    A worker runs with the host's config directory redirected, so **a CLI you
    signed into interactively is not signed in for the run**. Use
    `"isolate": false` to hand it your real setup, or supply a provider key.
    `plan` warns about this now. One measured trap: `codex` ignores both
    `OPENAI_API_KEY` and `OPENAI_BASE_URL` — it called `api.openai.com`
    unauthenticated — so for codex, `"isolate": false` is the only route.

## 6. The MCP server on its own

Independent of any host, using the protocol SDK as a client:

```python
import asyncio, os, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(command="agentdescent", args=["mcp"], env={**os.environ})
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            print(sorted(t.name for t in (await s.list_tools()).tools))
            print((await s.call_tool("doctor", {})).content[0].text[:200])

asyncio.run(main())
```

Expected tools (Path A default): `algorithm_spec apply cancel describe_algorithm diagnose doctor list_algorithms plan resume show start status` (12 tools). With `agentdescent mcp --advanced` / `AGENTDESCENT_MCP_ADVANCED=1`, the full set is also registered: `algorithm_spec apply audit_drift audit_pending audit_recompute audit_rescan audit_resolve audit_scorecard audit_status audit_trace cancel capability describe_algorithm diagnose doctor experience_cycle experience_ingest experience_recall experience_replay experience_report experience_update governed_harness list_algorithms meta_campaign ops plan platform platform_status portfolio release release_verify resume rsi safety show start status tenant traces_digest` (39 total). See [MCP Path A](mcp-path-a.md).

## 7. The web panel

```bash
agentdescent serve                     # http://127.0.0.1:8787/
curl -s localhost:8787/api/runs | head -c 200
```

The page lists runs and refreshes itself. In dsh's web UI the plugin adds an
`evolve` action to the session header with the live count; clicking it shows the
same list. If the panel says *"No run panel"*, `agentdescent serve` is not
running.

## 8. When something is wrong

```bash
agentdescent doctor        # what is missing, in one screen
agentdescent status        # every run, newest first
agentdescent show <id>     # the diff, and the file apply would overwrite
agentdescent serve         # a read-only panel on http://127.0.0.1:8787/
```

Run logs are at `~/.agentdescent/runs/<id>/log.txt`, and the spec that produced
them sits beside it, re-runnable from anywhere.

Two failure modes worth recognising:

* **A run fails with `Connection refused` partway through.** A detached run
  inherits the environment of whatever launched it, including a proxy. If that
  process was short-lived — a headless `claude -p`, say — the run loses its
  network when it exits. `agentdescent resume <id>` picks it up on the same
  ledger from somewhere longer-lived.
* **A run finishes having proposed nothing** — reward 0, `outcomes: {}`, and
  `considered: 0` in every round of `rounds.jsonl`. The reflector never
  produced a card. Check `start`'s reply for `host_model_available` /
  `host_model_unavailable`, and the warnings `evolve` and `resume` print. A
  `host_model` spec resumed from a shell does exactly this: it has no host to
  borrow from, so every proposal raises and the rounds pass in silence.

## 9. Running the test suite

```bash
pip install -e ".[dev,mcp]"
pytest tests/test_evolvespec.py tests/test_runstore_cli.py tests/test_mcp.py \
       tests/test_plugin_runner.py tests/test_integrations.py \
       tests/test_run_panel.py tests/test_stop_when.py tests/test_demo.py \
       tests/test_host_sampling.py
```

That is the whole plugin surface, offline, in about a minute — no credentials,
no host installed, no network.

| File | What it pins |
|---|---|
| `test_evolvespec.py` | every `kind` composes the `evolve()` call the quickstarts write; refs resolve inside the allowlist; a spec runs end to end with a stub agent |
| `test_runstore_cli.py` | a detached run really detaches, reports, resumes and cancels (with its workers); every CLI verb, including relative paths surviving the process boundary |
| `test_mcp.py` | the tool bodies, the nested-run stub, and — when `mcp` is installed — the real server's tool and resource registration |
| `test_plugin_runner.py` | `kind: plugin` against a stub host CLI: isolated host home, the validate gate, frozen hooks surviving a candidate that rewrites them, `env_passthrough` |
| `test_integrations.py` | every host manifest, the checked-in plugin packages matching their renderers, and the skill naming only tools/kinds/verbs that exist |
| `test_run_panel.py` | the HTTP panel, and that it refuses path traversal and non-loopback CORS |
| `test_demo.py` | `agentdescent demo` — the skill really is wrong, the offline agent really obeys the one on disk, and the run fixes it without touching your files |

Two of them reach further when the tools are present, and skip cleanly when not:

```bash
# drives the dsh plugin through dsh's own isSkillName validator
which dsh && pytest tests/test_integrations.py -k real_registry -q

# loads the browser bundle the way dsh's module loader does and renders it
mkdir -p /tmp/react-probe && cd /tmp/react-probe && npm init -y && npm i react react-dom
AGENTDESCENT_NODE_PROBE=/tmp/react-probe pytest tests/test_integrations.py -k client_bundle -q
```

## 10. What no test here can tell you

Be aware of these rather than assume they are covered.

* **Whether the dsh panel looks right.** The bundle is checked for loading,
  registering into `conversation.session.header.actions` and rendering HTML
  through React. Whether it is *legible in the actual UI* needs a browser and a
  dsh session.
* **A full Codex or DSH session.** Both were verified at the config layer
  (`codex mcp list`, `dsh --dump-config`) because neither had credentials here.
  Claude Code and OpenCode were driven to the point of tools returning data.
* **`kind: plugin` against a real dsh plugin repo.** The host table is
  exercised with a stub host CLI; the `pnpm install && pnpm build` chain in the
  dsh row has not been run against a real Cordis package.
* **Cost.** Every number `plan` reports is an upper bound on *calls*; the
  dollar figure only appears when you give it a per-call price. Run a real
  evolution with `--budget` and a small `rounds` the first time.
