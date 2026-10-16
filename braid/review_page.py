"""The review page: summary, impact, tests and the full diff, with Land it / Send back buttons.

`braid approvals serve` (and the watcher, when approvals are on) serves it from your machine. Links carry a
secret per approval, so only someone with the message can open or decide it. To open it from your phone, either
set approve.public_url to an address that reaches this port (Tailscale, ngrok, your own proxy) or set
approve.tunnel to cloudflared, which opens a free https://….trycloudflare.com tunnel with no account.
"""
import html
import re
import secrets
import shutil
import subprocess
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import approve

HEARTBEAT = 30  # seconds a server stays "alive" in the shared memory without refreshing


def public_url(store):
    if store.cfg("approve.public_url"):
        return store.cfg("approve.public_url").rstrip("/")
    if time.time() - float(store.get_meta("approve.server_at", "0")) > HEARTBEAT:
        return ""  # nothing is serving the page
    return store.get_meta("approve.live_url", "") or store.get_meta("approve.local_url", "")


# ------------------------------------------------------------------ rendering

CSS = """
:root{--bg:#fff;--fg:#1d2330;--mut:#5d6677;--line:#e3e6ec;--card:#f6f7f9;--add:#e6f6ea;--addfg:#1a6b34;
--del:#fdecec;--delfg:#a12a2a;--hunk:#eef2fb;--ok:#1a7f45;--bad:#c0392b;--warn:#b7791f;--acc:#2f5bea}
@media (prefers-color-scheme:dark){:root{--bg:#12151b;--fg:#e6e9ef;--mut:#9aa3b2;--line:#2a303b;--card:#1a1e26;
--add:#12301d;--addfg:#7ee2a1;--del:#3a1717;--delfg:#ff9c9c;--hunk:#1b2436;--ok:#3ccf7c;--bad:#ff6b5b;
--warn:#f0b44c;--acc:#7c9bff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
main{max-width:980px;margin:0 auto;padding:16px 16px 120px}h1{font-size:21px;margin:4px 0 6px;line-height:1.3}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--mut);margin:26px 0 8px}
.meta{color:var(--mut);font-size:13px}.chips{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}
.chip{border:1px solid var(--line);border-radius:999px;padding:2px 10px;font-size:13px;white-space:nowrap}
.ok{color:var(--ok);border-color:var(--ok)}.bad{color:var(--bad);border-color:var(--bad)}
.warn{color:var(--warn);border-color:var(--warn)}.card{background:var(--card);border:1px solid var(--line);
border-radius:10px;padding:12px 14px}table{border-collapse:collapse;width:100%;font-size:14px}
td,th{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--mut);font-weight:500;font-size:12px}td.n{text-align:right;white-space:nowrap;
font-variant-numeric:tabular-nums}.a{color:var(--addfg)}.d{color:var(--delfg)}code,pre{
font:12.5px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
details{border:1px solid var(--line);border-radius:10px;margin:8px 0;overflow:hidden}
summary{cursor:pointer;padding:9px 12px;background:var(--card);font-size:14px;display:flex;gap:8px;
justify-content:space-between}summary span.p{overflow-wrap:anywhere}
.diff{overflow-x:auto;margin:0;padding:6px 0;font:12.5px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}.diff div{padding:0 12px;white-space:pre;min-height:1.45em}
.diff .add{background:var(--add);color:var(--addfg)}.diff .del{background:var(--del);color:var(--delfg)}
.diff .hk{background:var(--hunk);color:var(--mut)}pre.out{white-space:pre-wrap;overflow-wrap:anywhere;
max-height:340px;overflow:auto;margin:8px 0 0}.bar{position:fixed;left:0;right:0;bottom:0;
background:var(--bg);border-top:1px solid var(--line);padding:10px 16px}.bar form{max-width:980px;
margin:0 auto;display:flex;gap:8px;align-items:center}.bar input[type=text]{flex:1;min-width:0;padding:10px;
border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg);font-size:15px}
button{border:0;border-radius:8px;padding:11px 16px;font-size:15px;font-weight:600;cursor:pointer}
.yes{background:var(--ok);color:#fff}.no{background:transparent;color:var(--bad);border:1px solid var(--bad)}
.state{font-weight:600}a{color:var(--acc)}ul{margin:6px 0;padding-left:20px}
"""


