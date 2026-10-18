"""The single page `braid dashboard` serves. Plain HTML, CSS and JavaScript; no build step, no CDN."""

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="braid-token" content="__TOKEN__">
<meta name="color-scheme" content="dark">
<title>braid</title>
<style>
:root{--bg:#05080d;--panel:rgba(10,22,34,.72);--panel2:rgba(14,30,46,.85);--line:rgba(80,200,255,.16);--line2:rgba(80,200,255,.32);
--ink:#d8f3ff;--muted:#7d9bb0;--dim:#4d6678;--cyan:#38e1ff;--cyan2:#0fb5d9;--glow:0 0 18px rgba(56,225,255,.35);
--ok:#4cf2a0;--warn:#ffc552;--bad:#ff5f6d;--violet:#a98bff;
--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;--r:12px}
*{box-sizing:border-box}
[hidden]{display:none!important}
html{background:var(--bg)}
body{margin:0;color:var(--ink);font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;min-height:100vh;
background:radial-gradient(1200px 600px at 70% -10%,rgba(15,181,217,.16),transparent 60%),
radial-gradient(900px 500px at -10% 110%,rgba(56,225,255,.08),transparent 60%),
linear-gradient(rgba(56,225,255,.035) 1px,transparent 1px) 0 0/40px 40px,
linear-gradient(90deg,rgba(56,225,255,.035) 1px,transparent 1px) 0 0/40px 40px,var(--bg)}
button,input,textarea,select{font:inherit;color:inherit}
select option{background:#0b1620}
.label{font-family:var(--mono);font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--muted)}
.mono{font-family:var(--mono);font-size:12.5px}
.muted{color:var(--muted)}.dim{color:var(--dim)}
.spacer{flex:1}

