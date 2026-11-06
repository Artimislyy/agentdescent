(() => {
  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => [...document.querySelectorAll(selector)];
  const copy = async (text, button) => {
    try {
      await navigator.clipboard.writeText(text);
      const before = button.textContent;
      button.textContent = 'Copied ✓';
      setTimeout(() => { button.textContent = before; }, 1300);
    } catch (_) {
      button.title = 'Clipboard unavailable; select the adjacent text to copy.';
    }
  };
  $$('[data-copy]').forEach((button) => button.addEventListener('click', () => copy(button.dataset.copy, button)));

  const page = $('.experience');
  const themeButton = $('.theme-toggle');
  if (page && themeButton) {
    let theme = 'light';
    try { theme = localStorage.getItem('agentdescent-theme-v2') || 'light'; } catch (_) { /* storage may be unavailable */ }
    const setTheme = (next) => {
      page.dataset.theme = next;
      themeButton.innerHTML = next === 'dark' ? '☀ <span>Light mode</span>' : '☾ <span>Dark mode</span>';
      themeButton.setAttribute('aria-label', next === 'dark' ? 'Switch to light mode' : 'Switch to dark mode');
      try { localStorage.setItem('agentdescent-theme-v2', next); } catch (_) { /* storage may be unavailable */ }
    };
    setTheme(theme);
    themeButton.addEventListener('click', () => setTheme(page.dataset.theme === 'dark' ? 'light' : 'dark'));
  }

  // Keep Material documentation pages in the same color mode as the landing pages.
  if (!page) {
    const paletteOptions = $$('input[data-md-color-scheme]');
    let savedTheme;
    try { savedTheme = localStorage.getItem('agentdescent-theme-v2'); } catch (_) { /* storage may be unavailable */ }
    if (savedTheme === 'dark' || savedTheme === 'light') {
      const scheme = savedTheme === 'dark' ? 'slate' : 'default';
      const option = paletteOptions.find((input) => input.dataset.mdColorScheme === scheme);
      if (option) { option.checked = true; document.body.dataset.mdColorScheme = scheme; }
    }
    paletteOptions.forEach((input) => input.addEventListener('change', () => {
      const next = input.dataset.mdColorScheme === 'slate' ? 'dark' : 'light';
      try { localStorage.setItem('agentdescent-theme-v2', next); } catch (_) { /* storage may be unavailable */ }
    }));
  }

  const hosts = {
    claude: {name: 'CLAUDE CODE', label: 'Claude Code', setup: 'agentdescent install claude-code\nclaude --plugin-dir ~/.agentdescent/plugins/claude-code', help: 'Start Claude Code with the plugin directory. In the session, /plugin lists it.'},
    codex: {name: 'CODEX', label: 'Codex', setup: 'codex plugin marketplace add ThinkFlowLab/agentdescent\ncodex plugin add agentdescent@agentdescent\ncodex mcp list', help: 'The marketplace plugin includes the AgentDescent MCP server. Confirm that codex mcp list shows it.'},
    opencode: {name: 'OPENCODE', label: 'OpenCode', setup: 'agentdescent install opencode\nopencode mcp list', help: 'Restart OpenCode after installation and check that AgentDescent is connected.'},
    dsh: {name: 'DEEPSEEK HARNESS', label: 'DeepSeek Harness', setup: 'agentdescent install dsh\ndsh --profile web --dump-config | grep agentdescent', help: 'Restart DeepSeek Harness and check that its configuration contains AgentDescent.'}
  };
  const oneClickCommand = 'curl -fsSL https://raw.githubusercontent.com/ThinkFlowLab/agentdescent/main/scripts/install.sh | bash';
  const pipCommand = "python3 -m pip install --upgrade 'agentdescent[mcp] @ git+https://github.com/ThinkFlowLab/agentdescent.git@main'";
  const hostOpen = {
    claude: {label:'LAUNCH CLAUDE CODE', command:'claude --plugin-dir ~/.agentdescent/plugins/claude-code', help:'The installer writes a local plugin directory. Launch Claude Code with it.'},
    codex: {label:'VERIFY CODEX', command:'codex mcp list', help:'Restart Codex, then check that the agentdescent MCP server is enabled.'},
    opencode: {label:'VERIFY OPENCODE', command:'opencode mcp list', help:'Restart OpenCode, then check that agentdescent is connected.'},
    dsh: {label:'VERIFY DEEPSEEK HARNESS', command:'dsh --profile web --dump-config | grep agentdescent', help:'Restart DeepSeek Harness, then confirm its config contains agentdescent.'}
  };
  let installMode = 'script';
  let selectedHost = 'claude';
  const renderHost = () => {
    const display = installMode === 'script' ? hostOpen[selectedHost] : {
      label: `CONNECT ${hosts[selectedHost].name}`,
      command: hosts[selectedHost].setup,
      help: hosts[selectedHost].help
    };
    if ($('#qs3-host-label')) $('#qs3-host-label').textContent = display.label;
    if ($('#qs3-host-command')) $('#qs3-host-command').textContent = display.command;
    if ($('#qs3-host-help')) $('#qs3-host-help').textContent = display.help;
  };
  $$('.qs3-tabbar button').forEach((button) => button.addEventListener('click', () => {
    installMode = button.dataset.installMode;
    $$('.qs3-tabbar button').forEach((item) => { item.classList.toggle('active', item === button); item.setAttribute('aria-selected', String(item === button)); });
    $('#qs3-install-command').textContent = installMode === 'script' ? oneClickCommand : pipCommand;
    $('#qs3-install-note').textContent = installMode === 'script'
      ? 'Installs AgentDescent and connects the agent CLIs already on your PATH.'
      : 'Installs current main with pip. Use the host setup command in step 02.';
    renderHost();
  }));
  $$('.qs3-host-tabs button').forEach((button) => button.addEventListener('click', () => {
    selectedHost = button.dataset.host;
    $$('.qs3-host-tabs button').forEach((item) => { item.classList.toggle('active', item === button); item.setAttribute('aria-selected', String(item === button)); });
    renderHost();
  }));
  $('#qs3-copy-install')?.addEventListener('click', (event) => copy($('#qs3-install-command').textContent, event.currentTarget));
  $('#qs3-copy-host')?.addEventListener('click', (event) => copy($('#qs3-host-command').textContent, event.currentTarget));
  $('#qs3-copy-prompt')?.addEventListener('click', (event) => copy($('#qs3-prompt-text').textContent, event.currentTarget));
  $$('.host-tabs button').forEach((button) => button.addEventListener('click', () => {
    $$('.host-tabs button').forEach((item) => { item.classList.toggle('active', item === button); item.setAttribute('aria-selected', String(item === button)); });
    const host = hosts[button.dataset.host];
    $('#qs-host-command').textContent = host.setup;
    $('#qs-host-help').textContent = host.help;
  }));
  $('#qs-host-copy')?.addEventListener('click', (event) => copy($('#qs-host-command').textContent, event.currentTarget));

  const recipes = {
    base: {
      kicker: 'DEFAULT',
      title: 'Start with one artifact.',
      copy: 'The same entry point handles the task, reward, actor and artifact strategy. Unspecified policy slots use their defaults.',
      code: 'evolve(tasks, reward, agent=agent,\n       strategy=FileTree(files),\n       policies=Policies())',
      note: 'Illustrative configuration · supply your own tasks, reward, agent and files.'
    },
    search: {
      kicker: 'SELECTION + SAMPLING',
      title: 'Search a wider frontier.',
      copy: 'A beam keeps several candidates in play while difficulty-weighted sampling spends more work on useful tasks. The artifact and reward stay the same.',
      code: 'evolve(tasks, reward, agent=agent,\n       strategy=FileTree(files),\n       policies=Policies(\n           selection=Beam(4),\n           task_sampler=DifficultyWeighted()))',
      note: 'Change only the decisions this algorithm needs.'
    },
    merge: {
      kicker: 'CONFLICT + FUSION',
      title: 'Change how diffs combine.',
      copy: 'Reflective merge installs a paired conflict resolver and fusion policy. Compatible edits can be combined before the acceptance gate.',
      code: 'evolve(tasks, reward, agent=agent,\n       strategy=FileTree(files),\n       policies=Policies(\n           **reflective_merge(completion)))',
      note: 'The same loop still handles workers, evaluation and versioning.'
    },
    custom: {
      kicker: 'OPTIMIZER EXIT',
      title: 'Bring your own algorithm.',
      copy: 'If your method needs a population, an archive or state that individual policy slots do not keep, supply an aggregator factory.',
      code: 'evolve(tasks, reward, agent=agent,\n       strategy=my_strategy,\n       aggregator_factory=my_optimizer_factory)',
      note: 'Use a custom Strategy for your artifact and an optimizer for its search rule.'
    }
  };
  $$('.recipe-options button').forEach((button) => button.addEventListener('click', () => {
    $$('.recipe-options button').forEach((item) => { item.classList.toggle('active', item === button); item.setAttribute('aria-selected', String(item === button)); });
    const recipe = recipes[button.dataset.recipe];
    $('#recipe-kicker').textContent = recipe.kicker;
    $('#recipe-title').textContent = recipe.title;
    $('#recipe-copy').textContent = recipe.copy;
    $('#recipe-code').textContent = recipe.code;
    $('#recipe-note').textContent = recipe.note;
  }));

  const artifacts = {
    prompt: {kicker: 'SINGLE SLOT STRATEGY', title: 'Evolve one instruction.', copy: 'Replace a single value and compare candidates against the tasks you care about.', filename: 'prompt.md', preview: 'You are a helpful assistant.\n\n+ Respond with only the requested answer.\n+ Omit extra explanation and restatement.', link: 'quickstart-skill/', linkText: 'Read the prompt quickstart'},
    skill: {kicker: 'FILE TREE STRATEGY', title: 'Grow a skill library.', copy: 'Treat paths in a folder as independent keys. Workers can edit separate files, then the aggregator fuses compatible changes.', filename: 'skills/pdf-audit/SKILL.md', preview: '# PDF audit\n\n+ Verify every section before reporting.\n+ Cite the page for each finding.\n\nreferences/rules.md  ·  unchanged', link: 'quickstart-directory/', linkText: 'Read the directory quickstart'},
    code: {kicker: 'PROGRAM + HARNESS STRATEGIES', title: 'Change executable behavior.', copy: 'Evolve a program or agent harness while keeping its evaluation tasks and protected files outside the search.', filename: 'agent/solver.py', preview: 'def solve(task):\n    context = retrieve(task)\n+   context = rank_evidence(context)\n    return answer(context, task)', link: 'quickstart-agent-code/', linkText: 'Read the code quickstart'},
    custom: {kicker: 'YOUR STRATEGY', title: 'Represent your own artifact.', copy: 'Define initial state, rendering and proposal-to-diff conversion. The same engine can then evaluate and merge your representation.', filename: 'my_strategy.py', preview: 'class MyStrategy:\n    def initial(self): ...\n    def render(self, state): ...\n    def to_diff(self, state, proposal, author, base_version, target): ...', link: 'strategies/', linkText: 'Write a custom Strategy'}
  };
  $$('.artifact-picker button').forEach((button) => button.addEventListener('click', () => {
    $$('.artifact-picker button').forEach((item) => { item.classList.toggle('active', item === button); item.setAttribute('aria-selected', String(item === button)); });
    const artifact = artifacts[button.dataset.artifact];
    $('#artifact-kicker').textContent = artifact.kicker;
    $('#artifact-title').textContent = artifact.title;
    $('#artifact-copy').textContent = artifact.copy;
    $('#artifact-filename').textContent = artifact.filename;
    $('#artifact-preview').textContent = artifact.preview;
    $('#artifact-link').href = artifact.link;
    $('#artifact-link').innerHTML = `${artifact.linkText} <span>↗</span>`;
  }));

  // ---------------------------------------------------------------------------
  // Interactive agent demo.
  //
  // A browser-only replay of the procedure the shipped skill asks a host agent
  // to follow (agentdescent/integrations/SKILL.md): doctor -> spec -> plan ->
  // wait for a yes -> start -> poll status -> show diff=true -> ask -> apply.
  // Slash commands, MCP tool names, default skill folders, output fields, the
  // plan estimate and the backup locations mirror the code in this repository
  // (integrations/__init__.py, mcp.py, cli.py, evolution.py). Rewards, call
  // counts and diffs are a sample run: nothing here calls a model or a server.
  // ---------------------------------------------------------------------------
  const demoBody = $('#demo-chat-body');
  if (!demoBody) return;
  const ARK_URL = 'https://ark.cn-beijing.volces.com/api/coding/v3';
  const HOME = '/home/you';
  const PROJECT = `${HOME}/project`;
  const demoHosts = {
    claude: {
      title: 'CLAUDE CODE', cli: 'claude', hostKey: 'claude-code', agentRef: 'claude_code',
      skillRoot: '~/.claude/skills', slash: '/agentdescent:evolve', prompt: '>', bullet: '●', out: '⎿',
      call: (tool, args) => `agentdescent - ${tool} (MCP)${args ? `(${args})` : ''}`
    },
    codex: {
      title: 'CODEX', cli: 'codex', hostKey: 'codex', agentRef: 'codex',
      skillRoot: '~/.codex/skills', slash: '/prompts:evolve', prompt: '›', bullet: '•', out: '└',
      call: (tool, args) => `Called agentdescent.${tool}(${args || '{}'})`
    },
    opencode: {
      title: 'OPENCODE', cli: 'opencode', hostKey: 'opencode', agentRef: 'opencode',
      skillRoot: '~/.config/opencode/skill', slash: '/agentdescent/evolve', prompt: '>', bullet: '●', out: '│',
      call: (tool, args) => `agentdescent_${tool}${args ? `  ${args}` : ''}`
    },
    dsh: {
      title: 'DEEPSEEK HARNESS', cli: 'dsh', hostKey: 'dsh', agentRef: 'dsh',
      // dsh has no slash surface: the skill is picked up from a plain request.
      skillRoot: '~/.dsh/skills', slash: null, prompt: '>', bullet: '●', out: '└',
      call: (tool, args) => `mcp-agentdescent · ${tool}${args ? `(${args})` : ''}`
    }
  };
  const reflect = `{"ref": "openai_compatible", "model": "deepseek-v4-flash", "api_key_env": "ARK_API_KEY", "default_base_url": "${ARK_URL}"}`;
  // Plan estimates are what `agentdescent plan` returns for 12 cases, 2 rounds,
  // 2 workers and the default held_out_frac 0.3 (text adds self_verify calls).
  const demoKinds = {
    skill: {
      kind: 'skill_dir', noun: 'skill', path: (host) => `${host.skillRoot}/pdf-audit`, score: 'contains',
      agent: (host) => `{"ref": "${host.agentRef}"}`, reflect: true,
      calls: {rollouts: 2, proposals: 2, self_verify: 0, ranking: 8, gate: 4}, upper: 36,
      // Rewards, calls and timings follow a recorded skill_dir run (opencode worker,
      // deepseek-v4-flash reflector on Ark): 0.000 -> 0.750 in 23 calls, 2m13s.
      rewards: [0, 0, 0.75], outcomes: [{'below-threshold': 1}, {committed: 1}], roundCalls: [15, 23], elapsed: [59, 133], tokens: 4356,
      backup: 'dir', file: 'SKILL.md',
      diff: [
        '--- a/SKILL.md', '+++ b/SKILL.md', '@@ -6,5 +6,7 @@ description: Audit a PDF report against references/rules.md',
        ' # PDF audit', ' ', ' 1. Read `references/rules.md` before opening the PDF.',
        '-2. Report every finding you see.', '-3. Reply with a short summary.',
        '+2. Check each numbered section in order; flag missing pages', '+   (an appendix listed in the contents but absent from the file).',
        '+3. Cite the page for every finding as `p. N`.', '+4. Reply with one line per finding, then `OK` or `FAIL`.'
      ],
      why: 'the missing-appendix and page-citation cases now pass'
    },
    prompt: {
      kind: 'text', noun: 'prompt', path: () => './prompts/answer.md', score: 'contains',
      // A text artifact is answered by a model, never by a CLI coding agent.
      agent: () => `{"ref": "openai_compatible", "model": "deepseek-v4-flash", "api_key_env": "ARK_API_KEY", "default_base_url": "${ARK_URL}"}`, reflect: false,
      calls: {rollouts: 2, proposals: 2, self_verify: 2, ranking: 8, gate: 4}, upper: 40,
      rewards: [0.5, 0.5, 0.75], outcomes: [{'below-threshold': 1}, {committed: 1}], roundCalls: [17, 31], elapsed: [41, 88], tokens: 6120,
      backup: 'file', file: 'answer.md',
      diff: [
        '--- a/answer.md', '+++ b/answer.md', '@@ -1,3 +1,5 @@',
        ' You are a support assistant for Acme Cloud.', "-Answer the user's question.",
        "+Answer the user's question in at most three sentences.", '+Quote the doc section you used as [doc: <title>].',
        '+If the docs do not cover it, say so instead of guessing.', ' Be polite.'
      ],
      why: 'answers now cite the doc section the gold expects'
    },
    code: {
      kind: 'agent_code', noun: 'agent code', path: () => './agent', score: 'contains',
      agent: (host) => `{"ref": "${host.agentRef}"}`, reflect: true, entrypoint: '["python", "run_agent.py"]',
      calls: {rollouts: 2, proposals: 2, self_verify: 0, ranking: 8, gate: 4}, upper: 36,
      rewards: [0.25, 0.5, 0.5], outcomes: [{committed: 1}, {'below-threshold': 1}], roundCalls: [15, 26], elapsed: [74, 151], tokens: 5208,
      backup: 'dir', file: 'solver.py',
      diff: [
        '--- a/solver.py', '+++ b/solver.py', '@@ -8,2 +8,3 @@ def solve(task):',
        '     context = retrieve(task, k=8)', '+    context = rank_evidence(context, task)[:4]', '     return answer(context, task)'
      ],
      why: 'ranking the retrieved evidence fixed two held-out answers; the round-1 candidate did not beat it'
    }
  };
  let activeHost = 'claude';
  let activeKind = 'skill';
  let phase = 0;
  // A restart invalidates every delayed continuation from the previous demo.
  let conversation = 0;
  let scenario;
  const approve = $('#demo-approve');
  const start = $('#demo-run');
  const status = $('#demo-status');
  const toolLine = $('#demo-tool-line');
  const announcer = $('#demo-live');
  const reduceMotion = typeof window !== 'undefined' && window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : {matches: false};
  const quick = () => reduceMotion.matches;
  const pause = (ms) => new Promise((resolve) => setTimeout(resolve, quick() ? Math.min(ms, 60) : ms));
  const fmt = (n) => (n === null || n === undefined ? 'null' : n.toFixed(3));
  const announce = (text) => { if (announcer) announcer.textContent = text; };
  const node = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  };
  const scrollDown = () => { demoBody.scrollTop = demoBody.scrollHeight; };
  const absolute = (path) => path.replace(/^~(?=\/|$)/, HOME).replace(/^\.\//, `${PROJECT}/`).replace(/^(?!\/)/, `${PROJECT}/`);
  const baseName = (path) => path.replace(/\/+$/, '').split('/').pop() || 'artifact';
  const shortHash = (text) => {
    let h1 = 0x811c9dc5; let h2 = 0x1b873593;
    for (const ch of text) { h1 = Math.imul(h1 ^ ch.charCodeAt(0), 16777619) >>> 0; h2 = Math.imul(h2 ^ ch.charCodeAt(0), 2246822519) >>> 0; }
    return (h1.toString(16).padStart(8, '0') + h2.toString(16).padStart(8, '0')).slice(0, 12);
  };
  const runId = () => {
    const d = new Date(); const p = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}-${shortHash(String(d.getTime())).slice(0, 6)}`;
  };
  // Type text into an element one character at a time (instant with reduced motion).
  async function typeInto(element, text, run, perChar = 18) {
    if (quick()) { element.textContent = text; return run === conversation; }
    for (let i = 1; i <= text.length; i += 2) {
      if (run !== conversation) return false;
      element.textContent = text.slice(0, i); scrollDown();
      await pause(perChar);
    }
    element.textContent = text; scrollDown();
    return run === conversation;
  }
  async function userTurn(text, run) {
    const host = scenario.host;
    const row = node('div', 'demo-message user');
    row.append(node('span', 'message-icon', host.prompt));
    const body = node('div', 'message-content');
    const line = node('p', 'demo-prompt');
    body.append(node('small', '', 'YOU'), line); row.append(body); demoBody.append(row);
    const ok = await typeInto(line, text, run, 14);
    announce(`You: ${text}`);
    return ok;
  }
  async function agentTurn(text, run) {
    const host = scenario.host;
    const row = node('div', 'demo-message agent');
    row.append(node('span', 'message-icon', host.bullet));
    const body = node('div', 'message-content');
    const paragraph = node('p', 'demo-stream');
    body.append(node('small', '', host.title), paragraph); row.append(body); demoBody.append(row);
    if (!quick()) {
      paragraph.classList.add('streaming');
      const words = text.split(/(\s+)/);
      let shown = '';
      for (const word of words) {
        if (run !== conversation) return false;
        shown += word; paragraph.textContent = shown; scrollDown();
        if (word.trim()) await pause(22);
      }
      paragraph.classList.remove('streaming');
    }
    paragraph.textContent = text; scrollDown();
    announce(text);
    return run === conversation;
  }
  // A tool-call block in the host's own style, with a short spinner and a
  // truncated result, as hosts collapse long MCP output.
  async function toolCall(tool, args, output, run, {hidden = 0, wait = 650, label} = {}) {
    const host = scenario.host;
    const block = node('div', 'demo-tool');
    const head = node('div', 'demo-tool-head');
    head.append(node('span', 'demo-tool-bullet', host.bullet), node('code', '', label || host.call(tool, args)));
    const state = node('span', 'demo-tool-state', 'running…');
    head.append(state);
    block.append(head); demoBody.append(block); scrollDown();
    toolLine.textContent = label ? label : `agentdescent.${tool} · running`;
    await pause(wait);
    if (run !== conversation) return false;
    state.textContent = ''; state.classList.add('done');
    const pre = node('pre', 'demo-tool-out');
    output.forEach((line, index) => {
      const row = node('span', '', `${index === 0 ? host.out : ' '}  ${line}`);
      pre.append(row, document.createTextNode('\n'));
    });
    if (hidden) pre.append(node('span', 'demo-tool-more', `   … +${hidden} lines`));
    block.append(pre); scrollDown();
    return run === conversation;
  }
  function diffBlock(lines) {
    const block = node('div', 'demo-diff');
    const pre = node('pre');
    lines.forEach((line) => {
      let cls = '';
      if (line.startsWith('+++') || line.startsWith('---')) cls = 'meta';
      else if (line.startsWith('@@')) cls = 'hunk';
      else if (line.startsWith('+')) cls = 'add';
      else if (line.startsWith('-')) cls = 'del';
      pre.append(node('span', cls, line), document.createTextNode('\n'));
    });
    block.append(pre); demoBody.append(block); scrollDown();
  }
  function progressPanel(rounds) {
    const panel = node('div', 'demo-progress');
    panel.setAttribute('aria-label', 'Sample run progress');
    const top = node('div', 'demo-progress-top');
    const title = node('strong', '', 'run 0/2'); const meta = node('span', '', 'phase=start');
    top.append(title, meta);
    const bars = node('div', 'demo-progress-bars');
    const labels = ['seed', ...Array.from({length: rounds}, (_, i) => `round ${i}`)];
    const cells = labels.map((text) => {
      const cell = node('div', 'demo-bar');
      const fill = node('i'); const value = node('b', '', '—');
      cell.append(fill, value, node('small', '', text)); bars.append(cell);
      return {cell, fill, value};
    });
    panel.append(top, bars, node('p', 'demo-progress-note', 'held-out reward on 4 cases · sample run, time compressed'));
    demoBody.append(panel); scrollDown();
    return {
      set(round, phaseText, calls, pending, best, elapsed) {
        const clock = elapsed === undefined ? '' : ` · ${Math.floor(elapsed / 60)}:${String(Math.round(elapsed) % 60).padStart(2, '0')}`;
        title.textContent = `round ${round}/${rounds}${clock}`;
        meta.textContent = `calls=${calls} pending=${pending} ${phaseText ? `phase=${phaseText}` : ''} best=${fmt(best)}`.replace(/\s+/g, ' ');
      },
      bar(index, reward, outcome) {
        const c = cells[index]; if (!c) return;
        c.fill.style.height = `${Math.max(4, reward * 100)}%`;
        c.value.textContent = fmt(reward);
        c.cell.classList.add(outcome || 'seed');
      }
    };
  }
  function setActive(selector, selected) { $$(selector).forEach((button) => { const active = button === selected; button.classList.toggle('active', active); if (button.getAttribute('role') === 'tab') button.setAttribute('aria-selected', String(active)); }); }
  function defaultPath() { return demoKinds[activeKind].path(demoHosts[activeHost]); }
  // Only replace the path while it still holds a preset, so a typed path survives.
  function presetPaths() { return Object.values(demoKinds).flatMap((k) => Object.values(demoHosts).map((h) => k.path(h))); }
  function syncPath() { const input = $('#demo-path'); if (!input.value.trim() || presetPaths().includes(input.value.trim())) input.value = defaultPath(); }
  function syncInvocation() {
    const hint = $('#demo-invocation'); if (!hint) return;
    const host = demoHosts[activeHost];
    hint.textContent = host.slash ? `${host.slash} <path> [cases.jsonl]` : 'no slash command · ask in plain words';
  }
  $$('.demo-hosts button').forEach((button) => button.addEventListener('click', () => {
    activeHost = button.dataset.demoHost; setActive('.demo-hosts button', button);
    $('#demo-window-title').textContent = `${demoHosts[activeHost].title} / AGENTDESCENT`;
    syncPath(); syncInvocation();
  }));
  $$('.demo-presets button').forEach((button) => button.addEventListener('click', () => {
    activeKind = button.dataset.demoKind; setActive('.demo-presets button', button);
    $('#demo-path').value = defaultPath();
  }));
  syncInvocation();

  function waitFor(label, nextPhase) {
    approve.textContent = label; approve.hidden = false; phase = nextPhase;
  }

  start.addEventListener('click', async () => {
    const run = ++conversation;
    phase = 0; approve.hidden = true; demoBody.replaceChildren();
    start.innerHTML = 'Restart conversation <span>↺</span>';
    const host = demoHosts[activeHost];
    const kind = demoKinds[activeKind];
    const path = $('#demo-path').value.trim() || defaultPath();
    const target = absolute(path);
    const name = baseName(target);
    const cases = `${PROJECT}/eval/cases.jsonl`;
    const specPath = `${PROJECT}/.agentdescent/${name}.evolve.json`;
    scenario = {host, kind, path, target, name, cases, specPath, id: runId()};
    status.textContent = 'DOCTOR';
    const ask = host.slash
      ? `${host.slash} ${path} eval/cases.jsonl`
      : `Use agentdescent to improve the ${kind.noun} at ${path} against eval/cases.jsonl. Show me the plan first.`;
    if (!await userTurn(ask, run)) return;
    await pause(350);
    if (!await agentTurn('I\'ll run doctor first to check the worker agent, provider key and run store.', run)) return;
    const clis = Object.keys(demoHosts).map((k) => {
      const cli = demoHosts[k].cli;
      return `"${cli}": ${demoHosts[k] === host ? `"/usr/local/bin/${cli}"` : 'null'}`;
    }).join(', ');
    if (!await toolCall('doctor', '', [
      '{"version": "0.8.0",',
      ` "agent_clis": {${clis}, "git": "/usr/bin/git"},`,
      ' "provider_keys_present": {"ANTHROPIC_API_KEY": false, "OPENAI_API_KEY": false, "ARK_API_KEY": true},',
      ` "run_store": "${HOME}/.agentdescent/runs",`,
      ` "hosts": {"${host.hostKey}": "ok (skill ok, mcp ok; cli /usr/local/bin/${host.cli})"},`
    ], run, {hidden: 14, wait: 800})) return;
    await pause(300);
    status.textContent = 'SPEC';
    const workerNote = kind.kind === 'text'
      ? 'A prompt is answered by a model, so the agent is openai_compatible on ARK_API_KEY, not a coding CLI.'
      : `${host.cli} will be the worker that edits files, and a cheap reflect model reads ARK_API_KEY.`;
    if (!await agentTurn(`Doctor is clean: ARK_API_KEY is set and ${host.cli} is on PATH. ${workerNote} I\'ll write the spec with absolute paths and plan it.`, run)) return;
    const specLines = [
      `{"version": 1, "kind": "${kind.kind}",`,
      ` "target": "${target}",`,
      ` "data": {"path": "${cases}"},`,
      ` "score": "${kind.score}",`,
      ` "agent": ${kind.agent(host)},`
    ];
    if (kind.reflect) specLines.push(` "reflect": ${reflect},`);
    if (kind.entrypoint) specLines.push(` "entrypoint": ${kind.entrypoint}, "test_cmd": ["python", "-m", "pytest", "-q"],`);
    specLines.push(' "evolve": {"rounds": 2, "n_workers": 2}}');
    if (!await toolCall('write', '', specLines, run, {wait: 450, label: `Write ${specPath}`})) return;
    status.textContent = 'PLANNING';
    const c = kind.calls;
    if (!await toolCall('plan', `spec="${specPath}"`, [
      `{"ok": true, "tasks": 12, "warnings": [], "artifact_id": "${name}",`,
      ' "estimate": {"rounds": 2, "n_workers": 2, "tasks": 12, "held_out_tasks": 4, "seed_score_calls": 4,',
      `   "calls_per_round": {"rollouts": ${c.rollouts}, "proposals": ${c.proposals}, "self_verify": ${c.self_verify}, "ranking": ${c.ranking}, "gate": ${c.gate}},`,
      `   "agent_calls_upper_bound": ${kind.upper}, "usd_upper_bound": null},`,
      ' "notes": []}'
    ], run, {hidden: 41, wait: 900})) return;
    await pause(250);
    if (!await agentTurn(`Plan: 12 cases (4 held out for the gate), 2 rounds × 2 workers, at most ${kind.upper} agent calls. No per-call price is known, so there is no dollar estimate. Nothing has run yet and ${path} is unchanged. Start the run?`, run)) return;
    status.textContent = 'WAITING FOR YOU'; toolLine.textContent = 'plan ready · nothing started';
    waitFor('Yes, start the run ↗', 1);
  });

  approve.addEventListener('click', async () => {
    if (phase !== 1 && phase !== 2) return;
    const run = conversation;
    const s = scenario;
    approve.hidden = true;
    if (phase === 1) {
      phase = 0;
      if (!await userTurn('yes, start it', run)) return;
      status.textContent = 'RUNNING';
      if (!await toolCall('start', `spec="${s.specPath}"`, [
        `{"ok": true, "run_id": "${s.id}", "state": "running", "pid": 48213,`,
        ` "dir": "${HOME}/.agentdescent/runs/${s.id}", "notes": []}`
      ], run, {wait: 600})) return;
      if (!await agentTurn(`Started ${s.id} in the background. I\'ll poll status about once per round.`, run)) return;
      const k = s.kind; const r = k.rewards;
      const panel = progressPanel(2);
      panel.set(0, 'run', 0, 4, null, 0);
      // Seed sweep, then each round: propose -> run -> merge (the held-out gate).
      const [c0, c1] = k.roundCalls;
      const best0 = Math.max(r[0], r[1]);
      const steps = [
        [0, 'run', 4, 0, null, () => panel.bar(0, r[0])],
        [0, 'propose', 6, 2, r[0]], [0, 'run', Math.round((6 + c0) / 2), 2, r[0]], [0, 'merge', c0 - 1, 1, r[0], () => panel.bar(1, r[1], k.outcomes[0].committed ? 'committed' : 'rejected')],
        [1, 'propose', c0 + 1, 2, best0], [1, 'run', Math.round((c0 + c1) / 2), 2, best0], [1, 'merge', c1 - 1, 1, best0, () => panel.bar(2, r[2], k.outcomes[1].committed ? 'committed' : 'rejected')]
      ];
      let tick = 0;
      for (const [round, ph, calls, pending, best, after] of steps) {
        tick += 1;
        await pause(700);
        if (run !== conversation) return;
        const [e0, e1] = k.elapsed;
        const elapsed = tick <= 4 ? e0 * [0.12, 0.3, 0.65, 0.95][tick - 1] : e0 + (e1 - e0) * [0.2, 0.6, 0.95][tick - 5];
        panel.set(round, ph, calls, pending, best, elapsed);
        toolLine.textContent = `${s.id} · round ${round}/2 · phase=${ph}`;
        if (after) after();
        if (ph === 'merge' && round === 0) {
          await pause(500);
          const o = k.outcomes[0];
          if (!await toolCall('status', `run_id="${s.id}"`, [
            `{"run_id": "${s.id}", "state": "running", "round": 1, "rounds": 2,`,
            ` "initial_reward": ${fmt(r[0])}, "best_reward": ${fmt(Math.max(r[0], r[1]))}, "committed": ${o.committed || 0},`,
            ` "calls": ${c0 + 1}, "pending_calls": 2, "phase": "propose", "usd": null,`,
            ` "recent_rounds": [{"round": 0, "held_out_reward": ${fmt(r[1])}, "committed": ${o.committed || 0}, "rejected": ${o.committed ? 0 : 1}, "reasons": ${JSON.stringify(o)}, "elapsed_s": ${k.elapsed[0]}.0}]}`
          ], run, {hidden: 12, wait: 450})) return;
          const said = o.committed
            ? `Round 0 committed one edit: held-out ${fmt(r[0])} → ${fmt(r[1])}. Round 1 is proposing.`
            : `Round 0: the one candidate was below-threshold on the held-out gate, so nothing was committed (still ${fmt(r[1])}). pending_calls=2 with phase=propose, so round 1 is alive.`;
          if (!await agentTurn(said, run)) return;
        }
      }
      await pause(600);
      if (run !== conversation) return;
      const best = Math.max(...r);
      panel.set(2, '', c1, 0, best, k.elapsed[1]);
      status.textContent = 'DONE';
      const outcomes = {};
      k.outcomes.forEach((o) => Object.entries(o).forEach(([key, n]) => { outcomes[key] = (outcomes[key] || 0) + n; }));
      if (!await toolCall('status', `run_id="${s.id}"`, [
        `{"run_id": "${s.id}", "state": "done", "round": 2, "rounds": 2, "best_reward": ${fmt(best)},`,
        ` "committed": ${outcomes.committed || 0}, "calls": ${c1}, "pending_calls": 0, "phase": null, "tokens": ${k.tokens}, "usd": null,`,
        ` "stop_reason": "rounds", "error": null, "kind": "${k.kind}", "target": "${s.target}"}`
      ], run, {hidden: 16, wait: 400})) return;
      const backup = s.kind.backup === 'file' ? `${s.target}.bak-0` : `${HOME}/.agentdescent/backups/${s.name}-${shortHash(s.target)}/bak-0`;
      s.backup = backup;
      const file = s.kind.file;
      const applyPlan = s.kind.backup === 'file'
        ? `{"written": ["${s.target}"], "unchanged": [], "backup": [], "noop": false}`
        : `{"written": ["${file}"], "unchanged": [], "extra": [], "deleted": [], "backup": [], "noop": false}`;
      s.applyPlan = applyPlan;
      if (!await toolCall('show', `run_id="${s.id}", diff=true`, [
        `{"run_id": "${s.id}", "state": "done", "stop_reason": "rounds",`,
        ` "initial_reward": ${r[0]}, "final_reward": ${best}, "outcomes": ${JSON.stringify(outcomes).replace(/,/g, ', ').replace(/:/g, ': ')},`,
        ` "apply_plan": ${applyPlan},`,
        ` "diff": "--- a/${file}\\n+++ b/${file}\\n@@ …"}`
      ], run, {hidden: 9, wait: 650})) return;
      diffBlock(s.kind.diff);
      await pause(300);
      if (!await agentTurn(`Held-out reward ${fmt(r[0])} → ${fmt(best)} in ${c1} calls (${Math.floor(k.elapsed[1] / 60)}m${String(k.elapsed[1] % 60).padStart(2, '0')}s): ${s.kind.why}. Apply overwrites ${s.path}; it backs up the current version first. Apply it?`, run)) return;
      status.textContent = 'WAITING FOR YOU'; toolLine.textContent = 'diff ready · target untouched until apply';
      waitFor('Yes, apply ↗', 2);
    } else if (phase === 2) {
      phase = 0;
      if (!await userTurn('apply it', run)) return;
      status.textContent = 'APPLYING';
      const written = s.kind.backup === 'file' ? `["${s.target}"], "unchanged": []` : `["${s.kind.file}"], "unchanged": [], "extra": [], "deleted": []`;
      if (!await toolCall('apply', `run_id="${s.id}"`, [
        `{"written": ${written},`,
        ` "backup": ["${s.backup}"], "noop": false,`,
        ` "dest": "${s.target}"}`
      ], run, {wait: 600})) return;
      if (!await agentTurn(`Applied to ${s.path}. The previous version is backed up at ${s.backup}; copy it back if you want to undo.`, run)) return;
      status.textContent = 'COMPLETE'; toolLine.textContent = 'sample run complete · no files were changed by this page';
    }
  });
})();
