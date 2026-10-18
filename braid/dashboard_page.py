"""The single page `braid dashboard` serves. Plain HTML, CSS and JavaScript; no build step, no CDN."""

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="braid-token" content="__TOKEN__">
<title>braid dashboard</title>
<style>
:root{--bg:#f6f7f9;--panel:#fff;--ink:#16191d;--muted:#5d6672;--line:#e3e6ea;--soft:#f0f2f5;
--accent:#3b5bdb;--accent-ink:#fff;--ok:#2b8a3e;--warn:#b7791f;--bad:#c92a2a;--purple:#7048e8;--cyan:#0b7285;
--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;--radius:10px}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--panel:#171a20;--ink:#e6e8eb;--muted:#9aa3ad;--line:#2a2f37;
--soft:#1e222a;--accent:#748ffc;--accent-ink:#0f1115;--ok:#51cf66;--warn:#fcc419;--bad:#ff6b6b;--purple:#b197fc;--cyan:#66d9e8}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--panel);border-bottom:1px solid var(--line);
padding:10px 16px;display:flex;flex-wrap:wrap;gap:10px;align-items:center}
header h1{font-size:16px;margin:0 8px 0 0;font-weight:650}
header .repo{color:var(--muted);font-family:var(--mono);font-size:12.5px}
.spacer{flex:1}
nav{display:flex;gap:2px;background:var(--soft);padding:3px;border-radius:8px}
nav button{border:0;background:transparent;color:var(--muted);padding:5px 12px;border-radius:6px;cursor:pointer;font:inherit}
nav button.on{background:var(--panel);color:var(--ink);box-shadow:0 1px 2px rgba(0,0,0,.08)}
main{padding:16px;max-width:1400px;margin:0 auto}
.grid{display:grid;grid-template-columns:minmax(0,1fr) 380px;gap:16px}
@media (max-width:980px){.grid{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:14px 16px;margin-bottom:16px}
.card h2{font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin:0 0 10px;font-weight:600;
display:flex;align-items:center;gap:8px}
.card h2 .count{background:var(--soft);color:var(--ink);border-radius:99px;padding:0 8px;font-size:12px}
button.btn{font:inherit;border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:7px;
padding:5px 11px;cursor:pointer;white-space:nowrap}
button.btn:hover{border-color:var(--muted)}
button.btn.primary{background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}
button.btn.danger{color:var(--bad)}
button.btn.small{padding:2px 8px;font-size:12.5px}
button.btn:disabled{opacity:.5;cursor:default}
input,textarea,select{font:inherit;color:var(--ink);background:var(--panel);border:1px solid var(--line);border-radius:7px;padding:6px 9px;width:100%}
textarea{min-height:74px;resize:vertical}
label.inline{display:inline-flex;gap:6px;align-items:center;color:var(--muted);font-size:13px;white-space:nowrap}
label.inline input{width:auto}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.row > .grow{flex:1;min-width:160px}
.pill{display:inline-flex;align-items:center;gap:5px;border-radius:99px;padding:1px 9px;font-size:12px;font-weight:600;
background:var(--soft);color:var(--muted);white-space:nowrap}
.pill::before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor}
.s-active{color:var(--cyan)}.s-ready{color:var(--warn)}.s-landed{color:var(--ok)}.s-blocked{color:var(--bad)}
.s-exited{color:var(--purple)}.s-paused,.s-done{color:var(--muted)}.s-running{color:var(--ok)}.s-stopped{color:var(--muted)}
.s-pending{color:var(--warn)}.s-approved{color:var(--ok)}.s-rejected,.s-failed{color:var(--bad)}
.agents{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:12px}
.agent{border:1px solid var(--line);border-radius:var(--radius);padding:12px;display:flex;flex-direction:column;gap:7px;background:var(--panel)}
.agent .top{display:flex;gap:8px;align-items:center}
.agent .name{font-weight:650;font-family:var(--mono);font-size:13px}
.agent .task{color:var(--ink)}
.meta{color:var(--muted);font-size:12.5px}
.mono{font-family:var(--mono);font-size:12.5px}
.alert{border-left:3px solid var(--bad);background:var(--soft);padding:6px 9px;border-radius:0 6px 6px 0;font-size:13px}
.alert.warn{border-color:var(--warn)}.alert.ok{border-color:var(--ok)}
.actions{display:flex;gap:6px;flex-wrap:wrap;margin-top:2px}
.list > div{padding:8px 0;border-top:1px solid var(--line)}
.list > div:first-child{border-top:0;padding-top:0}
.feed{max-height:460px;overflow:auto;font-size:13px}
.feed div{padding:3px 0;display:grid;grid-template-columns:62px 70px 1fr;gap:6px}
.feed .t{color:var(--muted);font-family:var(--mono);font-size:12px}
.feed .k{color:var(--cyan);font-family:var(--mono);font-size:12px}
.chat{max-height:300px;overflow:auto;font-size:13px}
.chat div{padding:4px 0;border-top:1px solid var(--line)}
.empty{color:var(--muted);font-style:italic}
.tabs2{display:flex;gap:14px;margin-bottom:10px;border-bottom:1px solid var(--line)}
.tabs2 button{border:0;background:none;color:var(--muted);font:inherit;padding:6px 0;cursor:pointer;border-bottom:2px solid transparent}
.tabs2 button.on{color:var(--ink);border-color:var(--accent)}
.needs{display:flex;flex-direction:column;gap:8px}
.cmd{border:1px solid var(--line);border-radius:var(--radius);margin-bottom:8px;background:var(--panel)}
.cmd summary{cursor:pointer;padding:9px 12px;display:flex;gap:10px;align-items:baseline;list-style:none}
.cmd summary::-webkit-details-marker{display:none}
.cmd summary b{font-family:var(--mono);font-size:13px;min-width:110px}
.cmd .body{padding:4px 12px 12px;display:grid;gap:8px}
.field{display:grid;grid-template-columns:150px 1fr;gap:8px;align-items:center}
@media (max-width:640px){.field{grid-template-columns:1fr}}
.field .lbl{font-family:var(--mono);font-size:12.5px}
.field input[type=checkbox]{justify-self:start;width:auto}
.field .help{grid-column:2;color:var(--muted);font-size:12px;margin-top:-4px}
table{width:100%;border-collapse:collapse}
td,th{text-align:left;padding:6px 8px;border-top:1px solid var(--line);vertical-align:middle}
th{color:var(--muted);font-weight:600;font-size:12.5px}
#drawer{position:fixed;left:0;right:0;bottom:0;z-index:6;background:var(--panel);border-top:1px solid var(--line);
box-shadow:0 -6px 20px rgba(0,0,0,.08);max-height:45vh;display:none;flex-direction:column}
#drawer.open{display:flex}
#drawer .bar{display:flex;gap:8px;align-items:center;padding:8px 16px;border-bottom:1px solid var(--line)}
#drawer pre{margin:0;padding:10px 16px;overflow:auto;font:12.5px/1.45 var(--mono);white-space:pre-wrap}
#modal{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:8;display:none;align-items:center;justify-content:center;padding:20px}
#modal.open{display:flex}
#modal .box{background:var(--panel);border-radius:var(--radius);width:min(1100px,100%);max-height:88vh;display:flex;flex-direction:column}
#modal .bar{display:flex;gap:8px;align-items:center;padding:10px 14px;border-bottom:1px solid var(--line)}
#modal pre{margin:0;padding:12px 14px;overflow:auto;font:12.5px/1.45 var(--mono)}
.d-add{color:var(--ok)}.d-del{color:var(--bad)}.d-hunk{color:var(--cyan)}.d-file{font-weight:700}
.toast{position:fixed;right:16px;top:64px;z-index:9;background:var(--ink);color:var(--bg);padding:8px 12px;border-radius:8px;opacity:0;transition:opacity .2s}
.toast.show{opacity:.95}
body.drawer-open main{padding-bottom:46vh}
</style>
</head>
<body>
<header>
  <h1>braid</h1>
  <span class="repo" id="repo">loading</span>
  <span id="daemon"></span>
  <span class="spacer"></span>
  <nav id="nav">
    <button data-tab="overview" class="on">Overview</button>
    <button data-tab="commands">Commands</button>
    <button data-tab="settings">Settings</button>
    <button data-tab="jobs">History</button>
  </nav>