header{position:sticky;top:0;z-index:10;display:flex;align-items:center;gap:14px;padding:12px 20px;
background:rgba(5,8,13,.82);backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
.reactor{width:42px;height:42px;flex:none;color:var(--cyan);filter:drop-shadow(0 0 6px currentColor);transition:color .4s}
.reactor .spin{transform-origin:50% 50%;animation:spin 14s linear infinite}
.reactor .spin2{transform-origin:50% 50%;animation:spin 9s linear infinite reverse}
.reactor .core{animation:pulse 2.6s ease-in-out infinite}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes pulse{0%,100%{opacity:.7}50%{opacity:1}}
.brand b{display:block;font-family:var(--mono);letter-spacing:.32em;font-size:15px;color:var(--cyan);text-shadow:var(--glow)}
.brand span{font-family:var(--mono);font-size:12px;color:var(--muted)}
.switch{display:flex;align-items:center;gap:8px;cursor:pointer;border:1px solid var(--line);border-radius:99px;padding:4px 12px 4px 6px;background:var(--panel)}
.switch i{width:30px;height:16px;border-radius:99px;background:#1b2b38;position:relative;transition:.2s}
.switch i::after{content:"";position:absolute;top:2px;left:2px;width:12px;height:12px;border-radius:50%;background:var(--dim);transition:.2s}
.switch.on i{background:rgba(76,242,160,.25)}
.switch.on i::after{left:16px;background:var(--ok);box-shadow:0 0 8px var(--ok)}
nav{display:flex;gap:4px}
nav button{background:none;border:1px solid transparent;border-radius:8px;padding:6px 12px;cursor:pointer;color:var(--muted);
font-family:var(--mono);font-size:12px;letter-spacing:.12em;text-transform:uppercase}
nav button:hover{color:var(--ink)}
nav button.on{color:var(--cyan);border-color:var(--line2);background:rgba(56,225,255,.06);text-shadow:var(--glow)}
main{max-width:1380px;margin:0 auto;padding:22px 20px 40px}

.panel{position:relative;background:var(--panel);border:1px solid var(--line);border-radius:var(--r);padding:16px 18px;margin-bottom:18px}
.panel::before,.panel::after{content:"";position:absolute;width:14px;height:14px;border:2px solid var(--cyan);opacity:.55;pointer-events:none}
.panel::before{top:-1px;left:-1px;border-right:0;border-bottom:0;border-top-left-radius:var(--r)}
.panel::after{bottom:-1px;right:-1px;border-left:0;border-top:0;border-bottom-right-radius:var(--r)}
.panel > .head{display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap}
.count{font-family:var(--mono);font-size:11px;color:var(--cyan);border:1px solid var(--line2);border-radius:99px;padding:0 8px}

.command{display:flex;flex-direction:column;gap:10px;padding:18px 20px}
.command .ask{display:flex;align-items:center;gap:12px;border:1px solid var(--line2);border-radius:12px;padding:6px 6px 6px 16px;
background:rgba(3,10,16,.7);box-shadow:inset 0 0 24px rgba(56,225,255,.06)}
.command .ask:focus-within{border-color:var(--cyan);box-shadow:var(--glow),inset 0 0 24px rgba(56,225,255,.08)}
.command .prompt{font-family:var(--mono);color:var(--cyan);text-shadow:var(--glow)}
.command textarea{flex:1;min-width:0;background:none;border:0;outline:0;resize:none;font-size:16px;padding:8px 0;min-height:24px;max-height:180px}
.command textarea::placeholder,.command input::placeholder{color:var(--dim)}
.modes{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.chip{border:1px solid var(--line);background:none;border-radius:99px;padding:3px 12px;cursor:pointer;color:var(--muted);font-size:12.5px}
.chip.on{border-color:var(--cyan);color:var(--cyan);background:rgba(56,225,255,.07)}
.opts{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.opts input[type=text],.opts input[type=number]{background:rgba(3,10,16,.6);border:1px solid var(--line);border-radius:8px;padding:5px 9px;outline:0}
.opts input:focus{border-color:var(--cyan2)}

.btn{border:1px solid var(--line2);background:rgba(56,225,255,.04);border-radius:8px;padding:6px 13px;cursor:pointer;white-space:nowrap;color:var(--ink);transition:.15s}
.btn:hover{border-color:var(--cyan);color:var(--cyan);box-shadow:0 0 12px rgba(56,225,255,.18)}
.btn.go{background:linear-gradient(180deg,#2ad4f5,#0e9fc4);border-color:#5ae8ff;color:#021018;font-weight:650;box-shadow:0 0 16px rgba(56,225,255,.35)}
.btn.go:hover{color:#021018;filter:brightness(1.1)}
.btn.ok{border-color:rgba(76,242,160,.6);color:var(--ok)}
.btn.bad{border-color:rgba(255,95,109,.45);color:var(--bad)}
.btn.bad:hover{box-shadow:0 0 12px rgba(255,95,109,.25)}
.btn.ghost{border-color:transparent;background:none;color:var(--muted)}
.btn.ghost:hover{color:var(--ink);box-shadow:none}
.btn.sm{padding:3px 10px;font-size:12.5px}

.stats{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:18px}
@media (max-width:760px){.stats{grid-template-columns:repeat(3,1fr)}}
.stat{position:relative;background:var(--panel);border:1px solid var(--line);border-radius:var(--r);padding:12px 14px;overflow:hidden}
.stat b{display:block;font-family:var(--mono);font-size:28px;font-weight:500;line-height:1.1;text-shadow:0 0 14px currentColor}
.stat::after{content:"";position:absolute;left:0;bottom:0;height:2px;width:100%;background:currentColor;opacity:.6}
.stat.cyan{color:var(--cyan)}.stat.ok{color:var(--ok)}.stat.warn{color:var(--warn)}.stat.bad{color:var(--bad)}.stat.violet{color:var(--violet)}
.stat .label{color:var(--muted)}
.stat.zero{color:var(--dim)}.stat.zero b{text-shadow:none}

.grid{display:grid;grid-template-columns:minmax(0,1fr) 400px;gap:18px}
@media (max-width:1040px){.grid{grid-template-columns:minmax(0,1fr)}}
.panel,.agent,.need,.msg{overflow-wrap:anywhere}

.need{display:flex;gap:12px;align-items:flex-start;padding:12px;border-radius:10px;border:1px solid rgba(255,197,82,.35);
background:linear-gradient(90deg,rgba(255,197,82,.08),transparent);margin-bottom:10px}
.need.red{border-color:rgba(255,95,109,.4);background:linear-gradient(90deg,rgba(255,95,109,.09),transparent)}
.need .icon{font-family:var(--mono);color:var(--warn);font-size:18px;line-height:1.2}
.need.red .icon{color:var(--bad)}
.need .what{flex:1;min-width:0}
.need .what b{display:block}
.need .acts{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.clear{display:flex;align-items:center;gap:10px;color:var(--muted)}
.clear::before{content:"";width:8px;height:8px;border-radius:50%;background:var(--ok);box-shadow:0 0 10px var(--ok)}

.agents{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(300px,100%),1fr));gap:14px}
.agent{position:relative;border:1px solid var(--line);border-radius:12px;padding:14px 14px 14px 17px;background:var(--panel2);display:flex;flex-direction:column;gap:8px;overflow:hidden}
.agent::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--c,var(--cyan));box-shadow:0 0 12px var(--c,var(--cyan))}
.agent .top{display:flex;align-items:center;gap:10px}
.agent .name{font-family:var(--mono);font-size:13px;color:var(--ink);letter-spacing:.03em}
.state{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--c,var(--cyan));font-weight:600}
.state::before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor;box-shadow:0 0 8px currentColor}
.state.live::before{animation:blink 1.4s ease-in-out infinite}
@keyframes blink{50%{opacity:.25}}
.agent .task{font-size:14.5px}
.agent .why{font-size:12.5px;padding:7px 10px;border-radius:8px;background:rgba(255,255,255,.03);border:1px solid var(--line)}
.agent .why.bad{border-color:rgba(255,95,109,.4);color:#ffc2c7}
.agent .why.ok{border-color:rgba(76,242,160,.35);color:#c1ffe0}
.agent .acts{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-top:2px}
.agent .more{display:flex;gap:6px;flex-wrap:wrap;padding-top:8px;border-top:1px dashed var(--line)}
.c-active{--c:var(--cyan)}.c-ready{--c:var(--warn)}.c-landed{--c:var(--ok)}.c-blocked{--c:var(--bad)}.c-exited{--c:var(--violet)}.c-paused,.c-done{--c:var(--dim)}

.rows > div{padding:10px 0;border-top:1px solid var(--line)}
.rows > div:first-child{border-top:0;padding-top:0}
.tag{font-family:var(--mono);font-size:11px;letter-spacing:.08em;text-transform:uppercase;border-radius:5px;padding:1px 7px;border:1px solid currentColor}
.t-conflict,.t-blocked,.t-rejected,.t-failed{color:var(--bad)}.t-semantic{color:var(--violet)}.t-overlap,.t-pending,.t-ready,.t-proposed{color:var(--warn)}
.t-landed,.t-approved,.t-done{color:var(--ok)}.t-running,.t-active{color:var(--cyan)}.t-cancelled{color:var(--dim)}
.bar{height:4px;border-radius:99px;background:#13222f;overflow:hidden;margin-top:6px}
.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--cyan2),var(--ok));box-shadow:0 0 8px var(--cyan)}
.empty{color:var(--dim);font-size:13px}

.comms{max-height:330px;overflow:auto;display:flex;flex-direction:column;gap:8px;padding-right:4px}
.msg{padding:8px 10px;border-radius:10px;background:rgba(255,255,255,.025);border:1px solid var(--line);font-size:13px}
.msg.me{background:rgba(56,225,255,.06);border-color:var(--line2);margin-left:28px}
.msg.sys{border-style:dashed}
.msg .who{font-family:var(--mono);font-size:11.5px;color:var(--muted);margin-bottom:2px}
.send{display:flex;gap:8px;margin-top:10px}
.send select,.send input{background:rgba(3,10,16,.6);border:1px solid var(--line);border-radius:8px;padding:6px 9px;outline:0;min-width:0}
.send select{max-width:120px}
.send input{flex:1}
.send input:focus,.send select:focus{border-color:var(--cyan2)}
.log{max-height:420px;overflow:auto;font-family:var(--mono);font-size:12px;line-height:1.55}
.log div{display:grid;grid-template-columns:62px 64px 1fr;gap:8px;padding:2px 0}
.log .t{color:var(--dim)}.log .k{color:var(--cyan)}
::-webkit-scrollbar{width:8px;height:8px}::-webkit-scrollbar-thumb{background:#1a2c3a;border-radius:8px}

.cmd{border:1px solid var(--line);border-radius:10px;margin-bottom:8px;background:var(--panel)}
.cmd summary{cursor:pointer;padding:10px 14px;display:flex;gap:14px;align-items:baseline;list-style:none}
.cmd summary::-webkit-details-marker{display:none}
.cmd summary b{font-family:var(--mono);color:var(--cyan);min-width:110px;font-weight:500}
.cmd[open] summary{border-bottom:1px solid var(--line)}
.cmd .body{padding:12px 14px;display:grid;gap:10px}
.field{display:grid;grid-template-columns:150px 1fr;gap:10px;align-items:center}
@media (max-width:640px){.field{grid-template-columns:1fr}}
.field .lbl{font-family:var(--mono);font-size:12.5px;color:var(--muted)}
.field .help{grid-column:2;color:var(--dim);font-size:12px;margin-top:-6px}
.field input[type=checkbox]{justify-self:start;accent-color:var(--cyan)}
.in{background:rgba(3,10,16,.6);border:1px solid var(--line);border-radius:8px;padding:6px 9px;outline:0;width:100%}
.in:focus{border-color:var(--cyan2)}
textarea.in{min-height:56px;resize:vertical}
table{width:100%;border-collapse:collapse}
td,th{text-align:left;padding:7px 8px;border-top:1px solid var(--line);vertical-align:middle}
th{font-family:var(--mono);font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);font-weight:500}

#console{position:fixed;left:16px;right:16px;bottom:16px;z-index:20;max-height:42vh;display:none;flex-direction:column;
background:rgba(3,9,14,.96);border:1px solid var(--line2);border-radius:12px;box-shadow:0 0 40px rgba(0,0,0,.6),var(--glow)}
#console.open{display:flex}
#console .top{display:flex;align-items:center;gap:10px;padding:8px 14px;border-bottom:1px solid var(--line)}
#console pre{margin:0;padding:12px 14px;overflow:auto;font:12.5px/1.5 var(--mono);white-space:pre-wrap;color:#bfefff}
body.console-open main{padding-bottom:46vh}

#dialog{position:fixed;inset:0;z-index:30;background:rgba(0,4,8,.7);backdrop-filter:blur(3px);display:none;align-items:center;justify-content:center;padding:20px}
#dialog.open{display:flex}
#dialog .box{width:min(560px,100%);margin:0}
#dialog.wide .box{width:min(1100px,100%);max-height:88vh;display:flex;flex-direction:column}
#dialog pre{margin:0;overflow:auto;font:12.5px/1.5 var(--mono);max-height:68vh}
.d-add{color:var(--ok)}.d-del{color:var(--bad)}.d-hunk{color:var(--cyan)}.d-file{color:var(--warn);font-weight:700;margin-top:6px}
.toast{position:fixed;right:20px;top:76px;z-index:40;background:var(--panel2);border:1px solid var(--line2);color:var(--ink);padding:9px 14px;border-radius:10px;
box-shadow:var(--glow);opacity:0;transform:translateY(-6px);transition:.2s;pointer-events:none}
.toast.show{opacity:1;transform:none}
@media (max-width:640px){header{flex-wrap:wrap;padding:10px 14px}nav{width:100%;overflow-x:auto}main{padding:16px 14px 40px}.brand span{display:none}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style>
</head>
<body>
<header>
  <svg class="reactor" viewBox="0 0 42 42" aria-hidden="true">
    <circle cx="21" cy="21" r="19" fill="none" stroke="currentColor" stroke-opacity=".25" stroke-width="1"/>
    <g class="spin"><circle cx="21" cy="21" r="16" fill="none" stroke="currentColor" stroke-width="2" stroke-dasharray="10 6" stroke-opacity=".8"/></g>
    <g class="spin2"><circle cx="21" cy="21" r="11" fill="none" stroke="currentColor" stroke-width="1.2" stroke-dasharray="3 4"/></g>
    <circle class="core" cx="21" cy="21" r="6" fill="currentColor"/>
  </svg>
  <div class="brand"><b>BRAID</b><span id="where">connecting</span></div>
  <span class="spacer"></span>
  <div class="switch" id="watcher" title="The watcher predicts conflicts and lands ready work"><i></i><span class="label" id="watcher-label">watcher</span></div>
  <nav id="nav">
    <button data-tab="home" class="on">Mission</button>
    <button data-tab="commands">Commands</button>
    <button data-tab="settings">Settings</button>
    <button data-tab="history">History</button>
  </nav>
</header>
<main>
<section id="tab-home">
  <div class="panel command">
    <div class="ask"><span class="prompt">&gt;</span>
      <textarea id="ask" rows="1" placeholder="What should we build? e.g. add login with Google and a settings page"></textarea>
      <button class="btn go" id="ask-go">Plan it</button></div>
    <div class="modes">
      <button class="chip on" data-mode="do">Plan it for me</button>
      <button class="chip" data-mode="start">One agent per line</button>
      <span class="spacer"></span>
      <button class="btn ghost sm" id="opts-toggle">Options</button>
    </div>
    <div class="opts" id="opts" hidden>
      <input type="text" id="opt-base" placeholder="land on branch (default: base)" style="width:240px">
      <input type="number" id="opt-max" min="1" placeholder="max agents" style="width:120px">
      <label class="muted" id="opt-push-label"><input type="checkbox" id="opt-push"> push when everything lands</label>
    </div>
  </div>

  <div class="stats" id="stats"></div>

  <div class="grid">
    <div>
      <div class="panel"><div class="head"><span class="label">Needs you</span><span class="count" id="needs-count">0</span></div><div id="needs"></div></div>
      <div class="panel">
        <div class="head"><span class="label">Agents</span><span class="count" id="agents-count">0</span><span class="spacer"></span>
          <button class="btn sm" data-run="land" title="Land every agent that is reviewed and ready">Land ready</button>
          <button class="btn sm" data-run="ship" title="Land ready work, then push">Ship</button>
          <button class="btn ghost sm" id="more-toggle">More</button></div>
        <div id="more-bar" style="display:none;gap:6px;flex-wrap:wrap;align-items:center;margin:-4px 0 12px">
          <button class="btn sm" data-run="check">Check conflicts now</button>
          <button class="btn sm" data-run="push">Push</button>
          <button class="btn sm" data-run="sync --all">Sync all</button>
          <button class="btn sm" data-run="prune">Clear landed</button>
          <label class="muted" style="font-size:12.5px;display:flex;gap:6px;align-items:center"><input type="checkbox" id="show-landed"> show landed</label>
          <span class="spacer"></span>
          <button class="btn bad sm" data-run="stop --all" data-confirm="Stop every agent and the watcher?">Stop everything</button>
        </div>
        <div class="agents" id="agents"></div>
      </div>
      <div class="panel"><div class="head"><span class="label">Conflict radar</span><span class="count" id="risks-count">0</span></div><div class="rows" id="risks"></div></div>
      <div class="panel"><div class="head"><span class="label">Plans</span></div><div class="rows" id="plans"></div></div>
      <div class="panel"><div class="head"><span class="label">Approvals</span><span class="muted" id="approvals-mode" style="font-size:12.5px"></span></div><div class="rows" id="approvals"></div></div>
    </div>
    <div>
      <div class="panel"><div class="head"><span class="label">Comms</span></div>
        <div class="comms" id="chat"></div>
        <div class="send"><select id="chat-to"><option value="">all agents</option></select>
          <input id="chat-text" placeholder="Tell the agents something"><button class="btn" id="chat-go">Send</button></div></div>
      <div class="panel"><div class="head"><span class="label">Activity log</span></div><div class="log" id="feed"></div></div>
      <div class="panel"><div class="head"><span class="label">Your checkout</span></div><pre class="mono muted" id="git" style="margin:0;white-space:pre-wrap"></pre></div>
    </div>
  </div>
</section>

<section id="tab-commands" hidden>
  <div class="panel command">
    <div class="ask"><span class="prompt">braid</span><input id="raw" class="mono" style="flex:1;min-width:0;background:none;border:0;outline:0;padding:9px 0;font-size:14px" placeholder="log --oneline -5      any braid or git command">
      <button class="btn go" id="raw-go">Run</button></div>
    <div class="muted" style="font-size:12.5px">Every command below is the real CLI command. Its form is built from the CLI itself, so nothing is missing.</div>
  </div>
  <div id="commands"></div>
</section>

<section id="tab-settings" hidden>
  <div class="panel"><div class="head"><span class="label">Settings</span></div>
    <p class="muted" style="margin-top:0">Saving runs <span class="mono">braid settings key value</span>. Tick "every repo" to save it for all your projects.</p>
    <table><thead><tr><th>key</th><th>value</th><th></th></tr></thead><tbody id="settings"></tbody></table></div>
</section>

<section id="tab-history" hidden><div class="panel"><div class="head"><span class="label">Run from this page</span></div><div class="rows" id="jobs"></div></div></section>
</main>

<div id="console"><div class="top"><span class="label">console</span><span class="mono" id="console-title"></span><span id="console-state"></span><span class="spacer"></span>
  <button class="btn sm" id="console-stop">Stop</button><button class="btn ghost sm" id="console-close">Close</button></div><pre id="console-out"></pre></div>
<div id="dialog"><div class="box panel" id="dialog-box"></div></div>
<div class="toast" id="toast"></div>

<script>
const TOKEN = document.querySelector('meta[name=braid-token]').content;
const $ = (s) => document.querySelector(s);
let S = null, schema = null, showingJob = null, mode = 'do';
const openMore = new Set();

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
const btn = (label, fn, cls, title) => h('button', {class: 'btn sm ' + (cls || ''), onclick: fn, title}, label);
const tag = (text, cls) => h('span', {class: 'tag t-' + (cls || text)}, text);
const clock = (t) => new Date(t * 1000).toTimeString().slice(0, 8);
function toast(msg) { const t = $('#toast'); t.textContent = msg; t.classList.add('show'); clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove('show'), 2600); }

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

// ---------- dialog: a friendlier prompt()/confirm() ----------
function closeDialog() { $('#dialog').classList.remove('open', 'wide'); }
function dialog({title, text, placeholder, okLabel, danger, input}) {
  return new Promise((resolve) => {
    const field = input ? h('textarea', {class: 'in', placeholder: placeholder || '', rows: 3}) : null;
    const done = (v) => { closeDialog(); resolve(v); };
    $('#dialog-box').replaceChildren(
      h('div', {class: 'head'}, h('span', {class: 'label'}, title)),
      text ? h('p', {style: 'margin:0 0 12px'}, text) : null, field,
      h('div', {style: 'display:flex;gap:8px;justify-content:flex-end;margin-top:14px'},
        btn('Cancel', () => done(null), 'ghost'),
        btn(okLabel || 'OK', () => done(field ? field.value.trim() : true), danger ? 'bad' : 'go')));
    $('#dialog').classList.add('open');
    if (field) { field.focus(); field.onkeydown = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); done(field.value.trim()); } }; }
  });
}
$('#dialog').onclick = (e) => { if (e.target.id === 'dialog') closeDialog(); };
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDialog(); });