def _e(x):
    return html.escape(str(x if x is not None else ""))


def _diff_html(diff, max_lines):
    """Split a unified diff by file and color it. Returns {path: html}."""
    files, cur, count = {}, None, {}
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/(.*) b/(.*)", line)
            cur = m.group(2) if m else line
            files[cur], count[cur] = [], 0
            continue
        if cur is None or line.startswith(("index ", "--- ", "+++ ", "new file", "deleted file", "similarity",
                                           "rename ", "old mode", "new mode")):
            continue
        count[cur] += 1
        if count[cur] > max_lines:
            if count[cur] == max_lines + 1:
                files[cur].append('<div class="hk">… more lines in the raw diff</div>')
            continue
        cls = "add" if line.startswith("+") else "del" if line.startswith("-") else "hk" if line.startswith("@@") else ""
        files[cur].append(f'<div class="{cls}">{_e(line)}</div>' if cls else f"<div>{_e(line)}</div>")
    return {k: "".join(v) for k, v in files.items()}


def _tests_chip(t):
    if not t["ran"]:
        return '<span class="chip warn">no tests configured</span>'
    n = f" · {t['counts']['passed']} tests" if t.get("counts") else ""
    return f'<span class="chip ok">tests passed{n}</span>' if t["passed"] else '<span class="chip bad">tests failed</span>'


def _who(r):
    return "whole run" if r.get("agents") is not None and r["agent"].startswith("run:") else r["agent"]


def _anchor(name):
    return "agent-" + re.sub(r"[^A-Za-z0-9_-]", "-", name)


def _email_agents(r, url, font):
    """For a whole run: one row per agent, each linking to its own section of the review page."""
    if not r.get("agents"):
        return ""
    rows = "".join(
        f"<tr><td style='padding:10px 0;border-top:1px solid #e3e6ec;font-family:{font};font-size:14px;"
        f"line-height:1.4'><a href='{_e(url)}#{_anchor(g['name'])}' style='color:#1d4ed8;font-weight:600;"
        f"text-decoration:none'>{_e(g['name'])}</a>"
        f" <span style='color:#1a7f45'>+{g['added']}</span> <span style='color:#c0392b'>-{g['removed']}</span>"
        f"<div style='color:#5d6677'>{_e((g['summary'] or g['task'])[:160])}</div></td></tr>"
        for g in r["agents"])
    return (f"<tr><td style='padding:18px 24px 0;font-family:{font};color:#1d2330;font-size:14px;"
            f"font-weight:700'>{len(r['agents'])} agent{'s' * (len(r['agents']) != 1)} in this run</td></tr>"
            f"<tr><td style='padding:4px 24px 0'><table role='presentation' width='100%' cellpadding='0' "
            f"cellspacing='0'>{rows}</table></td></tr>")


def _page_agents(r):
    """For a whole run: a section per agent with its task, summary and its own diff."""
    if not r.get("agents"):
        return ""
    out = [f"<h2>Agents in this run ({len(r['agents'])})</h2>"]
    for g in r["agents"]:
        n = len(g["files"])
        diffs = "".join(f"<div class='hk'>{_e(p)}</div>{h}" for p, h in _diff_html(g["diff"], 400).items())
        out.append(
            f"<div class='card' id='{_anchor(g['name'])}'><b>{_e(g['name'])}</b> "
            f"<span class='meta'>{n} file{'s' * (n != 1)} · <span class='a'>+{g['added']}</span> "
            f"<span class='d'>-{g['removed']}</span></span>"
            f"<div class='meta' style='margin-top:4px'>Task: {_e(g['task'])}</div>"
            + (f"<div style='margin-top:6px'>{_e(g['summary'])}</div>" if g["summary"] else "")
            + (f"<details><summary>Its changes</summary><div class='diff'>{diffs}</div></details>" if diffs else "")
            + "</div>")
    out.append("<h2>The whole run</h2>")
    return "".join(out)


