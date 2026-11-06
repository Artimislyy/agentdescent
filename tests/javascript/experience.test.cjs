// Execute the shipped script with a minimal DOM and manually advanced timers.
// This is deterministic interaction coverage, not a rendered-browser test.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {test} = require('node:test');
const source = fs.readFileSync(process.env.EXPERIENCE_JS || 'docs/assets/experience.js', 'utf8');

function demo({reducedMotion = false} = {}) {
  class Element {
    constructor(dataset = {}) {
      this.dataset = dataset; this.children = []; this.listeners = {};
      this.textContent = ''; this.value = ''; this.hidden = false; this.disabled = false;
      this.className = ''; this.style = {}; this.attributes = {};
      const classes = new Set();
      this.classList = {
        add: (name) => classes.add(name), remove: (name) => classes.delete(name),
        toggle: (name, on) => (on ?? !classes.has(name)) ? classes.add(name) : classes.delete(name),
        contains: (name) => classes.has(name),
      };
    }
    addEventListener(name, callback) { this.listeners[name] = callback; }
    click() { if (!this.disabled) this.listeners.click?.({currentTarget: this}); }
    append(...children) { this.children.push(...children); }
    replaceChildren() { this.children = []; }
    getAttribute(name) { return this.attributes[name] ?? null; }
    setAttribute(name, value) { this.attributes[name] = value; }
  }
  const elements = Object.fromEntries(['demo-chat-body', 'demo-approve', 'demo-run', 'demo-status',
    'demo-tool-line', 'demo-path', 'demo-live', 'demo-invocation', 'demo-window-title'].map(id => [id, new Element()]));
  elements['demo-path'].value = '~/.claude/skills/pdf-audit';
  const presets = ['skill', 'prompt', 'code'].map(demoKind => new Element({demoKind}));
  const hosts = ['claude', 'codex', 'opencode', 'dsh'].map(demoHost => {
    const button = new Element({demoHost}); button.attributes.role = 'tab'; return button;
  });
  let now = 0;
  const timers = [];
  vm.runInNewContext(source, {
    window: {matchMedia: () => ({matches: reducedMotion})},
    document: {
      querySelector: selector => elements[selector.slice(1)] || null,
      querySelectorAll: selector => selector === '.demo-presets button' ? presets
        : selector === '.demo-hosts button' ? hosts : [],
      createElement: () => new Element(),
      createTextNode: text => ({textContent: text, children: []}),
    },
    setTimeout: (callback, delay) => timers.push({callback, at: now + delay}),
  });
  const flush = () => new Promise(resolve => setImmediate(resolve));
  async function advance(ms) {
    const end = now + ms;
    await flush();
    while (true) {
      timers.sort((a, b) => a.at - b.at);
      if (!timers.length || timers[0].at > end) break;
      const timer = timers.shift(); now = timer.at; timer.callback();
      await flush();
    }
    now = end;
    await flush();
  }
  const text = (node) => (node.textContent || '') + (node.children || []).map(text).join('');
  const blocks = () => elements['demo-chat-body'].children;
  const ofKind = (cls) => blocks().filter(b => b.className.split(' ').includes(cls)).map(text);
  return {
    start: elements['demo-run'], approve: elements['demo-approve'], status: elements['demo-status'],
    path: elements['demo-path'], live: elements['demo-live'], invocation: elements['demo-invocation'], advance,
    select: kind => presets.find(button => button.dataset.demoKind === kind).click(),
    host: name => hosts.find(button => button.dataset.demoHost === name).click(),
    user: () => ofKind('user'), agent: () => ofKind('agent'), tools: () => ofKind('demo-tool'),
    diffs: () => ofKind('demo-diff'), progress: () => ofKind('demo-progress'),
    all: () => blocks().map(text).join('\n'),
  };
}
const LONG = 120000;

test('every run and apply waits for its own approval, and repeated clicks do nothing extra', async () => {
  const d = demo();
  d.approve.click(); assert.equal(d.all(), '');
  d.start.click(); d.start.click(); d.approve.click();
  await d.advance(LONG);
  assert.equal(d.status.textContent, 'WAITING FOR YOU');
  assert.equal(d.approve.hidden, false);
  assert.match(d.approve.textContent, /start the run/);
  assert.equal(d.user().length, 1, 'a double start leaves one conversation');
  assert.deepEqual(d.tools().map(t => t.match(/agentdescent - (\w+) \(MCP\)|Write/)[0]),
    ['agentdescent - doctor (MCP)', 'Write', 'agentdescent - plan (MCP)']);
  assert.match(d.tools()[2], /"agent_calls_upper_bound": 36/);
  assert.ok(!d.all().includes('run_id'), 'nothing starts before the yes');
  d.approve.click(); d.approve.click();
  await d.advance(LONG);
  assert.equal(d.status.textContent, 'WAITING FOR YOU');
  assert.match(d.approve.textContent, /apply/);
  assert.equal(d.tools().filter(t => t.includes('start (MCP)')).length, 1);
  assert.equal(d.progress().length, 1);
  assert.equal(d.diffs().length, 1);
  assert.ok(!d.tools().some(t => t.includes('apply (MCP)')), 'apply waits for its own yes');
  d.approve.click(); d.approve.click(); await d.advance(LONG);
  assert.equal(d.status.textContent, 'COMPLETE');
  assert.equal(d.tools().filter(t => t.includes('apply (MCP)')).length, 1);
  assert.match(d.tools().at(-1), /\.agentdescent\/backups\/pdf-audit-[0-9a-f]{12}\/bak-0/);
  d.approve.click(); await d.advance(LONG);
  assert.equal(d.tools().filter(t => t.includes('apply (MCP)')).length, 1);
});