async function showDiff(kind, ref, title) {
  const pre = h('pre', {}, 'loading...');
  $('#dialog-box').replaceChildren(h('div', {class: 'head'}, h('span', {class: 'label'}, 'changes'), h('span', {class: 'mono'}, title),
    h('span', {class: 'spacer'}), btn('Close', closeDialog, 'ghost')), pre);
  $('#dialog').classList.add('open', 'wide');
  try {
    const d = await api('/api/diff?kind=' + kind + '&ref=' + encodeURIComponent(ref));
    pre.textContent = '';
    for (const line of (d.diff || '(no changes yet)').split('\n')) {
      const cls = line.startsWith('diff --git') ? 'd-file' : line.startsWith('@@') ? 'd-hunk'
        : line.startsWith('+') && !line.startsWith('+++') ? 'd-add' : line.startsWith('-') && !line.startsWith('---') ? 'd-del' : '';
      pre.append(h('div', {class: cls}, line || ' '));
    }
    if (d.cut) pre.append(h('div', {class: 'muted'}, '... cut here; run git diff for the rest'));
  } catch (e) { pre.textContent = e.message; }
}

// ---------- running commands ----------
async function run(argv, opts = {}) {
  if (typeof argv === 'string') argv = split(argv);
  if (opts.confirm && !(await dialog({title: 'Confirm', text: opts.confirm, okLabel: 'Yes, do it', danger: true}))) return;
  try { const {job} = await api('/api/run', {argv}); openJob(job, argv); }
  catch (e) { toast(e.message); }
}
function openJob(id, argv) {
  showingJob = id;
  $('#console-title').textContent = 'braid ' + argv.map(a => /\s/.test(a) ? JSON.stringify(a) : a).join(' ');
  $('#console-out').textContent = '';
  $('#console').classList.add('open'); document.body.classList.add('console-open');
  pollJob(id);
}
async function pollJob(id) {
  if (showingJob !== id) return;
  try {
    const j = await api('/api/jobs/' + id);
    const out = $('#console-out'); const atEnd = out.scrollTop + out.clientHeight >= out.scrollHeight - 20;
    out.textContent = j.out || (j.rc == null ? 'working...' : '(no output)');
    if (atEnd) out.scrollTop = out.scrollHeight;
    $('#console-state').replaceChildren(j.rc == null ? tag('running') : j.rc === 0 ? tag('done') : tag('failed'));
    $('#console-stop').hidden = j.rc != null;
    if (j.rc == null) setTimeout(() => pollJob(id), 700); else refresh();
  } catch (e) { $('#console-out').textContent = e.message; }
}
$('#console-close').onclick = () => { showingJob = null; $('#console').classList.remove('open'); document.body.classList.remove('console-open'); };
$('#console-stop').onclick = () => showingJob && api('/api/jobs/' + showingJob + '/stop', {});

