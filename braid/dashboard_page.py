"""The single page `braid dashboard` serves. Plain HTML, CSS and JavaScript; no build step, no CDN.

One screen answers three questions, in this order: does anything need me, what are my agents doing,
and what should they do next. Everything else (every CLI command, settings, the activity log) lives
behind the menu so the home screen stays calm.
"""

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="braid-token" content="__TOKEN__">
<meta name="color-scheme" content="dark">
<title>braid</title>
<style>
:root{--bg:#060a10;--card:#0c141d;--card2:#101b26;--line:rgba(120,200,240,.12);--line2:rgba(120,200,240,.24);
--ink:#e4f4fc;--muted:#8aa3b5;--dim:#56707f;--cyan:#3ddcff;--cyan-soft:rgba(61,220,255,.1);
--ok:#4ee6a0;--warn:#ffc35a;--bad:#ff6b77;--r:14px;--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
*{box-sizing:border-box}
[hidden]{display:none!important}
html{background:var(--bg)}
body{margin:0;color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;min-height:100vh;
background:radial-gradient(900px 420px at 50% -120px,rgba(61,220,255,.13),transparent 70%),var(--bg)}
button,input,textarea,select{font:inherit;color:inherit}
select option{background:#0c141d}
a{color:var(--cyan)}
.muted{color:var(--muted)}.dim{color:var(--dim)}.mono{font-family:var(--mono);font-size:13px}
.spacer{flex:1}

/* ---------- top bar ---------- */
header{display:flex;align-items:center;gap:12px;max-width:820px;margin:0 auto;padding:18px 20px 0}
.reactor{width:34px;height:34px;flex:none;color:var(--cyan);filter:drop-shadow(0 0 6px currentColor);transition:color .5s}
.reactor .spin{transform-origin:50% 50%;animation:spin 16s linear infinite}
.reactor .core{animation:pulse 2.8s ease-in-out infinite}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes pulse{0%,100%{opacity:.65}50%{opacity:1}}
.brand{line-height:1.2}
.brand b{font-family:var(--mono);letter-spacing:.3em;color:var(--cyan);font-size:14px}
.brand div{font-size:13px;color:var(--muted)}
.icon-btn{width:38px;height:38px;border-radius:10px;border:1px solid var(--line);background:var(--card);cursor:pointer;
display:inline-flex;align-items:center;justify-content:center;color:var(--muted)}
.icon-btn:hover{color:var(--ink);border-color:var(--line2)}
body:not(.sub) .back{display:none}
.menu{position:relative}
.menu-list{position:absolute;right:0;top:46px;z-index:30;min-width:240px;background:var(--card2);border:1px solid var(--line2);border-radius:12px;
padding:6px;box-shadow:0 18px 50px rgba(0,0,0,.55)}
.menu-list button{display:flex;width:100%;gap:10px;align-items:center;text-align:left;background:none;border:0;border-radius:8px;padding:9px 12px;cursor:pointer}
.menu-list button:hover{background:var(--cyan-soft)}
.menu-list button small{color:var(--dim);margin-left:auto;font-size:12px}
.menu-list hr{border:0;border-top:1px solid var(--line);margin:6px 4px}
.menu-list .danger{color:var(--bad)}

main{max-width:820px;margin:0 auto;padding:10px 20px 120px}
h2{font-size:13px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:34px 0 12px}

/* ---------- headline ---------- */
.headline{margin:26px 0 4px;font-size:26px;font-weight:650;letter-spacing:-.01em}
.subline{color:var(--muted);margin:0}
.plan{margin-top:16px;background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:14px 16px}
.plan .row{display:flex;gap:10px;align-items:baseline}
.bar{height:5px;background:rgba(255,255,255,.06);border-radius:99px;overflow:hidden;margin-top:10px}
.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--cyan),var(--ok));box-shadow:0 0 10px var(--cyan)}