def render_email_card(a, url):
    """The approval email when there is a review page to link to: a short card and one button.

    Inline styles only, since mail clients drop most stylesheets."""
    r, t = a["report"], a["report"]["tests"]
    tests = ("no tests configured" if not t["ran"] else
             ("tests passed" + (f" ({t['counts']['passed']})" if t.get("counts") else "")) if t["passed"]
             else "tests failed")
    risk_color = {"low": "#1a7f45", "medium": "#b7791f", "high": "#c0392b"}.get(r["risk"], "#5d6677")
    n = len(r["files"])
    facts = (f"<span style='color:{'#1a7f45' if t['passed'] or not t['ran'] else '#c0392b'}'>{_e(tests)}</span>"
             f" &middot; <span style='color:{risk_color}'>{_e(r['risk'])} risk</span>"
             f" &middot; {n} file{'s' * (n != 1)} <span style='color:#1a7f45'>+{r['added']}</span>"
             f" <span style='color:#c0392b'>-{r['removed']}</span>")
    font = "-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif"
    return (
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'></head>"
        f"<body style='margin:0;padding:0;background:#f4f5f7'>"
        f"<table role='presentation' width='100%' cellpadding='0' cellspacing='0' style='background:#f4f5f7'>"
        f"<tr><td align='center' style='padding:24px 12px'>"
        f"<table role='presentation' width='100%' cellpadding='0' cellspacing='0' style='max-width:520px;"
        f"background:#ffffff;border-radius:12px;border:1px solid #e3e6ec'>"
        f"<tr><td style='padding:24px 24px 8px;font-family:{font};color:#5d6677;font-size:13px'>"
        f"braid &middot; {_e(_who(r))} &rarr; {_e(r['base'])}</td></tr>"
        f"<tr><td style='padding:0 24px;font-family:{font};color:#1d2330;font-size:20px;font-weight:700;"
        f"line-height:1.3'>{_e(r['title'])}</td></tr>"
        f"<tr><td style='padding:10px 24px 0;font-family:{font};font-size:14px'>{facts}</td></tr>"
        f"<tr><td style='padding:14px 24px 0;font-family:{font};color:#1d2330;font-size:15px;line-height:1.5'>"
        f"{_e(r['summary'])}</td></tr>"
        f"{_email_agents(r, url, font)}"
        f"<tr><td style='padding:24px'><a href='{_e(url)}' style='display:block;background:#1a7f45;"
        f"color:#ffffff;text-align:center;padding:14px 18px;border-radius:8px;text-decoration:none;"
        f"font-family:{font};font-size:16px;font-weight:600'>"
        f"{'Review the whole run and land' if r.get('agents') else 'Review and land'}</a></td></tr>"
        f"<tr><td style='padding:0 24px 24px;font-family:{font};color:#5d6677;font-size:13px;line-height:1.5'>"
        f"The page shows what changed, how it affects you, the tests and the full diff. "
        f"Or just reply <b>yes</b> to land it, or <b>no</b> and a reason to send it back.</td></tr>"
        f"</table></td></tr></table></body></html>")