const hostCases = {
  claude: {ask: '/agentdescent:evolve ~/.claude/skills/pdf-audit eval/cases.jsonl', tool: 'agentdescent - doctor (MCP)', worker: '"ref": "claude_code"'},
  codex: {ask: '/prompts:evolve ~/.codex/skills/pdf-audit eval/cases.jsonl', tool: 'Called agentdescent.doctor({})', worker: '"ref": "codex"'},
  opencode: {ask: '/agentdescent/evolve ~/.config/opencode/skill/pdf-audit eval/cases.jsonl', tool: 'agentdescent_doctor', worker: '"ref": "opencode"'},
  dsh: {ask: 'Use agentdescent to improve the skill at ~/.dsh/skills/pdf-audit', tool: 'mcp-agentdescent · doctor', worker: '"ref": "dsh"'},
};
for (const [name, c] of Object.entries(hostCases)) {
  test(`${name} uses its own invocation, skill folder, tool naming and worker`, async () => {
    const d = demo(); d.host(name);
    assert.equal(d.path.value, c.ask.match(/~\/\S+/)[0]);
    if (name === 'dsh') assert.match(d.invocation.textContent, /no slash command/);
    d.start.click(); await d.advance(LONG);
    assert.ok(d.user()[0].includes(c.ask), d.user()[0]);
    assert.ok(d.tools()[0].includes(c.tool), d.tools()[0]);
    assert.ok(d.tools()[1].includes(c.worker), d.tools()[1]);
    assert.ok(d.tools()[1].includes('"target": "/home/you/'), 'spec paths are absolute');
  });
}

test('a typed path survives switching hosts', () => {
  const d = demo(); d.path.value = '/srv/skills/triage'; d.host('codex');
  assert.equal(d.path.value, '/srv/skills/triage');
});

for (const delay of [0, 400, 2000, 6000, 12000]) {
  test(`restart cancels stale run/apply callbacks after ${delay}ms`, async () => {
    const d = demo(); d.start.click(); await d.advance(LONG); d.approve.click();
    await d.advance(delay);
    d.select('code'); d.start.click(); await d.advance(LONG);
    assert.equal(d.status.textContent, 'WAITING FOR YOU');
    assert.equal(d.user().length, 1);
    assert.match(d.user()[0], /\.\/agent eval\/cases\.jsonl/);
    assert.equal(d.tools().length, 3);
    assert.equal(d.progress().length, 0);
    d.approve.click(); await d.advance(LONG);
    assert.match(d.diffs()[0], /rank_evidence/);
    assert.equal(d.progress().length, 1);
  });
}

for (const initial of ['skill', 'prompt', 'code']) {
  test(`preset edits during a run cannot change the ${initial} plan or diff`, async () => {
    const files = {skill: 'SKILL.md', prompt: 'answer.md', code: 'solver.py'};
    const d = demo(); d.select(initial); d.path.value = './custom-artifact'; d.start.click();
    d.select('prompt'); await d.advance(3000);
    d.select('code'); d.host('codex'); await d.advance(LONG);
    assert.match(d.user()[0], /custom-artifact/);
    d.approve.click(); await d.advance(2000); d.select('skill'); await d.advance(LONG);
    assert.match(d.diffs()[0], new RegExp(`\\+\\+\\+ b/${files[initial]}`));
    assert.match(d.tools()[0], /agentdescent - doctor \(MCP\)/, 'the host stays Claude Code');
  });
}

test('a prompt is evolved with a model, not a coding CLI, and backed up beside the file', async () => {
  const d = demo(); d.select('prompt'); d.start.click(); await d.advance(LONG);
  assert.match(d.tools()[1], /"kind": "text"/);
  assert.match(d.tools()[1], /"ref": "openai_compatible", "model": "deepseek-v4-flash", "api_key_env": "ARK_API_KEY"/);
  assert.ok(!d.tools()[1].includes('"reflect"'));
  assert.match(d.tools()[2], /"self_verify": 2/);
  assert.match(d.tools()[2], /"agent_calls_upper_bound": 40/);
  d.approve.click(); await d.advance(LONG); d.approve.click(); await d.advance(LONG);
  assert.match(d.tools().at(-1), /\/home\/you\/project\/prompts\/answer\.md\.bak-0/);
});

test('status, show and the progress panel follow the recorded skill run', async () => {
  const d = demo(); d.start.click(); await d.advance(LONG); d.approve.click(); await d.advance(LONG);
  const status = d.tools().filter(t => t.includes('status (MCP)'));
  assert.equal(status.length, 2);
  assert.match(status[0], /"reasons": \{"below-threshold":1\}/);
  assert.match(status[1], /"state": "done".*"best_reward": 0\.750/s);
  assert.match(status[1], /"stop_reason": "rounds"/);
  assert.match(d.tools().find(t => t.includes('show (MCP)')), /"initial_reward": 0, "final_reward": 0\.75/);
  assert.match(d.progress()[0], /round 2\/2 · 2:13/);
  assert.match(d.progress()[0], /calls=23 pending=0/);
});

test('reduced motion skips typing and finishes quickly', async () => {
  const d = demo({reducedMotion: true}); d.start.click(); await d.advance(1500);
  assert.equal(d.status.textContent, 'WAITING FOR YOU');
  d.approve.click(); await d.advance(2500);
  assert.match(d.approve.textContent, /apply/);
  assert.ok(d.live.textContent.length > 0, 'the polite live region carries each step');
});