/* ---------- buttons ---------- */
.btn{border:1px solid var(--line2);background:transparent;border-radius:10px;padding:8px 16px;cursor:pointer;white-space:nowrap;transition:.15s}
.btn:hover{border-color:var(--cyan);color:var(--cyan)}
.btn.go{background:var(--cyan);border-color:var(--cyan);color:#03121a;font-weight:650;box-shadow:0 0 18px rgba(61,220,255,.3)}
.btn.go:hover{color:#03121a;filter:brightness(1.08)}
.btn.bad{color:var(--bad);border-color:rgba(255,107,119,.4)}
.link{background:none;border:0;padding:8px 6px;color:var(--muted);cursor:pointer;text-decoration:underline;text-underline-offset:3px}
.link:hover{color:var(--ink)}

/* ---------- needs you ---------- */
.need{display:flex;gap:14px;background:linear-gradient(180deg,rgba(255,195,90,.07),rgba(255,195,90,.02));border:1px solid rgba(255,195,90,.3);
border-radius:var(--r);padding:16px 18px;margin-bottom:10px}
.need.red{background:linear-gradient(180deg,rgba(255,107,119,.08),rgba(255,107,119,.02));border-color:rgba(255,107,119,.32)}
.need .dot{width:10px;height:10px;border-radius:50%;background:var(--warn);box-shadow:0 0 10px var(--warn);margin-top:8px;flex:none}
.need.red .dot{background:var(--bad);box-shadow:0 0 10px var(--bad)}
.need .q{font-weight:600;font-size:16px}
.need .acts{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px;align-items:center}

/* ---------- agents ---------- */
.list{background:var(--card);border:1px solid var(--line);border-radius:var(--r);overflow:hidden}
.row-agent{display:flex;align-items:center;gap:14px;padding:14px 18px;border-top:1px solid var(--line);cursor:pointer;background:none;border-left:0;border-right:0;border-bottom:0;width:100%;text-align:left}
.row-agent:first-child{border-top:0}
.row-agent:hover{background:rgba(61,220,255,.04)}
.row-agent .who{flex:1;min-width:0}
.row-agent .task{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row-agent .sub{font-size:13px;color:var(--dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pill{display:inline-flex;align-items:center;gap:7px;font-size:13px;white-space:nowrap;color:var(--muted)}
.pill i{width:8px;height:8px;border-radius:50%;background:var(--dim)}
.s-working i{background:var(--cyan);box-shadow:0 0 8px var(--cyan);animation:pulse 1.6s infinite}
.s-ready i{background:var(--ok)}
.s-you i{background:var(--warn);box-shadow:0 0 8px var(--warn)}
.s-stuck i{background:var(--bad);box-shadow:0 0 8px var(--bad)}
.s-landed i{background:var(--ok);opacity:.5}
.s-you{color:var(--warn)}.s-stuck{color:var(--bad)}.s-ready{color:var(--ok)}
.chev{color:var(--dim)}
.toggle-landed{margin-top:8px}

/* ---------- new task ---------- */
.ask{background:var(--card);border:1px solid var(--line2);border-radius:var(--r);padding:14px 14px 12px 18px;transition:.2s}
.ask:focus-within{border-color:var(--cyan);box-shadow:0 0 0 4px rgba(61,220,255,.08)}
.ask textarea{width:100%;background:none;border:0;outline:0;resize:none;font-size:16px;min-height:52px;max-height:220px}
.ask textarea::placeholder{color:var(--dim)}
.ask .foot{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.options{display:grid;gap:12px;margin-top:12px;padding-top:12px;border-top:1px solid var(--line)}
.options label{display:flex;gap:10px;align-items:center;font-size:14px}
.in{background:#081018;border:1px solid var(--line);border-radius:9px;padding:8px 11px;outline:0;width:100%}
.in:focus{border-color:var(--cyan)}
.seg{display:inline-flex;border:1px solid var(--line2);border-radius:10px;overflow:hidden}
.seg button{background:none;border:0;padding:7px 14px;cursor:pointer;color:var(--muted)}
.seg button.on{background:var(--cyan-soft);color:var(--cyan)}

/* ---------- welcome ---------- */
.welcome{text-align:center;padding:40px 0 8px}
.welcome .headline{font-size:30px}
.steps{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:30px 0 8px;text-align:left}
.step{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:14px 16px}
.step b{display:block;color:var(--cyan);font-family:var(--mono);font-size:12px;letter-spacing:.14em;margin-bottom:4px}
.examples{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.examples button{background:var(--card);border:1px solid var(--line);border-radius:99px;padding:6px 14px;cursor:pointer;color:var(--muted);font-size:13.5px}
.examples button:hover{color:var(--ink);border-color:var(--line2)}

/* ---------- drawer (one agent) ---------- */
.scrim{position:fixed;inset:0;background:rgba(2,6,10,.6);backdrop-filter:blur(2px);z-index:40;opacity:0;pointer-events:none;transition:.2s}
.scrim.open{opacity:1;pointer-events:auto}
.drawer{position:fixed;top:0;right:0;bottom:0;width:min(480px,100%);background:var(--card2);border-left:1px solid var(--line2);z-index:41;
transform:translateX(100%);transition:transform .25s ease;display:flex;flex-direction:column}
.drawer.open{transform:none}
.drawer .top{display:flex;align-items:center;gap:12px;padding:18px 20px;border-bottom:1px solid var(--line)}
.drawer .body{padding:20px;overflow:auto;flex:1}
.drawer h3{margin:0;font-size:18px}
.facts{display:grid;grid-template-columns:110px 1fr;gap:8px 14px;font-size:14px;margin:18px 0}
.facts dt{color:var(--dim)}.facts dd{margin:0;overflow-wrap:anywhere}
.callout{border-radius:12px;padding:12px 14px;background:var(--cyan-soft);border:1px solid var(--line2);margin-top:14px}
.callout.red{background:rgba(255,107,119,.08);border-color:rgba(255,107,119,.3)}
.callout.amber{background:rgba(255,195,90,.08);border-color:rgba(255,195,90,.3)}
.drawer .acts{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px}
.drawer .quiet{display:flex;gap:4px;flex-wrap:wrap;margin-top:22px;padding-top:14px;border-top:1px solid var(--line)}

/* ---------- modal (questions, diffs, output) ---------- */
.modal{position:fixed;inset:0;z-index:50;display:none;align-items:center;justify-content:center;padding:16px;background:rgba(2,6,10,.7);backdrop-filter:blur(3px)}
.modal.open{display:flex}
.modal .box{background:var(--card2);border:1px solid var(--line2);border-radius:16px;padding:20px;width:min(520px,100%);max-height:88vh;overflow:auto;box-shadow:0 30px 80px rgba(0,0,0,.6)}
.modal.wide .box{width:min(1000px,100%)}
.modal h3{margin:0 0 6px;font-size:17px}
.modal textarea{width:100%;min-height:90px;margin-top:12px}
.modal .acts{display:flex;gap:8px;justify-content:flex-end;margin-top:16px}
pre.out{margin:12px 0 0;font:12.5px/1.5 var(--mono);white-space:pre-wrap;word-break:break-word;background:#050a0f;border:1px solid var(--line);border-radius:10px;padding:12px;max-height:65vh;overflow:auto}
.d-add{color:var(--ok)}.d-del{color:var(--bad)}.d-hunk{color:var(--cyan)}.d-file{color:var(--ink);font-weight:700;margin-top:10px}

/* ---------- running indicator ---------- */
.runner{position:fixed;left:50%;bottom:20px;transform:translateX(-50%);z-index:45;display:flex;align-items:center;gap:12px;
background:var(--card2);border:1px solid var(--line2);border-radius:99px;padding:8px 10px 8px 18px;box-shadow:0 12px 40px rgba(0,0,0,.5);max-width:calc(100% - 32px)}
.runner span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.spinner{width:14px;height:14px;border-radius:50%;border:2px solid var(--cyan-soft);border-top-color:var(--cyan);animation:spin .8s linear infinite;flex:none}
.runner.ok .spinner{border:0;background:var(--ok);animation:none;width:10px;height:10px}
.runner.bad{border-color:rgba(255,107,119,.5)}
.runner.bad .spinner{border:0;background:var(--bad);animation:none;width:10px;height:10px}

/* ---------- other pages ---------- */
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:16px 18px}
.feed div{display:grid;grid-template-columns:70px 1fr;gap:12px;padding:7px 0;border-top:1px solid var(--line);font-size:14px}
.feed div:first-child{border-top:0}
.msg{padding:9px 0;border-top:1px solid var(--line);font-size:14px}
.msg:first-child{border-top:0}
.msg .from{font-size:12.5px;color:var(--dim)}
.send{display:flex;gap:8px;margin-top:12px}
details.cmd{background:var(--card);border:1px solid var(--line);border-radius:12px;margin-bottom:8px}
details.cmd summary{cursor:pointer;padding:12px 16px;display:flex;gap:14px;align-items:baseline;list-style:none}
details.cmd summary::-webkit-details-marker{display:none}
details.cmd summary b{font-family:var(--mono);color:var(--cyan);min-width:110px}
details.cmd .fields{padding:4px 16px 16px;display:grid;gap:12px}
.field span{display:block;font-size:13px;color:var(--muted);margin-bottom:4px}
.field small{display:block;color:var(--dim);font-size:12.5px;margin-top:3px}
.search{margin-bottom:14px}
table{width:100%;border-collapse:collapse;font-size:14px}
td{padding:8px 6px;border-top:1px solid var(--line);vertical-align:middle}
tr:first-child td{border-top:0}
.empty{color:var(--dim);padding:14px 0;text-align:center}

@media (max-width:640px){
  .headline{font-size:22px}.welcome .headline{font-size:24px}
  .steps{grid-template-columns:1fr}
  .row-agent .sub{display:none}
  .facts{grid-template-columns:90px 1fr}
  td:first-child{max-width:130px;overflow-wrap:anywhere}
}
</style>
</head>
<body>
<header>
  <button class="icon-btn back" id="back" title="Back to home" aria-label="Back">&#8592;</button>
  <svg class="reactor" viewBox="0 0 48 48" aria-hidden="true">
    <circle cx="24" cy="24" r="21" fill="none" stroke="currentColor" stroke-opacity=".35" stroke-width="1.5"/>
    <g class="spin"><circle cx="24" cy="24" r="16" fill="none" stroke="currentColor" stroke-width="2" stroke-dasharray="6 5"/></g>
    <circle class="core" cx="24" cy="24" r="7" fill="currentColor" fill-opacity=".85"/>
  </svg>
  <div class="brand"><b>BRAID</b><div id="where">connecting</div></div>
  <span class="spacer"></span>
  <div class="menu">
    <button class="icon-btn" id="menu-btn" aria-label="Menu" title="More">&#9776;</button>
    <div class="menu-list" id="menu" hidden>
      <button data-go="activity">Activity and messages</button>
      <button data-go="commands">Every command <small>CLI</small></button>
      <button data-go="settings">Settings</button>
      <button data-go="history">What I ran here</button>
      <hr>
      <button data-act="land">Land all ready work</button>
      <button data-act="push">Push to the remote</button>
      <button data-act="watcher" id="watcher-item">Watcher</button>
      <hr>
      <button data-act="stopall" class="danger">Stop all agents</button>
    </div>
  </div>
</header>

<main>
  <!-- HOME -->
  <section id="page-home">
    <div id="welcome" class="welcome" hidden>
      <div class="headline">What should your agents build?</div>
      <p class="subline">Describe it in plain words. braid splits it into tasks, runs an agent on each, and lands the work.</p>
      <div class="steps">
        <div class="step"><b>1 · DESCRIBE</b>Say what you want below.</div>
        <div class="step"><b>2 · WATCH</b>Agents work side by side on their own copies.</div>
        <div class="step"><b>3 · APPROVE</b>Tested work lands on your branch.</div>
      </div>
    </div>

    <div id="summary" hidden>
      <div class="headline" id="headline"></div>
      <p class="subline" id="subline"></p>
      <div id="plan"></div>
    </div>

    <div id="needs-wrap" hidden><h2>Needs you</h2><div id="needs"></div></div>

    <div id="agents-wrap" hidden>
      <h2>Agents</h2>
      <div class="list" id="agents"></div>
      <button class="link toggle-landed" id="toggle-landed"></button>
    </div>

    <h2 id="ask-title">New work</h2>
    <div class="ask">
      <textarea id="ask" rows="2" placeholder="e.g. Add a dark mode toggle to the settings page"></textarea>
      <div class="foot">
        <button class="link" id="opts-toggle">Options</button>
        <span class="spacer"></span>
        <button class="btn go" id="ask-go">Start</button>
      </div>
      <div class="options" id="opts" hidden>
        <div><div class="muted" style="font-size:13px;margin-bottom:6px">How to split it</div>
          <div class="seg"><button data-mode="do" class="on">Let braid plan it</button><button data-mode="start">One agent per line</button></div></div>
        <label>Land on branch <input class="in" id="opt-base" placeholder="your current branch" style="max-width:220px"></label>
        <label id="opt-max-row">At most <input class="in" id="opt-max" type="number" min="1" placeholder="4" style="max-width:80px"> agents at once</label>
        <label id="opt-push-row"><input type="checkbox" id="opt-push"> Push when everything has landed</label>
      </div>
    </div>
    <div class="examples" id="examples"></div>
  </section>

  <!-- ACTIVITY -->
  <section id="page-activity" hidden>
    <h2>Messages</h2>
    <div class="card"><div id="chat"></div>
      <div class="send"><select class="in" id="chat-to" style="max-width:170px"></select>
        <input class="in" id="chat-text" placeholder="Tell the agents something"><button class="btn go" id="chat-go">Send</button></div></div>
    <h2>Possible conflicts</h2><div class="card" id="risks"></div>
    <h2>Activity</h2><div class="card feed" id="feed"></div>
  </section>

  <!-- COMMANDS -->
  <section id="page-commands" hidden>
    <h2>Every command</h2>
    <p class="muted" style="margin-top:-4px">Each form runs the real <span class="mono">braid</span> command, so anything the CLI can do works here.</p>
    <div class="ask" style="margin-bottom:16px;display:flex;gap:10px;align-items:center;padding:8px 8px 8px 16px">
      <span class="mono" style="color:var(--cyan)">braid</span>
      <input id="raw" class="mono" style="flex:1;min-width:0;background:none;border:0;outline:0;font-size:14px" placeholder="type any braid or git command">
      <button class="btn go" id="raw-go">Run</button></div>
    <input class="in search" id="cmd-search" placeholder="Find a command">
    <div id="commands"></div>
  </section>

  <!-- SETTINGS -->
  <section id="page-settings" hidden>
    <h2>Settings</h2>
    <div class="card"><table><tbody id="settings"></tbody></table></div>
  </section>

  <!-- HISTORY -->
  <section id="page-history" hidden>
    <h2>What I ran here</h2><div class="card" id="jobs"></div>
  </section>
</main>

<div class="scrim" id="scrim"></div>
<aside class="drawer" id="drawer"><div class="top"><h3 id="d-name"></h3><span class="spacer"></span>
  <button class="icon-btn" id="d-close" aria-label="Close">&#10005;</button></div><div class="body" id="d-body"></div></aside>
<div class="modal" id="modal"><div class="box" id="modal-box"></div></div>
<div class="runner" id="runner" hidden><div class="spinner"></div><span id="runner-text"></span>
  <button class="btn" id="runner-see" style="padding:5px 12px">Details</button><button class="link" id="runner-x" style="padding:4px 8px">&#10005;</button></div>

<script>
const TOKEN = document.querySelector('meta[name=braid-token]').content;
const $ = (s) => document.querySelector(s);
let S = null, schema = null, mode = 'do', page = 'home', openAgent = null, showLanded = false;

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
const btn = (label, fn, cls) => h('button', {class: cls === 'link' ? 'link' : 'btn ' + (cls || ''), onclick: fn}, label);
const clock = (t) => new Date(t * 1000).toTimeString().slice(0, 5);
const plural = (n, w) => n + ' ' + w + (n === 1 ? '' : 's');
const tidy = (t) => (t || '').replace(/^landing it was blocked: (blocked: )?/, 'Landing failed: ').replace(/^./, c => c.toUpperCase());

async function api(path, body) {
  const r = await fetch(path, body ? {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Braid-Token': TOKEN}, body: JSON.stringify(body)}
                                   : {headers: {'X-Braid-Token': TOKEN}});
  const data = await r.json().catch(() => ({error: 'HTTP ' + r.status}));
  if (!r.ok) throw new Error(data.error || ('HTTP ' + r.status));
  return data;
}
function split(line) {
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

// ---------- modal: questions, confirmations, diffs, command output ----------
function closeModal() { $('#modal').classList.remove('open', 'wide'); }
function modal(kids, wide) { $('#modal-box').replaceChildren(...kids); $('#modal').classList.add('open'); $('#modal').classList.toggle('wide', !!wide); }
function ask({title, text, placeholder, ok, danger, input}) {
  return new Promise((resolve) => {
    const field = input ? h('textarea', {class: 'in', placeholder: placeholder || ''}) : null;
    const done = (v) => { closeModal(); resolve(v); };
    modal([h('h3', {}, title), text ? h('p', {class: 'muted', style: 'margin:0'}, text) : null, field,
      h('div', {class: 'acts'}, btn('Cancel', () => done(null), 'link'), btn(ok || 'OK', () => done(field ? field.value.trim() : true), danger ? 'bad' : 'go'))]);
    if (field) { field.focus(); field.onkeydown = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); done(field.value.trim()); } }; }
  });
}
$('#modal').onclick = (e) => { if (e.target.id === 'modal') closeModal(); };
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closeModal(); closeDrawer(); $('#menu').hidden = true; } });

async function showDiff(kind, ref, title) {
  const pre = h('pre', {class: 'out'}, 'Loading...');
  modal([h('div', {style: 'display:flex;align-items:center;gap:10px'}, h('h3', {style: 'margin:0'}, title), h('span', {class: 'spacer'}), btn('Close', closeModal)), pre], true);
  try {
    const d = await api('/api/diff?kind=' + kind + '&ref=' + encodeURIComponent(ref));
    pre.textContent = '';
    for (const line of (d.diff || 'No changes yet.').split('\n')) {
      const cls = line.startsWith('diff --git') ? 'd-file' : line.startsWith('@@') ? 'd-hunk'
        : line.startsWith('+') && !line.startsWith('+++') ? 'd-add' : line.startsWith('-') && !line.startsWith('---') ? 'd-del' : '';
      pre.append(h('div', {class: cls}, line || ' '));
    }
  } catch (e) { pre.textContent = e.message; }
}

// ---------- running commands: a quiet pill at the bottom, details on demand ----------
let job = null;
async function run(argv, label, opts = {}) {
  if (typeof argv === 'string') argv = split(argv);
  if (opts.confirm && !(await ask({title: opts.confirm, text: opts.detail, ok: opts.ok || 'Yes', danger: true}))) return;
  try {
    const {job: id} = await api('/api/run', {argv});
    job = {id, argv, label: label || 'braid ' + argv.join(' '), out: '', rc: null};
    showRunner(); poll(id);
    if (opts.show) showOutput();
  } catch (e) { job = {argv, label: e.message, rc: 1, out: e.message}; showRunner(); }
}
function showRunner() {
  const r = $('#runner'); r.hidden = false;
  r.className = 'runner' + (job.rc == null ? '' : job.rc === 0 ? ' ok' : ' bad');
  $('#runner-text').textContent = job.rc == null ? job.label + '...' : job.rc === 0 ? job.label + ': done' : job.label + ': it did not work';
  clearTimeout(showRunner.t);
  if (job.rc === 0) showRunner.t = setTimeout(() => { r.hidden = true; }, 4000);
}
async function poll(id) {
  if (!job || job.id !== id) return;
  try {
    const j = await api('/api/jobs/' + id);
    job.out = j.out; job.rc = j.rc; showRunner();
    if ($('#modal').classList.contains('open') && $('#job-out')) { const o = $('#job-out'); o.textContent = j.out || 'Working...'; o.scrollTop = o.scrollHeight; }
    if (j.rc == null) setTimeout(() => poll(id), 700); else refresh();
  } catch (e) { job.rc = 1; job.out = e.message; showRunner(); }
}
function showOutput() {
  if (!job) return;
  modal([h('div', {style: 'display:flex;align-items:center;gap:10px'}, h('h3', {style: 'margin:0'}, job.label), h('span', {class: 'spacer'}),
      job.rc == null && job.id ? btn('Stop it', () => api('/api/jobs/' + job.id + '/stop', {}), 'bad') : null, btn('Close', closeModal)),
    h('div', {class: 'mono dim', style: 'margin-top:4px'}, 'braid ' + job.argv.map(a => /\s/.test(a) ? JSON.stringify(a) : a).join(' ')),
    h('pre', {class: 'out', id: 'job-out'}, job.out || 'Working...')], true);
}
$('#runner-see').onclick = showOutput;
$('#runner-x').onclick = () => { $('#runner').hidden = true; };

const message = async (a) => { const m = await ask({title: 'Message ' + a.name, text: 'It reads this on its next step.', input: true, ok: 'Send'}); if (m) run(['chat', '--post', m, '--to', a.name], 'Messaging ' + a.name); };
const resume = async (a) => { const m = await ask({title: 'Resume ' + a.name, text: 'Tell it what to do next, or leave this empty to let it carry on.', input: true, ok: 'Resume'}); if (m != null) run(['resume', a.name, ...(m ? [m] : [])], 'Resuming ' + a.name); };
const sendBack = async (ap) => { const m = await ask({title: 'Send it back', text: 'What should change? The agent gets your note and keeps working.', input: true, ok: 'Send back'}); if (m != null) run(['reject', String(ap.id), ...(m ? ['-m', m] : [])], 'Sending back ' + ap.agent); };
const askChanges = async (a) => { const m = await ask({title: 'Ask ' + a.name + ' for changes', text: 'What should it change?', input: true, ok: 'Send'}); if (m) run(['review', a.name, '--changes', '-m', m], 'Asking ' + a.name + ' for changes'); };

// ---------- what each agent is up to, in plain words ----------
function view(a) {
  const ap = S.approvals.find(x => x.status === 'pending' && x.agent === a.name);
  if (ap) return {key: 'you', word: 'Waiting for your OK', ap};
  if (a.needs) return {key: 'stuck', word: 'Stuck'};
  if (a.status === 'ready') return a.gate && !a.gate.ok ? {key: 'ready', word: 'Done, in review'} : {key: 'ready', word: 'Done, landing soon'};
  if (a.status === 'active') return a.running ? {key: 'working', word: 'Working'} : a.interactive ? {key: 'idle', word: 'Yours to drive'} : {key: 'idle', word: 'Idle'};
  if (a.status === 'landed' || a.status === 'done') return {key: 'landed', word: 'Landed'};
  if (a.status === 'paused') return {key: 'idle', word: 'Paused'};
  if (a.status === 'exited') return {key: 'stuck', word: 'Stopped'};
  return {key: 'idle', word: a.status};
}
const pill = (v) => h('span', {class: 'pill s-' + v.key}, h('i'), v.word);

// ---------- home ----------
function renderHome() {
  const live = S.agents.filter(a => !['landed', 'done'].includes(a.status));
  const landed = S.agents.filter(a => ['landed', 'done'].includes(a.status));
  const pending = S.approvals.filter(a => a.status === 'pending');
  const stuck = live.filter(a => a.needs);
  const working = live.filter(a => view(a).key === 'working').length;
  const nNeeds = pending.length + S.decisions.length + stuck.length;

  $('#welcome').hidden = S.agents.length > 0;
  $('#summary').hidden = S.agents.length === 0;
  $('#ask-title').hidden = S.agents.length === 0;
  document.querySelector('.reactor').style.color = stuck.length ? 'var(--bad)' : nNeeds ? 'var(--warn)' : 'var(--cyan)';

  if (S.agents.length) {
    $('#headline').textContent = nNeeds ? plural(nNeeds, 'thing') + ' need' + (nNeeds === 1 ? 's' : '') + ' you'
      : live.length ? (working ? plural(working, 'agent') + ' working' : 'Agents are idle') + '. Nothing needs you.'
      : 'All work has landed.';
    const bits = [];
    if (live.length) bits.push(plural(live.length, 'agent') + ' on ' + S.base);
    if (landed.length) bits.push(landed.length + ' landed');
    const clashes = S.risks.filter(r => r.severity === 'conflict').length;
    if (clashes) bits.push(plural(clashes, 'possible conflict') + ', handled automatically');
    $('#subline').replaceChildren(bits.join(' · '));
    if (!S.daemon && live.length) $('#subline').append(h('div', {}, h('span', {style: 'color:var(--warn)'}, 'The watcher is off, so finished work will not land on its own. '),
      btn('Turn it on', ACTS.watcher, 'link')));
    const p = S.plans.filter(p => p.status === 'running').slice(-1)[0];
    $('#plan').replaceChildren(...(p ? [(() => {
      const done = p.tasks.filter(t => t.status === 'landed').length, pct = p.tasks.length ? Math.round(100 * done / p.tasks.length) : 0;
      return h('div', {class: 'plan'}, h('div', {class: 'row'}, h('b', {}, p.goal), h('span', {class: 'spacer'}), h('span', {class: 'muted'}, done + ' of ' + p.tasks.length + ' tasks landed')),
        h('div', {class: 'bar'}, h('i', {style: 'width:' + pct + '%'})));
    })()] : []));
  }

  const needs = [];
  for (const ap of pending) needs.push(h('div', {class: 'need'}, h('span', {class: 'dot'}), h('div', {style: 'flex:1;min-width:0'},
    h('div', {class: 'q'}, 'Land "' + ap.title + '"?'),
    h('div', {class: 'muted'}, ap.agent + ' finished. ' + (ap.tests ? 'Tests pass. ' : 'Tests FAILED. ') + '+' + ap.added + ' / -' + ap.removed + ' lines.'),
    h('div', {class: 'acts'}, btn('Land it', () => run(['approve', String(ap.id)], 'Landing ' + ap.agent), 'go'),
      btn('See changes', () => showDiff('approval', String(ap.id), ap.title)), btn('Send back', () => sendBack(ap), 'link')))));
  for (const d of S.decisions) needs.push(h('div', {class: 'need'}, h('span', {class: 'dot'}), h('div', {style: 'flex:1;min-width:0'},
    h('div', {class: 'q'}, 'Keep the automatic fix for a conflict?'),
    h('div', {class: 'muted'}, d.agent + ' and ' + [].concat(d.parties || []).join(', ') + ' both changed ' + [].concat(d.files || []).join(', ') + '. braid merged them and the tests pass.'),
    h('div', {class: 'acts'}, btn('Keep it', () => run(['vote', String(d.id), 'accept'], 'Accepting the fix'), 'go'),
      btn('Reject', async () => { const m = await ask({title: 'Reject the fix', text: 'Why? This stops the landing.', input: true, ok: 'Reject', danger: true}); if (m != null) run(['vote', String(d.id), 'object', ...(m ? [m] : [])], 'Rejecting the fix'); }, 'link')))));
  for (const a of stuck) needs.push(h('div', {class: 'need red'}, h('span', {class: 'dot'}), h('div', {style: 'flex:1;min-width:0'},
    h('div', {class: 'q'}, a.name + ' is stuck'), h('div', {class: 'muted'}, tidy(a.needs)),
    h('div', {class: 'acts'}, btn('Tell it what to do', () => resume(a), 'go'), btn('See changes', () => showDiff('agent', a.name, a.name)), btn('Details', () => openDrawer(a.name), 'link')))));
  $('#needs-wrap').hidden = !needs.length;
  $('#needs').replaceChildren(...needs);

  const shown = showLanded ? S.agents : live;
  $('#agents-wrap').hidden = !S.agents.length;
  $('#agents').replaceChildren(...(shown.length ? shown.map(a => {
    const v = view(a), now = a.intents.length ? a.intents[a.intents.length - 1] : null;
    return h('button', {class: 'row-agent', onclick: () => openDrawer(a.name)},
      h('div', {class: 'who'}, h('div', {class: 'task'}, a.task), h('div', {class: 'sub'}, a.name + (now ? ' · ' + now : ''))),
      pill(v), h('span', {class: 'chev'}, '›'));
  }) : [h('div', {class: 'empty'}, 'Everything has landed.')]));
  $('#toggle-landed').hidden = !landed.length;
  $('#toggle-landed').textContent = showLanded ? 'Hide landed work' : 'Show ' + landed.length + ' landed';
}

// ---------- one agent, in the drawer ----------
function openDrawer(name) { openAgent = name; renderDrawer(); $('#drawer').classList.add('open'); $('#scrim').classList.add('open'); }
function closeDrawer() { openAgent = null; $('#drawer').classList.remove('open'); $('#scrim').classList.remove('open'); }
$('#d-close').onclick = closeDrawer; $('#scrim').onclick = closeDrawer;
function renderDrawer() {
  const a = openAgent && S.agents.find(x => x.name === openAgent);
  if (!a) { if (openAgent) closeDrawer(); return; }
  const v = view(a), live = !['landed', 'done'].includes(a.status);
  let note = null; const acts = [];
  if (v.ap) {
    note = h('div', {class: 'callout amber'}, 'It is finished and tested. It lands as soon as you say so.');
    acts.push(btn('Land it', () => run(['approve', String(v.ap.id)], 'Landing ' + a.name), 'go'), btn('Send back', () => sendBack(v.ap)));
  } else if (a.needs) {
    note = h('div', {class: 'callout red'}, tidy(a.needs));
    acts.push(btn('Tell it what to do', () => resume(a), 'go'));
  } else if (a.status === 'ready') {
    if (a.gate && !a.gate.ok) { note = h('div', {class: 'callout'}, a.gate.why); acts.push(btn('Approve it myself', () => run(['review', a.name, '--approve'], 'Approving ' + a.name), 'go')); }
    else { note = h('div', {class: 'callout'}, 'Reviewed. The watcher lands it on its next pass.'); acts.push(btn('Land now', () => run(['land', a.name], 'Landing ' + a.name), 'go')); }
    acts.push(btn('Ask for changes', () => askChanges(a)));
  } else if (a.status === 'active' && a.running) acts.push(btn('Send a message', () => message(a), 'go'));
  else if (a.status === 'active' && a.interactive) {
    note = h('div', {class: 'callout'}, 'No agent is running here. You can work in its folder yourself, then mark it done.');
    acts.push(btn('Mark it done', async () => { const m = await ask({title: 'Mark ' + a.name + ' done', text: 'A one-line summary of the work (optional).', input: true, ok: 'Mark done'}); if (m != null) run(['ready', a.name, ...(m ? [m] : [])], 'Marking ' + a.name + ' done'); }, 'go'));
  } else if (live) acts.push(btn('Resume', () => resume(a), 'go'));
  acts.push(btn('See changes', () => showDiff('agent', a.name, a.task)));

  const facts = [['Status', pill(v)], ['Working on', a.intents.length ? a.intents[a.intents.length - 1] : null],
    ['Files', a.owns.length ? a.owns.map(l => l.path).join(', ') : null],
    ['Commits', a.ahead != null ? String(a.ahead) : null], ['Lands on', a.base], ['Folder', h('span', {class: 'mono'}, a.worktree)]];
  const risks = S.risks.filter(r => r.a === a.name || r.b === a.name);
  if (risks.length) facts.push(['Overlaps', risks.map(r => (r.a === a.name ? r.b : r.a) + ' in ' + [].concat(r.files || []).join(', ')).join('; ')]);

  const quiet = live ? [btn('Sync with ' + a.base, () => run(['sync', a.name], 'Syncing ' + a.name), 'link'),
    a.running ? btn('Pause', () => run(['stop', a.name], 'Pausing ' + a.name), 'link') : null,
    btn('Remove this agent', () => run(['drop', a.name, '--delete'], 'Removing ' + a.name,
      {confirm: 'Remove ' + a.name + '?', detail: 'Its work is thrown away: the branch and folder are deleted.', ok: 'Remove'}), 'link')] : [];

  $('#d-name').textContent = a.name;
  $('#d-body').replaceChildren(h('div', {style: 'font-size:17px'}, a.task), note,
    h('div', {class: 'acts'}, acts),
    h('dl', {class: 'facts'}, ...facts.filter(f => f[1]).flatMap(([k, val]) => [h('dt', {}, k), h('dd', {}, val)])),
    quiet.length ? h('div', {class: 'quiet'}, quiet) : null);
}

// ---------- the other pages ----------
function renderActivity() {
  const chat = $('#chat');
  chat.replaceChildren(...(S.notes.length ? S.notes.slice(-40).map(n => h('div', {class: 'msg'},
    h('div', {class: 'from'}, (n.agent === 'human' ? 'You' : n.agent) + (n.to_agent ? ' to ' + n.to_agent : '') + ' · ' + clock(n.at)), n.text))
    : [h('div', {class: 'empty'}, 'No messages yet.')]));
  const to = $('#chat-to'), keep = to.value;
  to.replaceChildren(h('option', {value: ''}, 'All agents'), ...S.agents.filter(a => !['landed', 'done'].includes(a.status)).map(a => h('option', {value: a.name}, a.name)));
  to.value = keep;
  $('#risks').replaceChildren(...(S.risks.length ? S.risks.map(r => h('div', {class: 'msg'},
    h('b', {}, r.a + ' and ' + r.b), ' ', h('span', {class: 'muted'}, (r.severity === 'conflict' ? 'would conflict in ' : 'touch ') + [].concat(r.files || []).join(', '))))
    : [h('div', {class: 'empty'}, 'No two agents are about to collide.')]));
  $('#feed').replaceChildren(...(S.events.length ? S.events.slice().reverse().slice(0, 60).map(e => h('div', {},
    h('span', {class: 'dim'}, clock(e.at)), h('span', {}, e.agent ? h('b', {}, e.agent + ' ') : null, e.text)))
    : [h('div', {class: 'empty'}, 'Quiet so far.')]));
}
$('#chat-go').onclick = () => {
  const t = $('#chat-text').value.trim(); if (!t) return;
  run(['chat', '--post', t, ...($('#chat-to').value ? ['--to', $('#chat-to').value] : [])], 'Sending message'); $('#chat-text').value = '';
};
$('#chat-text').onkeydown = (e) => { if (e.key === 'Enter') $('#chat-go').click(); };

let editing = false;
function renderSettings() {
  if (editing) return;
  const rows = Object.entries(S.settings).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => {
    const input = h('input', {class: 'in mono', value: v == null ? '' : v, onfocus: () => editing = true, onblur: () => setTimeout(() => editing = false, 300)});
    return h('tr', {}, h('td', {class: 'mono'}, k), h('td', {}, input), h('td', {style: 'width:1%'}, btn('Save', () => { editing = false; run(['settings', k, input.value], 'Saving ' + k); })));
  });
  const nk = h('input', {class: 'in mono', placeholder: 'new setting'}), nv = h('input', {class: 'in mono', placeholder: 'value'});
  rows.push(h('tr', {}, h('td', {}, nk), h('td', {}, nv), h('td', {}, btn('Add', () => nk.value && run(['settings', nk.value, nv.value], 'Saving ' + nk.value)))));
  $('#settings').replaceChildren(...rows);
}

function renderCommands() {
  const q = $('#cmd-search').value.trim().toLowerCase();
  $('#commands').replaceChildren(...schema.filter(c => !q || (c.name + ' ' + (c.help || '')).toLowerCase().includes(q)).map(c => {
    const inputs = [];
    const fields = c.args.map(a => {
      let el;
      if (a.kind === 'flag') el = h('input', {type: 'checkbox'});
      else if (a.choices) el = h('select', {class: 'in'}, a.required ? null : h('option', {value: ''}, '(none)'), ...a.choices.map(x => h('option', {value: x}, x)));
      else if (a.kind === 'list') el = h('textarea', {class: 'in', placeholder: 'one per line'});
      else el = h('input', {class: 'in', type: a.int ? 'number' : 'text'});
      inputs.push([a, el]);
      return a.kind === 'flag' ? h('label', {style: 'display:flex;gap:8px;align-items:center'}, el, h('span', {class: 'mono'}, a.flag), a.help ? h('span', {class: 'dim', style: 'font-size:13px'}, a.help) : null)
        : h('div', {class: 'field'}, h('span', {}, (a.flag || a.dest) + (a.required ? ' (required)' : '')), el, a.help ? h('small', {}, a.help) : null);
    });
    const go = () => {
      const argv = [c.name];
      for (const [a, el] of inputs) {
        if (a.kind === 'flag') { if (el.checked) argv.push(a.flag); continue; }
        const vals = a.kind === 'list' ? el.value.split('\n').map(s => s.trim()).filter(Boolean) : (el.value.trim() ? [el.value.trim()] : []);
        if (!vals.length) { if (a.required) { ask({title: a.dest + ' is required'}); return; } continue; }
        if (a.flag) for (const v of vals) argv.push(a.flag, v); else argv.push(...vals);
      }
      if (c.name === 'do' && !argv.includes('--yes')) argv.push('--yes');
      run(argv, null, {show: true});
    };
    return h('details', {class: 'cmd'}, h('summary', {}, h('b', {}, c.name), h('span', {class: 'muted'}, c.help || '')),
      h('div', {class: 'fields'}, ...fields, h('div', {}, btn('Run', go, 'go'))));
  }));
}
$('#cmd-search').oninput = () => schema && renderCommands();
$('#raw-go').onclick = () => { const v = $('#raw').value.trim(); if (v) run(v.replace(/^braid\s+/, ''), null, {show: true}); };
$('#raw').onkeydown = (e) => { if (e.key === 'Enter') $('#raw-go').click(); };

async function renderHistory() {
  const jobs = await api('/api/jobs');
  $('#jobs').replaceChildren(...(jobs.length ? jobs.slice().reverse().map(j => h('div', {class: 'msg', style: 'display:flex;gap:12px;align-items:center'},
    h('span', {class: 'dim'}, clock(j.started)), h('span', {class: 'mono', style: 'flex:1;overflow-wrap:anywhere'}, 'braid ' + j.argv.join(' ')),
    h('span', {class: 'pill ' + (j.rc == null ? 's-working' : j.rc === 0 ? 's-ready' : 's-stuck')}, h('i'), j.rc == null ? 'running' : j.rc === 0 ? 'done' : 'failed'),
    btn('Output', () => { job = {id: j.id, argv: j.argv, label: 'braid ' + j.argv[0], out: j.out, rc: j.rc}; showOutput(); if (j.rc == null) poll(j.id); }, 'link')))
    : [h('div', {class: 'empty'}, 'Nothing run from this page yet.')]));
}

// ---------- navigation ----------
function go(p) {
  page = p; $('#menu').hidden = true;
  for (const s of ['home', 'activity', 'commands', 'settings', 'history']) $('#page-' + s).hidden = s !== p;
  document.body.classList.toggle('sub', p !== 'home');
  if (location.hash !== '#' + p) history.replaceState(null, '', p === 'home' ? location.pathname + location.search : '#' + p);
  window.scrollTo(0, 0);
  if (p === 'history') renderHistory();
  if (S) render();
}
$('#back').onclick = () => go('home');
$('#menu-btn').onclick = (e) => { e.stopPropagation(); $('#menu').hidden = !$('#menu').hidden; };
document.addEventListener('click', (e) => { if (!e.target.closest('.menu')) $('#menu').hidden = true; });
for (const b of document.querySelectorAll('[data-go]')) b.onclick = () => go(b.dataset.go);
const ACTS = {
  land: () => run(['land'], 'Landing ready work'),
  push: () => run(['push'], 'Pushing'),
  watcher: () => run(['daemon', S.daemon ? 'stop' : 'start'], S.daemon ? 'Turning the watcher off' : 'Turning the watcher on'),
  stopall: () => run(['stop', '--all'], 'Stopping all agents', {confirm: 'Stop every agent?', detail: 'Their work is kept. You can resume each one later.', ok: 'Stop all'}),
};
for (const b of document.querySelectorAll('[data-act]')) b.onclick = () => { $('#menu').hidden = true; ACTS[b.dataset.act](); };

// ---------- new work ----------
const EXAMPLES = ['Add a dark mode toggle', 'Write tests for the checkout flow', 'Fix the slow search page'];
$('#examples').replaceChildren(...EXAMPLES.map(t => h('button', {onclick: () => { $('#ask').value = t; $('#ask').focus(); grow(); }}, t)));
for (const b of document.querySelectorAll('[data-mode]')) b.onclick = () => {
  mode = b.dataset.mode;
  for (const x of document.querySelectorAll('[data-mode]')) x.classList.toggle('on', x === b);
  $('#ask').placeholder = mode === 'do' ? 'e.g. Add a dark mode toggle to the settings page' : 'One task per line, one agent each';
  $('#opt-max-row').hidden = $('#opt-push-row').hidden = mode !== 'do';
};
$('#opts-toggle').onclick = () => { $('#opts').hidden = !$('#opts').hidden; $('#opts-toggle').textContent = $('#opts').hidden ? 'Options' : 'Hide options'; };
const grow = () => { const t = $('#ask'); t.style.height = 'auto'; t.style.height = Math.min(t.scrollHeight, 220) + 'px'; };
$('#ask').oninput = grow;
$('#ask').onkeydown = (e) => { if (e.key === 'Enter' && !e.shiftKey && mode === 'do') { e.preventDefault(); $('#ask-go').click(); } };
$('#ask-go').onclick = () => {
  const text = $('#ask').value.trim();
  if (!text) { $('#ask').focus(); return; }
  const base = $('#opt-base').value.trim();
  if (mode === 'do') {
    const argv = ['do', '--yes', ...(base ? ['--base', base] : [])];
    if ($('#opt-max').value) argv.push('--max-agents', $('#opt-max').value);
    if ($('#opt-push').checked) argv.push('--push');
    run([...argv, text], 'Planning and starting agents');
  } else {
    const tasks = text.split('\n').map(s => s.trim()).filter(Boolean);
    run(['start', ...(base ? ['--base', base] : []), ...tasks], 'Starting ' + plural(tasks.length, 'agent'));
  }
  $('#ask').value = ''; grow();
};

// ---------- refresh ----------
function render() {
  $('#where').textContent = S.name + ' · ' + S.base;
  $('#watcher-item').replaceChildren(S.daemon ? 'Turn the watcher off' : 'Turn the watcher on', h('small', {}, S.daemon ? 'on' : 'off'));
  if (page === 'home') renderHome();
  if (page === 'activity') renderActivity();
  if (page === 'settings') renderSettings();
  renderDrawer();
}
$('#toggle-landed').onclick = () => { showLanded = !showLanded; render(); };
async function refresh() {
  try { S = await api('/api/state'); render(); }
  catch (e) { $('#where').textContent = 'Lost contact: ' + e.message; }
}
(async () => {
  const start = location.hash.slice(1);
  await refresh();
  go(['activity', 'commands', 'settings', 'history'].includes(start) ? start : 'home');
  try { schema = await api('/api/commands'); renderCommands(); } catch (e) { $('#commands').textContent = e.message; }
  setInterval(refresh, 2000);
})();
</script>
</body>
</html>
"""