def render(store, a, mode="web", url="", page_id=None):
    """mode: web (interactive), static (a saved file), email (an HTML email body).
    page_id is the approval's name in page links (the worker names it differently)."""
    page_id = page_id or a["id"]
    r = a["report"]
    risk_cls = {"low": "ok", "medium": "warn", "high": "bad"}.get(r["risk"], "")
    status = a["status"]
    q = f"?t={urllib.parse.quote(a['token'])}"
    parts = [f"<!doctype html><html><head><meta charset='utf-8'>"
             f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
             f"<title>braid #{a['id']}: {_e(r['title'])}</title><style>{CSS}</style>"]
    if mode == "web" and status == "approved":
        parts.append("<meta http-equiv='refresh' content='3'>")  # landing in progress
    parts.append("</head><body><main>")
    parts.append(f"<div class='meta'>braid #{a['id']} · {_e(_who(r))} → {_e(r['base'])} · "
                 f"{time.strftime('%d %b %H:%M', time.localtime(a['created_at']))}</div>")
    parts.append(f"<h1>{_e(r['title'])}</h1>")
    chips = [_tests_chip(r["tests"]), f"<span class='chip {risk_cls}'>{_e(r['risk'])} risk</span>",
             f"<span class='chip'>{len(r['files'])} file{'s' * (len(r['files']) != 1)} · <span class='a'>+{r['added']}</span> "
             f"<span class='d'>-{r['removed']}</span></span>"]
    chips += [f"<span class='chip ok'>reviewed by {_e(x)}</span>" for x in r["reviewers"]]
    if r.get("resolution"):
        chips.append("<span class='chip warn'>conflict auto-resolved</span>")
    if status != "pending":
        cls = {"landed": "ok", "approved": "ok", "rejected": "bad", "failed": "bad"}.get(status, "")
        chips.append(f"<span class='chip state {cls}'>{_e(status)}"
                     f"{' by ' + _e(a['decided_by']) if a['decided_by'] else ''}</span>")
    parts.append(f"<div class='chips'>{''.join(chips)}</div>")
    if status != "pending" and (a.get("result") or a.get("comment")):
        parts.append(f"<div class='card'>{_e(a.get('result') or '')}"
                     f"{'<br>Reason: ' + _e(a['comment']) if a.get('comment') else ''}</div>")

    parts.append(f"<h2>What changed</h2><div class='card'>{_e(r['summary'])}"
                 f"<div class='meta' style='margin-top:6px'>Task: {_e(r['task'])}</div></div>")
    parts.append(_page_agents(r))
    parts.append(f"<h2>How it affects you</h2><div class='card'>{_e(r['impact'])}")
    users = [e for e in r["entities"] if e.get("used_by")]
    if users:
        parts.append("<ul>" + "".join(
            f"<li><code>{_e(e['name'])}</code> ({_e(e['change'])}) is used in "
            f"{', '.join('<code>' + _e(u) + '</code>' for u in e['used_by'][:6])}</li>" for e in users[:12]) + "</ul>")
    parts.append("</div>")
    if r.get("resolution"):
        parts.append(f"<h2>Conflict resolution</h2><div class='card'>{_e(r['resolution'])}</div>")

    t = r["tests"]
    parts.append("<h2>Tests</h2><div class='card'>")
    if t["ran"]:
        parts.append(f"{'Passed' if t['passed'] else 'Failed'} on the merged result: <code>{_e(t['command'])}</code>")
        if t["output"].strip():
            parts.append(f"<details><summary>Output</summary><pre class='out'>{_e(t['output'])}</pre></details>")
    else:
        parts.append("No test command is configured, so nothing was run. Set one with "
                     "<code>braid settings test.command \"pytest -q\"</code>.")
    parts.append("</div>")
    if r["reviews"]:
        parts.append("<h2>Reviews</h2><div class='card'><ul>" + "".join(
            f"<li><b>{_e(v['reviewer'])}</b>: {_e(v['verdict'])}. {_e(v['comment'])}</li>" for v in r["reviews"])
            + "</ul></div>")

    if mode == "email" and url:
        return render_email_card(a, url)
    if mode == "email":  # no page to link to, so the email carries the details itself
        parts.append("<h2>Files</h2><table>" + "".join(
            f"<tr><td><code>{_e(f['path'])}</code><div class='meta'>{_e(f['note'])}</div></td>"
            f"<td class='n'><span class='a'>+{f['added']}</span> <span class='d'>-{f['removed']}</span></td></tr>"
            for f in r["files"]) + "</table>")
        if r["diff_lines"] <= 300:
            parts.append("<h2>Diff</h2>" + "".join(
                f"<details open><summary><span class='p'>{_e(p)}</span></summary><div class='diff'>{h}</div></details>"
                for p, h in _diff_html(a["diff"], 300).items()))
        if url:
            parts.append(f"<p style='margin-top:24px'><a href='{_e(url)}' style='background:#1a7f45;color:#fff;"
                         f"padding:12px 18px;border-radius:8px;text-decoration:none;font-weight:600'>"
                         f"Review and land</a></p>")
        parts.append(f"<p class='meta'>Or reply <b>YES</b> to land it, or <b>NO</b> and a reason to send it "
                     f"back to {_e(r['agent'])}.</p></main></body></html>")
        return "".join(parts)

    diffs = _diff_html(a["diff"], 1500)
    parts.append("<h2>Files</h2>")
    many = len(r["files"]) > 8
    for f in r["files"]:
        note = f"<div class='meta'>{_e(f['note'])}</div>" if f.get("note") else ""
        body = diffs.get(f["path"].split(" => ")[-1], "") or "<div class='hk'>binary or renamed</div>"
        parts.append(f"<details{'' if many else ' open'}><summary><span class='p'><code>{_e(f['path'])}</code>"
                     f"{note}</span><span class='n'><span class='a'>+{f['added']}</span> "
                     f"<span class='d'>-{f['removed']}</span></span></summary><div class='diff'>{body}</div></details>")
    if r.get("commits"):
        parts.append("<h2>Commits</h2><div class='card'><code>" + "<br>".join(_e(c) for c in r["commits"])
                     + "</code></div>")
    if mode == "web":
        parts.append(f"<p class='meta'><a href='/a/{page_id}/raw.diff{q}'>Raw diff</a></p>")
    if mode == "web" and status == "pending":
        parts.append(f"<div class='bar'><form method='post' action='/a/{page_id}/decide'>"
                     f"<input type='hidden' name='t' value='{_e(a['token'])}'>"
                     f"<input type='text' name='comment' placeholder='Reason, if sending back'>"
                     f"<button class='no' name='action' value='reject'>Send back</button>"
                     f"<button class='yes' name='action' value='approve'>Land it</button></form></div>")
    elif mode == "static" and status == "pending":
        parts.append(f"<p class='meta'>Reply <b>YES {a['code']}</b> to the message to land it, or run "
                     f"<code>braid approve {a['id']}</code>.</p>")
    parts.append("</main></body></html>")
    return "".join(parts)