</header>
<main>
  <section id="tab-overview">
    <div class="row" style="margin-bottom:14px">
      <button class="btn" data-run="check">Check conflicts now</button>
      <button class="btn" data-run="land">Land ready work</button>
      <button class="btn" data-run="ship">Ship (land + push)</button>
      <button class="btn" data-run="push">Push</button>
      <button class="btn" data-run="sync --all">Sync all agents</button>
      <button class="btn" data-run="prune">Tidy landed agents</button>
      <span class="spacer"></span>
      <button class="btn danger" data-run="stop --all" data-confirm="Stop every agent and the watcher?">Stop all</button>
    </div>
    <div class="grid">
      <div>
        <div class="card" id="needs-card"><h2>Needs you <span class="count" id="needs-count">0</span></h2><div class="needs" id="needs"></div></div>
        <div class="card">
          <div class="tabs2" id="newtabs"><button data-new="do" class="on">Plan a goal</button><button data-new="start">Start tasks</button></div>
          <div id="new-do">
            <textarea id="goal" placeholder="What should get built? e.g. a notes app: storage module, CLI, tests"></textarea>
            <div class="row" style="margin-top:8px">
              <input class="grow" id="do-base" placeholder="land on branch (default: the base branch)">
              <input id="do-max" type="number" min="1" placeholder="max agents" style="width:120px">
              <label class="inline"><input type="checkbox" id="do-push"> push when done</label>
              <button class="btn primary" id="do-go">Plan and start</button>
            </div>
          </div>
          <div id="new-start" hidden>
            <textarea id="tasks" placeholder="One task per line; each gets its own agent"></textarea>
            <div class="row" style="margin-top:8px">
              <input class="grow" id="start-base" placeholder="land on branch (default: the base branch)">
              <label class="inline"><input type="checkbox" id="start-nolaunch"> make the worktrees, I'll drive</label>
              <button class="btn primary" id="start-go">Start agents</button>
            </div>
          </div>
        </div>
        <div class="card"><h2>Agents <span class="count" id="agents-count">0</span>
          <span class="spacer"></span><label class="inline" style="text-transform:none;letter-spacing:0"><input type="checkbox" id="show-landed"> show landed</label></h2>
          <div class="agents" id="agents"></div></div>
        <div class="card"><h2>Predicted conflicts <span class="count" id="risks-count">0</span></h2><div class="list" id="risks"></div></div>
        <div class="card"><h2>Plans</h2><div class="list" id="plans"></div></div>
        <div class="card"><h2>Approvals <span id="approvals-mode" class="meta" style="text-transform:none;letter-spacing:0"></span></h2><div class="list" id="approvals"></div></div>
      </div>
      <div>
        <div class="card"><h2>Chat with the agents</h2>
          <div class="chat" id="chat"></div>
          <div class="row" style="margin-top:8px;flex-wrap:nowrap">
            <select id="chat-to" style="width:110px"><option value="">everyone</option></select>
            <input id="chat-text" style="flex:1;min-width:0;width:auto" placeholder="e.g. use the v2 API">
            <button class="btn" id="chat-go">Send</button>
          </div>
        </div>
        <div class="card"><h2>Activity</h2><div class="feed" id="feed"></div></div>
        <div class="card"><h2>Your checkout</h2><pre class="mono" id="git" style="margin:0;white-space:pre-wrap"></pre></div>
      </div>
    </div>
  </section>
  <section id="tab-commands" hidden>
    <div class="card">
      <h2>Run anything</h2>
      <div class="row"><span class="mono">braid</span><input class="grow mono" id="raw" placeholder="log --oneline -5   (any braid or git command)"><button class="btn primary" id="raw-go">Run</button></div>
      <p class="meta" style="margin:8px 0 0">Every command below is the real CLI command; its form is built from the CLI itself.</p>
    </div>
    <div id="commands"></div>
  </section>
  <section id="tab-settings" hidden>
    <div class="card"><h2>Settings</h2>
      <p class="meta" style="margin-top:0">Saving runs <span class="mono">braid settings key value</span>. Tick "every repo" to save it in ~/.config/braid instead.</p>
      <table><thead><tr><th>key</th><th>value</th><th></th></tr></thead><tbody id="settings"></tbody></table>
    </div>
  </section>
  <section id="tab-jobs" hidden><div class="card"><h2>Commands run from this page</h2><div class="list" id="jobs"></div></div></section>
