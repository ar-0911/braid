"""`braid dashboard`: steer every agent from one web page on your machine instead of the command line.

The page shows what `braid status`, `braid feed`, `braid chat`, `braid plans` and `braid approvals` show, live,
with buttons for the everyday actions (start, plan, review, land, vote, approve, resume, stop, settings). Every
other braid command has a form built from the CLI's own argument parser, so nothing the CLI can do is missing
here, and new commands show up on their own.

Each action runs the real `braid` command in the repo, exactly as if you had typed it, and the page shows its
output. The server listens on 127.0.0.1 only, and every request needs the secret token printed with the URL.
"""
import argparse
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import gitutil
from .store import Store

HIDDEN = {"merge-driver", "hook", "mcp", "dashboard"}  # internal plumbing, or this page itself
MAX_OUTPUT = 200_000
# `python -m braid` would put the repo first on sys.path, so a repo file such as email.py would shadow the stdlib
RUN_BRAID = "import sys; del sys.path[0]; sys.argv[0] = 'braid'; from braid.cli import main; main()"
MAX_DIFF = 400_000


def refused(argv):
    """Why the page won't run argv, or None. Commands that never end are pointless here: the page is live."""
    if not argv:
        return "no command"
    cmd, rest = argv[0], argv[1:]
    if cmd in HIDDEN:
        return f"`braid {cmd}` isn't something to run from the dashboard"
    if cmd == "status" and "--live" in rest:
        return "the dashboard is already live; plain `status` works"
    if cmd == "feed" and ({"-f", "--follow"} & set(rest)):
        return "the activity panel already follows the feed"
    if cmd == "watch":
        return "use `daemon start` for the watcher; `watch` runs in the foreground forever"
    if cmd == "approvals" and rest[:1] == ["serve"]:
        return "the watcher serves review pages; `approvals serve` runs forever"
    return None


# ---------- commands: a form for every CLI command, read from argparse itself ----------

def command_schema():
    from .cli import build_parser
    parser, _ = build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    helps = {c.dest: c.help for c in sub._choices_actions}
    out = []
    for name, p in sub.choices.items():
        if name in HIDDEN:
            continue
        args = []
        for a in p._actions:
            if isinstance(a, argparse._HelpAction) or a.help == argparse.SUPPRESS:
                continue
            kind = ("flag" if isinstance(a, (argparse._StoreTrueAction, argparse._StoreFalseAction))
                    else "list" if a.nargs in ("+", "*") else "value")
            args.append({"dest": a.dest, "flag": max(a.option_strings, key=len) if a.option_strings else None,
                         "kind": kind, "required": bool(a.required) or (not a.option_strings and a.nargs not in ("?", "*")),
                         "choices": list(a.choices) if a.choices else None, "help": a.help or "",
                         "int": a.type is int})
        out.append({"name": name, "help": helps.get(name, ""), "args": args})
    return out


# ---------- jobs: each action is the real braid command, run in the background ----------

class Jobs:
    def __init__(self, repo):
        self.repo, self.jobs, self.lock, self.next = repo, {}, threading.Lock(), 1

    def run(self, argv):
        pkg_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # this braid, even if not installed
        path = os.pathsep.join(p for p in (pkg_parent, os.environ.get("PYTHONPATH")) if p)
        env = {**os.environ, "NO_COLOR": "1", "PYTHONPATH": path}
        env.pop("BRAID_AGENT", None)
        proc = subprocess.Popen([sys.executable, "-c", RUN_BRAID, *argv], cwd=self.repo, env=env, text=True,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                start_new_session=True)
        with self.lock:
            jid, self.next = self.next, self.next + 1
            job = self.jobs[jid] = {"id": jid, "argv": argv, "out": "", "rc": None, "started": time.time(),
                                    "proc": proc}
        threading.Thread(target=self._read, args=(job,), daemon=True).start()
        return jid

    def _read(self, job):
        for line in job["proc"].stdout:
            if len(job["out"]) < MAX_OUTPUT:
                job["out"] += line
        job["rc"] = job["proc"].wait()

    def get(self, jid):
        j = self.jobs.get(jid)
        return j and {k: v for k, v in j.items() if k != "proc"}

    def stop(self, jid):
        j = self.jobs.get(jid)
        if j and j["rc"] is None:
            j["proc"].terminate()
        return bool(j)

    def recent(self):
        return [self.get(j) for j in sorted(self.jobs)[-20:]]