# ------------------------------------------------------------------ server

def make_handler(repo):
    from .store import Store

    class Handler(BaseHTTPRequestHandler):
        server_version = "braid"

        def log_message(self, fmt, *args):
            pass

        def _send(self, code, body, ctype="text/html; charset=utf-8", headers=()):
            data = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Robots-Tag", "noindex")
            for k, v in headers:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _approval(self, store, aid, token):
            a = approve.get(store, aid) if aid.isdigit() else None
            if not a or not token or not secrets.compare_digest(a["token"], token):
                self._send(404, "<h1>Not found</h1>")
                return None
            return a

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            token = urllib.parse.parse_qs(u.query).get("t", [""])[0]
            if u.path == "/health":
                return self._send(200, "ok", "text/plain")
            m = re.fullmatch(r"/a/(\d+)(/raw\.diff)?", u.path)
            if not m:
                return self._send(404, "<h1>Not found</h1>")
            store = Store(repo)
            try:
                a = self._approval(store, m.group(1), token)
                if not a:
                    return
                if m.group(2):
                    return self._send(200, a["diff"], "text/plain; charset=utf-8")
                self._send(200, render(store, a, mode="web"))
            finally:
                store.close()

        def do_POST(self):
            m = re.fullmatch(r"/a/(\d+)/decide", urllib.parse.urlparse(self.path).path)
            if not m:
                return self._send(404, "<h1>Not found</h1>")
            n = int(self.headers.get("Content-Length") or 0)
            form = urllib.parse.parse_qs(self.rfile.read(min(n, 20000)).decode(errors="replace"))
            token, action = form.get("t", [""])[0], form.get("action", [""])[0]
            comment = form.get("comment", [""])[0].strip()[:1000]
            store = Store(repo)
            try:
                a = self._approval(store, m.group(1), token)
                if not a:
                    return
                if action in ("approve", "reject") and a["status"] == "pending":
                    approve.decide(store, a["id"], action == "approve", "web", comment, apply=False)
                    if action == "approve":
                        threading.Thread(target=_apply_in_background, args=(repo, a["id"]), daemon=True).start()
            finally:
                store.close()
            self._send(303, "", headers=[("Location", f"/a/{m.group(1)}?t={urllib.parse.quote(token)}")])

    return Handler