</main>
<div id="drawer"><div class="bar"><b class="mono" id="drawer-title"></b><span id="drawer-state" class="pill"></span><span class="spacer"></span>
  <button class="btn small" id="drawer-stop">Stop</button><button class="btn small" id="drawer-close">Close</button></div><pre id="drawer-out"></pre></div>
<div id="modal"><div class="box"><div class="bar"><b id="modal-title"></b><span class="spacer"></span><button class="btn small" id="modal-close">Close</button></div><pre id="modal-body"></pre></div></div>
<div class="toast" id="toast"></div>
<script>
const TOKEN = document.querySelector('meta[name=braid-token]').content;
const $ = (s) => document.querySelector(s);
let S = null, showingJob = null, schema = null;

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'class') el.className = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of kids.flat()) if (c != null && c !== false) el.append(c.nodeType ? c : String(c));
  return el;
}
const pill = (text, cls) => h('span', {class: 'pill s-' + (cls || text)}, text);
const btn = (label, fn, cls) => h('button', {class: 'btn small ' + (cls || ''), onclick: fn}, label);
const ago = (t) => { const s = Math.max(0, Date.now() / 1000 - t); return s < 60 ? Math.round(s) + 's' : s < 3600 ? Math.round(s / 60) + 'm' : Math.round(s / 3600) + 'h'; };
const clock = (t) => new Date(t * 1000).toTimeString().slice(0, 8);
function toast(msg) { const t = $('#toast'); t.textContent = msg; t.classList.add('show'); setTimeout(() => t.classList.remove('show'), 2200); }