# ---------- state: everything the page shows, in one read ----------

def state(repo):
    from . import approve, land
    from .cli import daemon_pid, needs_attention
    store = Store(repo)
    try:
        base = store.base_branch()
        leases = store.leases()
        agents = []
        for a in store.agents():
            ab = store.agent_base(a)
            ahead = None
            if a["status"] not in ("landed", "done") and gitutil.rev(ab, cwd=repo) and gitutil.rev(a["branch"], cwd=repo):
                ahead = int(gitutil.out("rev-list", "--count", f"{ab}..{a['branch']}", cwd=repo) or 0)
            running = bool(a.get("pid")) and store.process_alive(a)
            gate = land.review_gate(store, a) if a["status"] == "ready" else None
            agents.append({
                "name": a["name"], "status": a["status"], "task": a["task"], "branch": a["branch"], "base": ab,
                "worktree": a["worktree"], "running": running, "interactive": not a.get("pid"), "ahead": ahead,
                "owns": [{"path": l["path"], "kind": l["kind"]} for l in leases if l["agent"] == a["name"]],
                "intents": [i["description"] for i in store.intents(a["name"])][-3:],
                "gate": None if gate is None else {"ok": gate[0], "why": gate[1]},
                "needs": needs_attention(store, a) if a["status"] in ("exited", "blocked") and not running else None,
            })
        live = {a["name"] for a in store.live_agents()}
        risks = [r for r in store.risks() if r["a"] in live and (r["b"] in live or r["b"].startswith("@"))]
        plans = [{"id": p["id"], "goal": p["goal"], "base": p["base"], "status": p["status"],
                  "tasks": [{"id": t["id"], "title": t["title"], "status": t["status"],
                             "agent": t["agent"], "deps": t["depends_on"]} for t in store.plan_tasks(p["id"])]}
                 for p in store.plans()][-8:]
        approve.ensure(store)
        approvals = []
        for a in approve.all_approvals(store)[-15:]:
            r = a["report"]
            approvals.append({"id": a["id"], "code": a["code"], "status": a["status"], "agent": a["agent"],
                              "title": r.get("title", ""), "summary": r.get("summary", ""),
                              "added": r.get("added", 0), "removed": r.get("removed", 0),
                              "tests": bool(r.get("tests", {}).get("passed")), "risk": r.get("risk", "")})
        return {
            "repo": str(repo), "name": os.path.basename(str(repo)), "base": base,
            "daemon": daemon_pid(store), "agents": agents, "risks": risks,
            "decisions": [d for d in store.decisions() if d["status"] in ("proposed", "escalated")],
            "plans": plans, "approvals": approvals, "approvals_on": approve.required(store),
            "events": store.events(80), "notes": store.notes()[-60:],
            "settings": store.all_cfg(),
            "git": gitutil.out("status", "--short", "--branch", cwd=repo),
            "at": time.time(),
        }
    finally:
        store.close()


def diff_for(repo, kind, ref):
    from . import approve
    store = Store(repo)
    try:
        if kind == "approval":
            a = approve.get(store, ref)
            return a["diff"] if a else None
        a = store.agent(ref)
        if not a:
            return None
        ab = store.agent_base(a)
        snap = store.snapshot(a["name"]) or a["branch"]  # includes uncommitted edits when the watcher has seen them
        rc, out = gitutil.git("diff", "--stat", "--patch", f"{ab}...{snap}", cwd=repo, check=False)
        return out if rc == 0 else gitutil.out("diff", f"{ab}...{a['branch']}", cwd=repo)
    finally:
        store.close()