const ask = (title, text, placeholder) => dialog({title, text, placeholder, input: true, okLabel: 'Send'});
const resume = async (a) => { const m = await ask('Resume ' + a.name, 'What should it do next? Leave it empty to let it carry on where it stopped.'); if (m != null) run(['resume', a.name, ...(m ? [m] : [])]); };

// ---------- the mission view ----------
const tidy = (t) => (t || '').replace(/^landing it was blocked: (blocked: )?/, 'Landing failed: ');
const WORDS = {active: 'Working', ready: 'Ready to land', landed: 'Landed', blocked: 'Blocked', exited: 'Stopped early', paused: 'Paused', done: 'Done'};

function agentCard(a) {
  const main = [], more = [btn('See changes', () => showDiff('agent', a.name, a.name + ' vs ' + a.base))];
  let why = null;
  const asked = S.approvals.find(x => x.status === 'pending' && x.agent === a.name);
  if (asked) {
    main.push(btn('Land it', () => run(['approve', String(asked.id)]), 'go'));
    main.push(btn('See changes', () => showDiff('approval', String(asked.id), '#' + asked.id + ' ' + asked.title)));
    why = h('div', {class: 'why'}, 'Reviewed and tested. Waiting for your yes (approval #' + asked.id + ').');
  } else if (a.status === 'ready') {
    if (a.gate && !a.gate.ok) {
      main.push(btn('Approve', () => run(['review', a.name, '--approve']), 'ok', 'Review it yourself and approve'));
      why = h('div', {class: 'why'}, a.gate.why);
    } else {
      main.push(btn('Land now', () => run(['land', a.name]), 'go'));
      why = h('div', {class: 'why ok'}, 'Reviewed. The watcher lands it on its next pass, or land it now.');
    }
    main.push(btn('Ask for changes', async () => { const m = await ask('Changes for ' + a.name, 'What should it change?'); if (m) run(['review', a.name, '--changes', '-m', m]); }));
  } else if (a.needs) {
    main.push(btn('Resume', () => resume(a), 'go'));
    why = h('div', {class: 'why bad'}, tidy(a.needs));
  } else if (a.status === 'active') {
    if (a.running) main.push(btn('Message', async () => { const m = await ask('Message ' + a.name, 'It reads this on its next step.'); if (m) run(['chat', '--post', m, '--to', a.name]); }));
    else if (a.interactive) {
      main.push(btn('Mark ready', async () => { const m = await ask('Mark ' + a.name + ' ready', 'A one-line summary of the work (optional).'); if (m != null) run(['ready', a.name, ...(m ? [m] : [])]); }));
      why = h('div', {class: 'why', title: a.worktree}, 'You drive this one, in its own folder: ' + a.worktree.split('/').slice(-2).join('/'));
    }
  } else if (a.status === 'paused' || a.status === 'exited') main.push(btn('Resume', () => resume(a), 'go'));
  if (!['landed', 'done'].includes(a.status)) {
    more.push(btn('Sync with ' + a.base, () => run(['sync', a.name])));
    if (!main.length || a.status === 'active') more.push(btn('Resume', () => resume(a)));
    if (a.running) more.push(btn('Stop', () => run(['stop', a.name])));
    more.push(btn('Drop', () => run(['drop', a.name, '--delete'], {confirm: 'Abandon ' + a.name + '? Its branch and folder are deleted.'}), 'bad'));
  }
  const open = openMore.has(a.name);
  const toggle = btn(open ? 'Less' : 'More', () => { open ? openMore.delete(a.name) : openMore.add(a.name); render(); }, 'ghost');
  const doing = a.intents.length ? a.intents[a.intents.length - 1] : null;
  return h('div', {class: 'agent c-' + a.status},
    h('div', {class: 'top'}, h('span', {class: 'name'}, a.name), h('span', {class: 'spacer'}),
      h('span', {class: 'state' + (a.running ? ' live' : '')}, asked ? 'Waiting for you' : WORDS[a.status] || a.status)),
    h('div', {class: 'task'}, a.task),
    h('div', {class: 'muted', style: 'font-size:12.5px'},
      (a.ahead != null ? a.ahead + ' commit' + (a.ahead === 1 ? '' : 's') + ' · ' : '') + 'lands on ' + a.base +
      (a.owns.length ? ' · owns ' + a.owns.map(l => l.path).join(', ') : '')),
    doing ? h('div', {class: 'muted', style: 'font-size:12.5px'}, h('span', {class: 'dim'}, 'now: '), doing) : null,
    why,
    h('div', {class: 'acts'}, main, h('span', {class: 'spacer'}), toggle),
    open ? h('div', {class: 'more'}, more) : null);
}