async function api(path, body) {
  const r = await fetch(path, body ? {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Braid-Token': TOKEN}, body: JSON.stringify(body)}
                                   : {headers: {'X-Braid-Token': TOKEN}});
  const data = await r.json().catch(() => ({error: 'HTTP ' + r.status}));
  if (!r.ok) throw new Error(data.error || ('HTTP ' + r.status));
  return data;
}

function split(line) {  // shell-like: quotes group words
  const out = []; let cur = '', q = null, any = false;
  for (const ch of line) {
    if (q) { if (ch === q) q = null; else cur += ch; }
    else if (ch === '"' || ch === "'") { q = ch; any = true; }
    else if (/\s/.test(ch)) { if (cur || any) out.push(cur); cur = ''; any = false; }
    else cur += ch;
  }
  if (cur || any) out.push(cur);
  return out;
}

async function run(argv, opts = {}) {
  if (typeof argv === 'string') argv = split(argv);
  if (opts.confirm && !confirm(opts.confirm)) return;
  try {
    const {job} = await api('/api/run', {argv});
    openJob(job, argv);
  } catch (e) { toast(e.message); }
}

function openJob(id, argv) {
  showingJob = id;
  $('#drawer-title').textContent = 'braid ' + argv.map(a => /\s/.test(a) ? JSON.stringify(a) : a).join(' ');
  $('#drawer-out').textContent = '';
  $('#drawer').classList.add('open'); document.body.classList.add('drawer-open');
  pollJob(id);
}
async function pollJob(id) {
  if (showingJob !== id) return;
  try {
    const j = await api('/api/jobs/' + id);
    const out = $('#drawer-out'); const atEnd = out.scrollTop + out.clientHeight >= out.scrollHeight - 20;
    out.textContent = j.out || (j.rc == null ? 'running...' : '(no output)');
    if (atEnd) out.scrollTop = out.scrollHeight;
    const st = $('#drawer-state');
    st.textContent = j.rc == null ? 'running' : j.rc === 0 ? 'done' : 'exit ' + j.rc;
    st.className = 'pill s-' + (j.rc == null ? 'active' : j.rc === 0 ? 'landed' : 'blocked');
    $('#drawer-stop').hidden = j.rc != null;
    if (j.rc == null) setTimeout(() => pollJob(id), 700); else refresh();
  } catch (e) { $('#drawer-out').textContent = e.message; }
}
$('#drawer-close').onclick = () => { showingJob = null; $('#drawer').classList.remove('open'); document.body.classList.remove('drawer-open'); };
$('#drawer-stop').onclick = () => showingJob && api('/api/jobs/' + showingJob + '/stop', {});

async function showDiff(kind, ref, title) {
  $('#modal-title').textContent = title; const body = $('#modal-body'); body.textContent = 'loading...';
  $('#modal').classList.add('open');
  try {
    const d = await api('/api/diff?kind=' + kind + '&ref=' + encodeURIComponent(ref));
    body.textContent = '';
    for (const line of (d.diff || '(no changes yet)').split('\n')) {
      const cls = line.startsWith('diff --git') ? 'd-file' : line.startsWith('@@') ? 'd-hunk'
        : line.startsWith('+') && !line.startsWith('+++') ? 'd-add' : line.startsWith('-') && !line.startsWith('---') ? 'd-del' : '';
      body.append(h('div', {class: cls}, line || ' '));
    }
    if (d.cut) body.append(h('div', {class: 'meta'}, '... cut; run git diff for the rest'));
  } catch (e) { body.textContent = e.message; }
}
$('#modal-close').onclick = () => $('#modal').classList.remove('open');
$('#modal').onclick = (e) => { if (e.target.id === 'modal') $('#modal').classList.remove('open'); };
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') $('#modal').classList.remove('open'); });

function ask(question, fallback) { const v = prompt(question, fallback || ''); return v == null ? null : v; }

// ---------- overview ----------
function agentCard(a) {
  const acts = [btn('Diff', () => showDiff('agent', a.name, a.name + ' vs ' + a.base))];
  if (a.status === 'ready') {
    acts.push(btn('Approve', () => run(['review', a.name, '--approve'])));
    acts.push(btn('Ask for changes', () => { const m = ask('What should ' + a.name + ' change?'); if (m) run(['review', a.name, '--changes', '-m', m]); }));
    acts.push(btn('Land', () => run(['land', a.name]), 'primary'));
  }
  if (a.status === 'active' && a.interactive) acts.push(btn('Mark ready', () => { const m = ask('One-line summary of the work'); if (m != null) run(['ready', a.name, ...(m ? [m] : [])]); }));
  if (!['landed', 'done'].includes(a.status)) {
    acts.push(btn('Sync', () => run(['sync', a.name])));
    acts.push(btn(a.running ? 'Nudge' : 'Resume', () => {
      if (a.running) { const m = ask('Message for ' + a.name); if (m) run(['chat', '--post', m, '--to', a.name]); return; }
      const m = ask('What should ' + a.name + ' do next? (optional)'); if (m != null) run(['resume', a.name, ...(m ? [m] : [])]);
    }));
    if (a.running) acts.push(btn('Stop', () => run(['stop', a.name])));
    acts.push(btn('Drop', () => run(['drop', a.name, '--delete'], {confirm: 'Abandon ' + a.name + ' and delete its branch and worktree?'}), 'danger'));
  }
  return h('div', {class: 'agent'},
    h('div', {class: 'top'}, h('span', {class: 'name'}, a.name), pill(a.status),
      a.interactive ? h('span', {class: 'meta'}, 'you drive') : pill(a.running ? 'running' : 'stopped'),
      h('span', {class: 'spacer'}), a.ahead != null ? h('span', {class: 'meta'}, a.ahead + ' commit' + (a.ahead === 1 ? '' : 's')) : null),
    h('div', {class: 'task'}, a.task),
    h('div', {class: 'meta mono'}, a.branch + ' → ' + a.base),
    a.intents.length ? h('div', {class: 'meta'}, 'doing: ' + a.intents[a.intents.length - 1]) : null,
    a.owns.length ? h('div', {class: 'meta mono'}, 'owns: ' + a.owns.map(l => l.path + (l.kind === 'hard' ? ' (hard)' : '')).join(', ')) : null,
    a.gate ? h('div', {class: 'alert ' + (a.gate.ok ? 'ok' : 'warn')}, a.gate.ok ? 'can land' : a.gate.why) : null,
    a.needs ? h('div', {class: 'alert'}, 'needs you: ' + a.needs) : null,
    h('div', {class: 'actions'}, acts));
}

function render() {
  $('#repo').textContent = S.name + '  →  ' + S.base;
  $('#daemon').replaceChildren(pill(S.daemon ? 'watcher running' : 'watcher stopped', S.daemon ? 'running' : 'stopped'), ' ',
    btn(S.daemon ? 'Stop watcher' : 'Start watcher', () => run(['daemon', S.daemon ? 'stop' : 'start'])));

  const pending = S.approvals.filter(a => a.status === 'pending');
  const stuck = S.agents.filter(a => a.needs);
  const needs = [];
  for (const a of pending) needs.push(h('div', {class: 'alert warn'}, h('b', {}, 'Approve #' + a.id + ': '), a.title, ' ',
    h('span', {class: 'actions', style: 'display:inline-flex;margin-left:6px'},
      btn('Review diff', () => showDiff('approval', String(a.id), '#' + a.id + ' ' + a.title)),
      btn('Land it', () => run(['approve', String(a.id)]), 'primary'),
      btn('Send back', () => { const m = ask('Why? (goes to the agent)'); if (m != null) run(['reject', String(a.id), ...(m ? ['-m', m] : [])]); }))));
  for (const d of S.decisions) needs.push(h('div', {class: 'alert warn'}, h('b', {}, 'Decision #' + d.id + ': '),
    d.agent + ' vs ' + [].concat(d.parties || []).join(', ') + ' in ' + [].concat(d.files || []).join(', ') + '. ' + d.detail, ' ',
    h('span', {class: 'actions', style: 'display:inline-flex;margin-left:6px'},
      btn('Accept', () => run(['vote', String(d.id), 'accept'])),
      btn('Object', () => { const m = ask('Why object?'); if (m != null) run(['vote', String(d.id), 'object', ...(m ? [m] : [])]); }, 'danger'))));
  for (const a of stuck) needs.push(h('div', {class: 'alert'}, h('b', {}, a.name + ': '), a.needs, ' ',
    h('span', {class: 'actions', style: 'display:inline-flex;margin-left:6px'},
      btn('Resume', () => { const m = ask('What should ' + a.name + ' do? (optional)'); if (m != null) run(['resume', a.name, ...(m ? [m] : [])]); }))));
  $('#needs').replaceChildren(...(needs.length ? needs : [h('div', {class: 'empty'}, 'Nothing is waiting on you.')]));
  $('#needs-count').textContent = needs.length;

  const showLanded = $('#show-landed').checked;
  const agents = S.agents.filter(a => showLanded || !['landed', 'done'].includes(a.status));
  $('#agents').replaceChildren(...(agents.length ? agents.map(agentCard) : [h('div', {class: 'empty'}, S.agents.length ? 'All agents have landed.' : 'No agents yet. Plan a goal or start tasks above.')]));
  $('#agents-count').textContent = agents.length;

  $('#risks').replaceChildren(...(S.risks.length ? S.risks.map(r => h('div', {},
    pill(r.severity, {conflict: 'blocked', semantic: 'exited'}[r.severity] || 'ready'), ' ',
    h('b', {class: 'mono'}, r.a + ' ↔ ' + r.b), ' ', h('span', {class: 'meta mono'}, [].concat(r.files || []).join(', ')))) : [h('div', {class: 'empty'}, 'No conflicts predicted.')]));
  $('#risks-count').textContent = S.risks.length;

  $('#plans').replaceChildren(...(S.plans.length ? S.plans.slice().reverse().map(p => {
    const done = p.tasks.filter(t => t.status === 'landed').length;
    return h('div', {},
      h('div', {class: 'row'}, h('b', {}, '#' + p.id + ' ' + p.goal), pill(p.status, {running: 'active', done: 'landed', cancelled: 'paused', proposed: 'ready'}[p.status]),
        h('span', {class: 'meta'}, done + '/' + p.tasks.length + ' landed on ' + p.base), h('span', {class: 'spacer'}),
        p.status === 'proposed' ? btn('Start', () => run(['plans', 'start', String(p.id)])) : null,
        ['running', 'proposed'].includes(p.status) ? btn('Cancel', () => run(['plans', 'cancel', String(p.id)], {confirm: 'Cancel plan #' + p.id + '?'}), 'danger') : null),
      h('div', {class: 'meta'}, p.tasks.map(t => t.title + ' (' + t.status + ')').join(' · ')));
  }) : [h('div', {class: 'empty'}, 'No plans yet.')]));

  $('#approvals-mode').textContent = S.approvals_on ? '(on: ' + (S.settings['approve.mode'] || 'each') + ')' : '(off)';
  $('#approvals').replaceChildren(...(S.approvals.length ? S.approvals.slice().reverse().map(a => h('div', {},
    h('div', {class: 'row'}, h('b', {}, '#' + a.id), pill(a.status), h('span', {}, a.title), h('span', {class: 'spacer'}),
      h('span', {class: 'meta'}, '+' + a.added + ' / -' + a.removed + (a.tests ? ', tests ok' : ', tests failed') + (a.risk ? ', risk ' + a.risk : '')),
      btn('Diff', () => showDiff('approval', String(a.id), '#' + a.id + ' ' + a.title)),
      btn('Details', () => run(['approvals', 'show', String(a.id)]))),
    a.summary ? h('div', {class: 'meta'}, a.summary) : null)) : [h('div', {class: 'empty'}, S.approvals_on ? 'Nothing asked yet.' : 'Approvals are off. Turn on approve.required in Settings to say yes before anything lands.')]));

  const chat = $('#chat'); const atEnd = chat.scrollTop + chat.clientHeight >= chat.scrollHeight - 20;
  chat.replaceChildren(...(S.notes.length ? S.notes.map(n => h('div', {}, h('span', {class: 'meta mono'}, clock(n.at) + ' '),
    h('b', {}, n.agent + (n.to_agent ? ' → ' + n.to_agent : '')), h('span', {class: 'meta'}, ' [' + n.topic + '] '), n.text)) : [h('div', {class: 'empty'}, 'No notes yet.')]));
  if (atEnd) chat.scrollTop = chat.scrollHeight;
  const to = $('#chat-to'), keep = to.value;
  to.replaceChildren(h('option', {value: ''}, 'everyone'), ...S.agents.filter(a => !['landed', 'done'].includes(a.status)).map(a => h('option', {value: a.name}, a.name)));
  to.value = keep;

  $('#feed').replaceChildren(...(S.events.length ? S.events.slice().reverse().map(e => h('div', {},
    h('span', {class: 't'}, clock(e.at)), h('span', {class: 'k'}, e.kind), h('span', {}, e.agent ? h('b', {}, e.agent + ' ') : null, e.text))) : [h('div', {class: 'empty'}, 'Nothing has happened yet.')]));
  $('#git').textContent = S.git;
  renderSettings();
}

let settingsEditing = false;
function renderSettings() {
  if (settingsEditing) return;  // don't wipe what someone is typing
  const rows = Object.entries(S.settings).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => {
    const input = h('input', {class: 'mono', value: v == null ? '' : v, onfocus: () => settingsEditing = true, onblur: () => setTimeout(() => settingsEditing = false, 300)});
    const glob = h('input', {type: 'checkbox'});
    return h('tr', {}, h('td', {class: 'mono'}, k), h('td', {}, input),
      h('td', {}, h('div', {class: 'row', style: 'flex-wrap:nowrap'}, h('label', {class: 'inline'}, glob, 'every repo'),
        btn('Save', () => { settingsEditing = false; run(['settings', ...(glob.checked ? ['--global'] : []), k, input.value]); }))));
  });
  const nk = h('input', {class: 'mono', placeholder: 'new key'}), nv = h('input', {class: 'mono', placeholder: 'value'});
  rows.push(h('tr', {}, h('td', {}, nk), h('td', {}, nv), h('td', {}, btn('Add', () => nk.value && run(['settings', nk.value, nv.value])))));
  $('#settings').replaceChildren(...rows);
}