# ---------- the server ----------

def make_handler(repo, token, jobs):
    from .dashboard_page import PAGE

    class Handler(BaseHTTPRequestHandler):
        server_version = "braid"

        def log_message(self, fmt, *args):
            pass

        def _send(self, code, body, ctype="application/json", headers=()):
            data = (body if isinstance(body, str) else json.dumps(body, default=str)).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            for k, v in headers:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _authed(self, query):
            given = (self.headers.get("X-Braid-Token") or query.get("t", [""])[0]
                     or _cookie(self.headers.get("Cookie", ""), "braid_dash"))
            return bool(given) and secrets.compare_digest(given, token)

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(u.query)
            if u.path == "/favicon.ico":
                return self._send(204, "")
            if not self._authed(q):
                return self._send(403, "<h1>braid dashboard</h1><p>Open the link `braid dashboard` printed; "
                                       "it carries the key.</p>", "text/html")
            if u.path == "/":
                return self._send(200, PAGE.replace("__TOKEN__", token), "text/html",
                                  [("Set-Cookie", f"braid_dash={token}; HttpOnly; SameSite=Strict; Path=/")])
            try:
                if u.path == "/api/state":
                    return self._send(200, state(repo))
                if u.path == "/api/commands":
                    return self._send(200, command_schema())
                if u.path == "/api/jobs":
                    return self._send(200, jobs.recent())
                if u.path.startswith("/api/jobs/"):
                    j = jobs.get(int(u.path.rsplit("/", 1)[1]))
                    return self._send(200 if j else 404, j or {"error": "no such job"})
                if u.path == "/api/diff":
                    d = diff_for(repo, q.get("kind", ["agent"])[0], q.get("ref", [""])[0])
                    if d is None:
                        return self._send(404, {"error": "not found"})
                    return self._send(200, {"diff": d[:MAX_DIFF], "cut": len(d) > MAX_DIFF})
            except Exception as e:  # keep the page alive; show the reason
                return self._send(500, {"error": f"{type(e).__name__}: {e}"})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            u = urllib.parse.urlparse(self.path)
            # POSTs need the header, not the cookie, so another site can't make your browser act here
            if not secrets.compare_digest(self.headers.get("X-Braid-Token") or "", token):
                return self._send(403, {"error": "missing key"})
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(min(n, 100_000)) or b"{}")
            except json.JSONDecodeError:
                return self._send(400, {"error": "bad json"})
            if u.path == "/api/run":
                argv = body.get("argv")
                if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
                    return self._send(400, {"error": "argv must be a list of strings"})
                why = refused(argv)
                if why:
                    return self._send(400, {"error": why})
                return self._send(200, {"job": jobs.run(argv)})
            if u.path.startswith("/api/jobs/") and u.path.endswith("/stop") and u.path.split("/")[3].isdigit():
                return self._send(200, {"ok": jobs.stop(int(u.path.split("/")[3]))})
            self._send(404, {"error": "not found"})

    return Handler


def _cookie(header, name):
    for part in header.split(";"):
        k, _, v = part.strip().partition("=")
        if k == name:
            return v
    return ""


def serve(repo, port=8770, bind="127.0.0.1", open_browser=True, token=None):
    token = token or secrets.token_urlsafe(18)
    jobs = Jobs(repo)
    try:
        httpd = ThreadingHTTPServer((bind, port), make_handler(repo, token, jobs))
    except OSError:
        httpd = ThreadingHTTPServer((bind, 0), make_handler(repo, token, jobs))  # port taken: any free one
    url = f"http://{'127.0.0.1' if bind in ('0.0.0.0', '') else bind}:{httpd.server_address[1]}/?t={token}"
    return httpd, url


def run(repo, port, bind, open_browser):
    httpd, url = serve(repo, port, bind)
    print(f"braid dashboard for {repo}\n  {url}\n(ctrl-c to stop; the agents and the watcher keep running)",
          flush=True)
    if open_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