function stat(n, label, cls) { return h('div', {class: 'stat ' + (n ? cls : 'zero')}, h('b', {}, n), h('span', {class: 'label'}, label)); }

function render() {
  $('#where').textContent = S.name + '  →  ' + S.base;
  $('#watcher').classList.toggle('on', !!S.daemon);
  $('#watcher-label').textContent = S.daemon ? 'watcher on' : 'watcher off';

  const live = S.agents.filter(a => !['landed', 'done'].includes(a.status));
  const pending = S.approvals.filter(a => a.status === 'pending');
  const stuck = S.agents.filter(a => a.needs);
  const count = (st) => S.agents.filter(a => a.status === st).length;
  $('#stats').replaceChildren(
    stat(count('active'), 'working', 'cyan'), stat(count('ready'), 'ready', 'warn'),
    stat(stuck.length, 'stuck', 'bad'), stat(S.risks.filter(r => r.severity !== 'overlap').length, 'conflicts', 'violet'),
    stat(count('landed'), 'landed', 'ok'));
  document.querySelector('.reactor').style.color = stuck.length ? 'var(--bad)' : (pending.length || S.decisions.length) ? 'var(--warn)' : 'var(--cyan)';

  const needs = [];
  const need = (icon, title, detail, acts, red) => needs.push(h('div', {class: 'need' + (red ? ' red' : '')},
    h('span', {class: 'icon'}, icon), h('div', {class: 'what'}, h('b', {}, title), detail ? h('div', {class: 'muted'}, detail) : null, h('div', {class: 'acts'}, acts))));
  for (const a of pending) need('◆', 'Land "' + a.title + '"?', a.agent + ' · +' + a.added + ' / -' + a.removed + ' · ' + (a.tests ? 'tests pass' : 'tests FAILED') + (a.risk ? ' · risk ' + a.risk : ''), [
    btn('Land it', () => run(['approve', String(a.id)]), 'go'),
    btn('See changes', () => showDiff('approval', String(a.id), '#' + a.id + ' ' + a.title)),
    btn('Send back', async () => { const m = await ask('Send back #' + a.id, 'Why? The agent gets this and fixes it.'); if (m != null) run(['reject', String(a.id), ...(m ? ['-m', m] : [])]); }, 'bad')]);
  for (const d of S.decisions) need('✦', 'Accept an automatic conflict fix?', d.agent + ' vs ' + [].concat(d.parties || []).join(', ') + ' in ' + [].concat(d.files || []).join(', ') + '. ' + d.detail, [
    btn('Accept', () => run(['vote', String(d.id), 'accept']), 'ok'),
    btn('Object', async () => { const m = await ask('Object to #' + d.id, 'Why? This stops the landing.'); if (m != null) run(['vote', String(d.id), 'object', ...(m ? [m] : [])]); }, 'bad')]);
  for (const a of stuck) need('▲', a.name + ' is stuck', tidy(a.needs), [btn('Resume', () => resume(a), 'go'), btn('See changes', () => showDiff('agent', a.name, a.name))], true);
  $('#needs').replaceChildren(...(needs.length ? needs : [h('div', {class: 'clear'}, 'All clear. Nothing is waiting on you.')]));
  $('#needs-count').textContent = needs.length;

  const agents = $('#show-landed').checked ? S.agents : live;
  $('#agents').replaceChildren(...(agents.length ? agents.map(agentCard)
    : [h('div', {class: 'empty'}, S.agents.length ? 'Every agent has landed. Describe the next job above.' : 'No agents yet. Describe what to build above and press Plan it.')]));
  $('#agents-count').textContent = agents.length;

  $('#risks').replaceChildren(...(S.risks.length ? S.risks.map(r => h('div', {style: 'display:flex;gap:10px;align-items:center;flex-wrap:wrap'},
    tag(r.severity), h('b', {class: 'mono'}, r.a + '  ↔  ' + r.b), h('span', {class: 'muted mono'}, [].concat(r.files || []).join(', ')),
    h('span', {class: 'spacer'}), r.severity === 'conflict' ? h('span', {class: 'dim', style: 'font-size:12px'}, 'both agents have been told') : null))
    : [h('div', {class: 'empty'}, 'Radar clear. No two agents are about to collide.')]));
  $('#risks-count').textContent = S.risks.length;

  $('#plans').replaceChildren(...(S.plans.length ? S.plans.slice().reverse().map(p => {
    const done = p.tasks.filter(t => t.status === 'landed').length, pct = p.tasks.length ? Math.round(100 * done / p.tasks.length) : 0;
    return h('div', {},
      h('div', {style: 'display:flex;gap:10px;align-items:center;flex-wrap:wrap'}, tag(p.status), h('b', {}, p.goal), h('span', {class: 'spacer'}),
        h('span', {class: 'muted mono'}, done + '/' + p.tasks.length + ' → ' + p.base),
        p.status === 'proposed' ? btn('Start', () => run(['plans', 'start', String(p.id)]), 'go') : null,
        ['running', 'proposed'].includes(p.status) ? btn('Cancel', () => run(['plans', 'cancel', String(p.id)], {confirm: 'Cancel plan #' + p.id + '?'}), 'bad') : null),
      h('div', {class: 'bar'}, h('i', {style: 'width:' + pct + '%'})),
      h('div', {class: 'muted', style: 'font-size:12.5px;margin-top:6px'}, p.tasks.map(t => t.title + ' (' + t.status + ')').join('  ·  ')));
  }) : [h('div', {class: 'empty'}, 'No plans yet.')]));

  $('#approvals-mode').textContent = S.approvals_on ? 'on, ' + ((S.settings['approve.mode'] || 'each') === 'run' ? 'one request per run' : 'one request per landing') : 'off';
  $('#approvals').replaceChildren(...(S.approvals.length ? S.approvals.slice().reverse().map(a => h('div', {},
    h('div', {style: 'display:flex;gap:10px;align-items:center;flex-wrap:wrap'}, tag(a.status), h('span', {}, a.title), h('span', {class: 'spacer'}),
      h('span', {class: 'muted mono'}, '+' + a.added + ' / -' + a.removed), btn('Changes', () => showDiff('approval', String(a.id), '#' + a.id + ' ' + a.title)),
      btn('Details', () => run(['approvals', 'show', String(a.id)]), 'ghost')),
    a.summary ? h('div', {class: 'muted', style: 'font-size:12.5px;margin-top:4px'}, a.summary) : null))
    : [h('div', {class: 'empty'}, S.approvals_on ? 'Nothing asked yet.' : 'Off: work lands without asking you. Turn on approve.required in Settings.')]));

  const chat = $('#chat'); const atEnd = chat.scrollTop + chat.clientHeight >= chat.scrollHeight - 20;
  chat.replaceChildren(...(S.notes.length ? S.notes.map(n => h('div', {class: 'msg' + (n.agent === 'human' ? ' me' : n.agent === 'braid' ? ' sys' : '')},
    h('div', {class: 'who'}, (n.agent === 'human' ? 'you' : n.agent) + (n.to_agent ? ' → ' + n.to_agent : '') + '  ·  ' + n.topic + '  ·  ' + clock(n.at)), n.text))
    : [h('div', {class: 'empty'}, 'No messages yet.')]));
  if (atEnd) chat.scrollTop = chat.scrollHeight;
  const to = $('#chat-to'), keep = to.value;
  to.replaceChildren(h('option', {value: ''}, 'all agents'), ...live.map(a => h('option', {value: a.name}, a.name)));
  to.value = keep;

  $('#feed').replaceChildren(...(S.events.length ? S.events.slice().reverse().map(e => h('div', {},
    h('span', {class: 't'}, clock(e.at)), h('span', {class: 'k'}, e.kind), h('span', {}, e.agent ? h('b', {}, e.agent + ' ') : null, e.text)))
    : [h('div', {class: 'empty'}, 'Quiet so far.')]));
  $('#git').textContent = S.git;
  renderSettings();
}