// ---------- all commands, built from the CLI's own parser ----------
function renderCommands() {
  $('#commands').replaceChildren(...schema.map(c => {
    const inputs = [];
    const fields = c.args.map(a => {
      let el;
      if (a.kind === 'flag') el = h('input', {type: 'checkbox', style: 'width:auto'});
      else if (a.choices) el = h('select', {}, a.required ? null : h('option', {value: ''}, '(none)'), ...a.choices.map(x => h('option', {value: x}, x)));
      else if (a.kind === 'list') el = h('textarea', {placeholder: 'one per line', style: 'min-height:54px'});
      else el = h('input', {type: a.int ? 'number' : 'text'});
      inputs.push([a, el]);
      return h('div', {class: 'field'}, h('span', {class: 'lbl'}, (a.flag || a.dest) + (a.required ? ' *' : '')), el,
        a.help ? h('span', {class: 'help'}, a.help) : null);
    });
    const go = () => {
      const argv = [c.name];
      for (const [a, el] of inputs) {
        if (a.kind === 'flag') { if (el.checked) argv.push(a.flag); continue; }
        const vals = a.kind === 'list' ? el.value.split('\n').map(s => s.trim()).filter(Boolean) : (el.value.trim() ? [el.value.trim()] : []);
        if (!vals.length) { if (a.required) { toast(a.dest + ' is required'); return null; } continue; }
        if (a.flag) for (const v of vals) argv.push(a.flag, v); else argv.push(...vals);
      }
      if (c.name === 'do' && !argv.includes('--yes')) argv.push('--yes');  // nobody to answer the prompt
      run(argv);
    };
    return h('details', {class: 'cmd'}, h('summary', {}, h('b', {}, c.name), h('span', {class: 'meta'}, c.help || '')),
      h('div', {class: 'body'}, ...fields, h('div', {}, h('button', {class: 'btn primary', onclick: go}, 'Run braid ' + c.name))));
  }));
}