def _apply_in_background(repo, aid):
    from . import notify
    from .store import Store
    store = Store(repo)
    try:
        a, message = approve.apply_approved(store, aid)
        notify.send_text(store, f"braid #{aid}: {message}")
    except Exception as e:
        approve._set(store, aid, status="failed", result=f"landing failed: {e}")
    finally:
        store.close()


class ReviewServer:
    """The review page server, its heartbeat, and the optional tunnel."""

    def __init__(self, store, port=None, bind=None, tunnel=None):
        self.repo = store.repo
        self.port = int(port or store.cfg("approve.port"))
        self.bind = bind or store.cfg("approve.bind")
        self.tunnel = store.cfg("approve.tunnel") if tunnel is None else tunnel
        self.httpd, self.proc, self.stop = None, None, threading.Event()

    def start(self):
        from .store import Store
        self.httpd = ThreadingHTTPServer((self.bind, self.port), make_handler(self.repo))
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        store = Store(self.repo)
        host = "localhost" if self.bind in ("127.0.0.1", "0.0.0.0", "") else self.bind
        store.set_meta("approve.local_url", f"http://{host}:{self.port}")
        store.set_meta("approve.live_url", "")
        if self.tunnel:
            store.set_meta("approve.live_url", self._open_tunnel() or "")
        store.set_meta("approve.server_at", time.time())
        store.close()
        threading.Thread(target=self._beat, daemon=True).start()
        return self

    def url(self):
        from .store import Store
        store = Store(self.repo)
        try:
            return public_url(store)
        finally:
            store.close()

    def _beat(self):
        from .store import Store
        while not self.stop.wait(HEARTBEAT / 3):
            store = Store(self.repo)
            store.set_meta("approve.server_at", time.time())
            store.close()

    def _open_tunnel(self):
        if self.tunnel != "cloudflared" or not shutil.which("cloudflared"):
            return None
        self.proc = subprocess.Popen(["cloudflared", "tunnel", "--no-autoupdate", "--url",
                                      f"http://127.0.0.1:{self.port}"], stdout=subprocess.DEVNULL,
                                     stderr=subprocess.PIPE, text=True, stdin=subprocess.DEVNULL)
        deadline = time.time() + 30
        found = []

        def read():
            for line in self.proc.stderr:
                m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
                if m and not found:
                    found.append(m.group(0))
        threading.Thread(target=read, daemon=True).start()
        while time.time() < deadline and not found and self.proc.poll() is None:
            time.sleep(0.2)
        return found[0] if found else None

    def close(self):
        from .store import Store
        self.stop.set()
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
        if self.proc:
            self.proc.terminate()
        store = Store(self.repo)
        store.set_meta("approve.server_at", "0")
        store.close()