let settingsEditing = false;
function renderSettings() {
  if (settingsEditing) return;
  const rows = Object.entries(S.settings).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => {
    const input = h('input', {class: 'in mono', value: v == null ? '' : v, onfocus: () => settingsEditing = true, onblur: () => setTimeout(() => settingsEditing = false, 300)});
    const glob = h('input', {type: 'checkbox', style: 'accent-color:var(--cyan)'});
    return h('tr', {}, h('td', {class: 'mono'}, k), h('td', {}, input),
      h('td', {}, h('div', {style: 'display:flex;gap:8px;align-items:center;white-space:nowrap'}, h('label', {class: 'muted', style: 'font-size:12.5px'}, glob, ' every repo'),
        btn('Save', () => { settingsEditing = false; run(['settings', ...(glob.checked ? ['--global'] : []), k, input.value]); }))));
  });
  const nk = h('input', {class: 'in mono', placeholder: 'new key'}), nv = h('input', {class: 'in mono', placeholder: 'value'});
  rows.push(h('tr', {}, h('td', {}, nk), h('td', {}, nv), h('td', {}, btn('Add', () => nk.value && run(['settings', nk.value, nv.value])))));
  $('#settings').replaceChildren(...rows);
}

function renderCommands() {
  $('#commands').replaceChildren(...schema.map(c => {
    const inputs = [];
    const fields = c.args.map(a => {
      let el;
      if (a.kind === 'flag') el = h('input', {type: 'checkbox'});
      else if (a.choices) el = h('select', {class: 'in'}, a.required ? null : h('option', {value: ''}, '(none)'), ...a.choices.map(x => h('option', {value: x}, x)));
      else if (a.kind === 'list') el = h('textarea', {class: 'in', placeholder: 'one per line'});
      else el = h('input', {class: 'in', type: a.int ? 'number' : 'text'});
      inputs.push([a, el]);
      return h('div', {class: 'field'}, h('span', {class: 'lbl'}, (a.flag || a.dest) + (a.required ? ' *' : '')), el, a.help ? h('span', {class: 'help'}, a.help) : null);
    });
    const go = () => {
      const argv = [c.name];
      for (const [a, el] of inputs) {
        if (a.kind === 'flag') { if (el.checked) argv.push(a.flag); continue; }
        const vals = a.kind === 'list' ? el.value.split('\n').map(s => s.trim()).filter(Boolean) : (el.value.trim() ? [el.value.trim()] : []);
        if (!vals.length) { if (a.required) { toast(a.dest + ' is required'); return; } continue; }
        if (a.flag) for (const v of vals) argv.push(a.flag, v); else argv.push(...vals);
      }
      if (c.name === 'do' && !argv.includes('--yes')) argv.push('--yes');
      run(argv);
    };
    return h('details', {class: 'cmd'}, h('summary', {}, h('b', {}, c.name), h('span', {class: 'muted'}, c.help || '')),
      h('div', {class: 'body'}, ...fields, h('div', {}, h('button', {class: 'btn go', onclick: go}, 'Run braid ' + c.name))));
  }));
}