async function renderJobs() {
  const jobs = await api('/api/jobs');
  $('#jobs').replaceChildren(...(jobs.length ? jobs.slice().reverse().map(j => h('div', {class: 'row'},
    h('span', {class: 'meta mono'}, clock(j.started)), h('span', {class: 'mono grow'}, 'braid ' + j.argv.join(' ')),
    pill(j.rc == null ? 'running' : j.rc === 0 ? 'done' : 'exit ' + j.rc, j.rc == null ? 'active' : j.rc === 0 ? 'landed' : 'blocked'),
    btn('Output', () => openJob(j.id, j.argv)))) : [h('div', {class: 'empty'}, 'Nothing run from here yet.')]));
}

// ---------- wiring ----------
for (const b of document.querySelectorAll('[data-run]')) b.onclick = () => run(b.dataset.run, {confirm: b.dataset.confirm});
for (const b of document.querySelectorAll('#nav button')) b.onclick = () => {
  for (const x of document.querySelectorAll('#nav button')) x.classList.toggle('on', x === b);
  for (const t of ['overview', 'commands', 'settings', 'jobs']) $('#tab-' + t).hidden = t !== b.dataset.tab;
  if (b.dataset.tab === 'jobs') renderJobs();
};
for (const b of document.querySelectorAll('#newtabs button')) b.onclick = () => {
  for (const x of document.querySelectorAll('#newtabs button')) x.classList.toggle('on', x === b);
  $('#new-do').hidden = b.dataset.new !== 'do'; $('#new-start').hidden = b.dataset.new !== 'start';
};
$('#do-go').onclick = () => {
  const goal = $('#goal').value.trim(); if (!goal) return toast('Say what to build');
  const argv = ['do', '--yes'];
  if ($('#do-base').value.trim()) argv.push('--base', $('#do-base').value.trim());
  if ($('#do-max').value) argv.push('--max-agents', $('#do-max').value);
  if ($('#do-push').checked) argv.push('--push');
  run([...argv, goal]); $('#goal').value = '';
};
$('#start-go').onclick = () => {
  const tasks = $('#tasks').value.split('\n').map(s => s.trim()).filter(Boolean); if (!tasks.length) return toast('Add at least one task');
  const argv = ['start'];
  if ($('#start-base').value.trim()) argv.push('--base', $('#start-base').value.trim());
  if ($('#start-nolaunch').checked) argv.push('--no-launch');
  run([...argv, ...tasks]); $('#tasks').value = '';
};
$('#chat-go').onclick = () => {
  const text = $('#chat-text').value.trim(); if (!text) return;
  run(['chat', '--post', text, ...($('#chat-to').value ? ['--to', $('#chat-to').value] : [])]); $('#chat-text').value = '';
};
$('#chat-text').onkeydown = (e) => { if (e.key === 'Enter') $('#chat-go').click(); };
$('#raw-go').onclick = () => { const v = $('#raw').value.trim(); if (v) run(v.replace(/^braid\s+/, '')); };
$('#raw').onkeydown = (e) => { if (e.key === 'Enter') $('#raw-go').click(); };
$('#show-landed').onchange = () => S && render();

async function refresh() {
  try { S = await api('/api/state'); render(); }
  catch (e) { $('#repo').textContent = 'cannot read state: ' + e.message; }
}
(async () => {
  await refresh();
  try { schema = await api('/api/commands'); renderCommands(); } catch (e) { $('#commands').textContent = e.message; }
  setInterval(refresh, 2000);
})();
</script>
</body>
</html>
"""