async function renderJobs() {
  const jobs = await api('/api/jobs');
  $('#jobs').replaceChildren(...(jobs.length ? jobs.slice().reverse().map(j => h('div', {style: 'display:flex;gap:10px;align-items:center'},
    h('span', {class: 'dim mono'}, clock(j.started)), h('span', {class: 'mono', style: 'flex:1'}, 'braid ' + j.argv.join(' ')),
    j.rc == null ? tag('running') : j.rc === 0 ? tag('done') : tag('failed'), btn('Output', () => openJob(j.id, j.argv), 'ghost')))
    : [h('div', {class: 'empty'}, 'Nothing run from here yet.')]));
}

// ---------- wiring ----------
for (const b of document.querySelectorAll('[data-run]')) b.onclick = () => run(b.dataset.run, {confirm: b.dataset.confirm});
for (const b of document.querySelectorAll('#nav button')) b.onclick = () => {
  for (const x of document.querySelectorAll('#nav button')) x.classList.toggle('on', x === b);
  for (const t of ['home', 'commands', 'settings', 'history']) $('#tab-' + t).hidden = t !== b.dataset.tab;
  if (b.dataset.tab === 'history') renderJobs();
};
for (const b of document.querySelectorAll('[data-mode]')) b.onclick = () => {
  mode = b.dataset.mode;
  for (const x of document.querySelectorAll('[data-mode]')) x.classList.toggle('on', x === b);
  $('#ask-go').textContent = mode === 'do' ? 'Plan it' : 'Start agents';
  $('#ask').placeholder = mode === 'do' ? 'What should we build? e.g. add login with Google and a settings page' : 'One task per line (Shift+Enter for a new line)';
  $('#opt-max').hidden = $('#opt-push-label').hidden = mode !== 'do';
};
$('#opts-toggle').onclick = () => { $('#opts').hidden = !$('#opts').hidden; };
$('#more-toggle').onclick = () => { const m = $('#more-bar'); m.style.display = m.style.display === 'none' ? 'flex' : 'none'; };
const grow = () => { const t = $('#ask'); t.style.height = 'auto'; t.style.height = Math.min(t.scrollHeight, 180) + 'px'; };
$('#ask').oninput = grow;
$('#ask').onkeydown = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('#ask-go').click(); } };
$('#ask-go').onclick = () => {
  const text = $('#ask').value.trim(); if (!text) return toast(mode === 'do' ? 'Say what to build first' : 'Add at least one task');
  const base = $('#opt-base').value.trim();
  if (mode === 'do') {
    const argv = ['do', '--yes', ...(base ? ['--base', base] : [])];
    if ($('#opt-max').value) argv.push('--max-agents', $('#opt-max').value);
    if ($('#opt-push').checked) argv.push('--push');
    run([...argv, text]);
  } else run(['start', ...(base ? ['--base', base] : []), ...text.split('\n').map(s => s.trim()).filter(Boolean)]);
  $('#ask').value = ''; grow();
};
$('#watcher').onclick = () => S && run(['daemon', S.daemon ? 'stop' : 'start']);
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
  catch (e) { $('#where').textContent = 'lost contact: ' + e.message; }
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
