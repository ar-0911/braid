"""Shared memory: one SQLite file in the repo's common git dir, used by every agent and by braid itself."""
import fnmatch
import json
import os
import sqlite3
import time
from pathlib import Path

from . import gitutil

SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    name TEXT PRIMARY KEY,
    branch TEXT NOT NULL,
    worktree TEXT NOT NULL,
    task TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',  -- active | ready | landed | blocked | exited | paused | done
    pid INTEGER,
    heartbeat REAL,
    created_at REAL,
    ready_at REAL,
    summary TEXT,
    base TEXT                     -- branch this agent starts from and lands on
);
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY,
    goal TEXT NOT NULL,
    base TEXT NOT NULL,
    status TEXT NOT NULL,         -- proposed | running | done | cancelled
    push INTEGER NOT NULL DEFAULT 0,
    at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS plan_tasks (
    plan_id INTEGER NOT NULL,
    id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    files TEXT NOT NULL,          -- JSON list of paths/globs this task owns
    depends_on TEXT NOT NULL,     -- JSON list of task ids
    agent TEXT,
    status TEXT NOT NULL,         -- waiting | running | landed | failed
    seq INTEGER NOT NULL,
    PRIMARY KEY (plan_id, id)
);
CREATE TABLE IF NOT EXISTS intents (
    id INTEGER PRIMARY KEY,
    agent TEXT NOT NULL,
    paths TEXT NOT NULL,
    description TEXT NOT NULL,
    at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS leases (
    agent TEXT NOT NULL,
    path TEXT NOT NULL,
    kind TEXT NOT NULL,           -- soft: signal ownership; hard: other agents' commits are blocked
    expires_at REAL NOT NULL,
    PRIMARY KEY (agent, path)
);
CREATE TABLE IF NOT EXISTS snapshots (
    agent TEXT PRIMARY KEY,
    oid TEXT NOT NULL,
    at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS risks (
    a TEXT NOT NULL,
    b TEXT NOT NULL,              -- another agent, or '@<base>'
    severity TEXT NOT NULL,       -- conflict | overlap
    files TEXT NOT NULL,
    at REAL NOT NULL,
    PRIMARY KEY (a, b)
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY,
    agent TEXT NOT NULL,
    topic TEXT NOT NULL,
    text TEXT NOT NULL,
    to_agent TEXT,                -- NULL means everyone
    at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY,
    agent TEXT NOT NULL,          -- whose work
    reviewer TEXT NOT NULL,
    commit_oid TEXT NOT NULL,     -- the branch head that was reviewed
    verdict TEXT NOT NULL,        -- approve | changes
    comment TEXT NOT NULL,
    at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY,
    agent TEXT NOT NULL,          -- agent being landed
    parties TEXT NOT NULL,        -- JSON list of agents whose work is in the conflict
    files TEXT NOT NULL,
    status TEXT NOT NULL,         -- proposed | accepted | rejected | escalated
    proposal_oid TEXT,
    detail TEXT NOT NULL,
    at REAL NOT NULL,
    decided_at REAL
);
CREATE TABLE IF NOT EXISTS votes (
    decision_id INTEGER NOT NULL,
    agent TEXT NOT NULL,
    vote TEXT NOT NULL,           -- accept | object
    reason TEXT NOT NULL,
    at REAL NOT NULL,
    PRIMARY KEY (decision_id, agent)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    agent TEXT,
    text TEXT NOT NULL,
    at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Defaults for `braid settings`. Values are strings, as typed on the command line.
RUN_PREFIX = "braid-run/"  # staging branches for approve.mode run

DEFAULTS = {
    "base": "main",
    "remote": "origin",
    "test.command": "",                # e.g. "python -m pytest -q"; empty means no tests gate
    "review.required": "auto",         # auto: needs a peer approval while a peer is still running; yes; no
    "review.command": "",              # optional automatic reviewer, e.g. "claude -p {prompt}"
    "resolve.command": "claude -p {prompt} --permission-mode acceptEdits",
    "resolve.verify": "true",          # a second model checks every automatic resolution before it lands
    "resolve.verify_command": "claude -p {prompt} --allowedTools Read Glob Grep",
    "consensus.window": "0",           # seconds parties may object to an auto-resolution before it lands
    "test.retries": "1",               # re-runs of a failing test suite; a pass on retry is flagged as flaky
    "predict.tests": "true",           # also run the tests on predicted merges of overlapping agents
    "regen": "",                       # generated files: "package-lock.json=npm install --package-lock-only; ..."
    "land.semantic": "true",           # block a landing whose merge still uses a name the other side removed
    "land.auto": "true",               # the daemon lands agents as soon as they're ready
    "push.auto": "false",              # push base to the remote after every landing
    # agents may run git (pushes from agent worktrees are blocked by braid's pre-push hook) and the tests
    "agent.command": "claude -p {prompt} --mcp-config {mcp_config} --permission-mode acceptEdits "
                     "--allowedTools mcp__braid 'Bash(git:*)'",
    "watch.interval": "5",
    "plan.command": "claude -p {prompt} --allowedTools Read Glob Grep",  # the planner for braid do (read-only)
    "plan.max_tasks": "6",
    "plan.serialize": "true",          # tasks that own the same file run one after the other, not in parallel
    "agent.auto_resume": "2",          # times the daemon relaunches an agent that stopped with feedback to handle
    "spelunk": "auto",                 # use Spelunk when it is installed: auto, on, off (see braid/spelunk.py)
    "spelunk.command": "spelunk",
}


def global_dir():
    """Per-user braid settings and secrets, shared by every repo: ~/.config/braid (or $BRAID_HOME)."""
    return Path(os.environ.get("BRAID_HOME") or Path.home() / ".config" / "braid")


def global_cfg():
    try:
        return json.loads((global_dir() / "settings.json").read_text())
    except (OSError, ValueError):
        return {}


def set_global_cfg(key, value):
    data = global_cfg()
    if value == "":
        data.pop(key, None)
    else:
        data[key] = value
    global_dir().mkdir(parents=True, exist_ok=True)
    (global_dir() / "settings.json").write_text(json.dumps(data, indent=1, sort_keys=True))


class Store:
    def __init__(self, repo):
        self.repo = Path(repo)
        self.dir = gitutil.common_dir(repo) / "braid"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.dir / "state.db", timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass  # some network filesystems refuse WAL; rollback journal still works
        self.db.executescript(SCHEMA)
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(agents)")}
        if "base" not in cols:  # databases made before per-agent bases
            self.db.execute("ALTER TABLE agents ADD COLUMN base TEXT")

    def close(self):
        self.db.close()

    # ---- config
    def get_meta(self, key, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, str(value)))

    def cfg(self, key):
        """This repo's setting, else your global one (braid settings --global), else the default."""
        value = self.get_meta("cfg." + key)
        if value is None:
            value = global_cfg().get(key)
        return value if value is not None else DEFAULTS.get(key, "")

    def cfg_bool(self, key):
        return self.cfg(key).lower() in ("1", "true", "yes", "on")

    def set_cfg(self, key, value):
        self.set_meta("cfg." + key, value)

    def all_cfg(self):
        return {k: self.cfg(k) for k in DEFAULTS}

    def base_branch(self):
        return self.cfg("base")

    def agent_base(self, agent):
        """The branch an agent lands on: its own, else the repo default. With approve.mode run, a staging
        branch (braid-run/<base>) that collects the whole run and goes to you for one yes at the end."""
        base = agent.get("base") or self.base_branch()
        if (self.cfg("approve.mode") == "run" and self.cfg_bool("approve.required")
                and agent.get("status") not in ("landed", "done")):
            return self.run_branch(base)
        return base

    def run_branch(self, base):
        """The staging branch for a run on base, created from base when a run starts."""
        staging = RUN_PREFIX + base
        if not gitutil.rev(staging, cwd=self.repo) and gitutil.rev(base, cwd=self.repo):
            gitutil.git("branch", staging, base, cwd=self.repo)
            self.event("branch", f"created {staging} to collect this run before it goes to {base}")
        return staging

    def bases_in_use(self):
        return sorted({self.base_branch()} | {self.agent_base(a) for a in self.agents()})

    # ---- plans (braid do)
    def add_plan(self, goal, base, tasks, push=False):
        cur = self.db.execute("INSERT INTO plans(goal, base, status, push, at) VALUES (?, ?, 'proposed', ?, ?)",
                              (goal, base, int(push), time.time()))
        pid = cur.lastrowid
        for i, t in enumerate(tasks):
            self.db.execute(
                "INSERT INTO plan_tasks(plan_id, id, title, description, files, depends_on, status, seq) "
                "VALUES (?, ?, ?, ?, ?, ?, 'waiting', ?)",
                (pid, t["id"], t["title"], t.get("description", ""), json.dumps(t.get("files", [])),
                 json.dumps(t.get("depends_on", [])), i))
        return pid

    def plan(self, pid):
        r = self.db.execute("SELECT * FROM plans WHERE id=?", (pid,)).fetchone()
        return dict(r) if r else None

    def plans(self, status=None):
        q, args = "SELECT * FROM plans", ()
        if status:
            q, args = q + " WHERE status=?", (status,)
        return [dict(r) for r in self.db.execute(q + " ORDER BY id", args)]

    def plan_tasks(self, pid):
        rows = [dict(r) for r in self.db.execute("SELECT * FROM plan_tasks WHERE plan_id=? ORDER BY seq", (pid,))]
        for r in rows:
            r["files"], r["depends_on"] = json.loads(r["files"]), json.loads(r["depends_on"])
        return rows

    def update_plan_task(self, pid, tid, **fields):
        cols = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE plan_tasks SET {cols} WHERE plan_id=? AND id=?", (*fields.values(), pid, tid))

    def set_plan_status(self, pid, status):
        self.db.execute("UPDATE plans SET status=? WHERE id=?", (status, pid))

    def initialized(self):
        return self.get_meta("cfg.base") is not None

    # ---- events (the activity feed)
    def event(self, kind, text, agent=None):
        self.db.execute("INSERT INTO events(kind, agent, text, at) VALUES (?, ?, ?, ?)",
                        (kind, agent, text, time.time()))

    def events_for(self, agent, kind):
        """Text of the latest event of this kind for an agent, or None."""
        r = self.db.execute("SELECT text FROM events WHERE agent=? AND kind=? ORDER BY id DESC LIMIT 1",
                            (agent, kind)).fetchone()
        return r["text"] if r else None

    def events(self, limit=50):
        rows = self.db.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in reversed(rows)]

    # ---- agents
    def add_agent(self, name, branch, worktree, task, base=None):
        now = time.time()
        self.db.execute(
            "INSERT OR REPLACE INTO agents(name, branch, worktree, task, status, heartbeat, created_at, base) "
            "VALUES (?, ?, ?, ?, 'active', ?, ?, ?)",
            (name, branch, str(worktree), task, now, now, base or self.base_branch()))
        self.event("agent", f"started: {task}", name)

    def agents(self, statuses=None):
        rows = [dict(r) for r in self.db.execute("SELECT * FROM agents ORDER BY created_at, name")]
        return [r for r in rows if statuses is None or r["status"] in statuses]

    def live_agents(self):
        """Agents whose work is not on the base branch yet."""
        return self.agents(("active", "ready", "blocked", "exited", "paused"))

    def agent(self, name):
        r = self.db.execute("SELECT * FROM agents WHERE name=?", (name,)).fetchone()
        return dict(r) if r else None

    def agent_for_worktree(self, worktree):
        wt = str(Path(worktree).resolve())
        for a in self.agents():
            if str(Path(a["worktree"]).resolve()) == wt:
                return a
        return None

    def update_agent(self, name, **fields):
        cols = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE agents SET {cols} WHERE name=?", (*fields.values(), name))

    def set_status(self, name, status, why=None):
        fields = {"status": status}
        if status == "ready":
            fields["ready_at"] = time.time()
        self.update_agent(name, **fields)
        self.event("status", status + (f": {why}" if why else ""), name)

    def heartbeat(self, name):
        self.update_agent(name, heartbeat=time.time())

    def process_alive(self, agent):
        """Is this agent's process still running? Interactive agents (no pid) count while status is active."""
        pid = agent.get("pid")
        if not pid:
            return agent["status"] == "active"
        try:
            done, _ = os.waitpid(pid, os.WNOHANG)  # reap if it's our child
            if done:
                return False
        except ChildProcessError:
            pass
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return _not_zombie(pid)

    # ---- intents
    def declare_intent(self, agent, paths, description):
        self.db.execute("INSERT INTO intents(agent, paths, description, at) VALUES (?, ?, ?, ?)",
                        (agent, json.dumps(list(paths)), description, time.time()))

    def intents(self, agent=None):
        q, args = "SELECT * FROM intents", ()
        if agent:
            q, args = q + " WHERE agent=?", (agent,)
        rows = [dict(r) for r in self.db.execute(q + " ORDER BY at", args)]
        for r in rows:
            r["paths"] = json.loads(r["paths"])
        return rows

    # ---- leases
    def acquire_lease(self, agent, path, kind="soft", ttl=3600):
        """Take a lease unless another agent holds an overlapping hard lease. Returns (ok, other_holders)."""
        others = [l for l in self.overlapping_leases(path) if l["agent"] != agent]
        if any(l["kind"] == "hard" for l in others) or (kind == "hard" and others):
            return False, others
        self.db.execute("INSERT OR REPLACE INTO leases(agent, path, kind, expires_at) VALUES (?, ?, ?, ?)",
                        (agent, path, kind, time.time() + ttl))
        return True, others

    def release_lease(self, agent, path=None):
        freed = [l["path"] for l in self.leases() if l["agent"] == agent and path in (None, l["path"])]
        if path is None:
            self.db.execute("DELETE FROM leases WHERE agent=?", (agent,))
        else:
            self.db.execute("DELETE FROM leases WHERE agent=? AND path=?", (agent, path))
        for p in freed:
            self._wake_waiters(p)

    def wait_for_lease(self, agent, path):
        """Queue agent for a lease it couldn't get. Returns its place in the queue (1 = next)."""
        key = f"lease.wait.{path}"
        queue = [a for a in json.loads(self.get_meta(key, "[]")) if a != agent] + [agent]
        self.set_meta(key, json.dumps(queue))
        return len(queue)

    def _wake_waiters(self, path):
        """Tell the first agent queued on an overlapping path that it's free (it then has to acquire it)."""
        for row in self.db.execute("SELECT key, value FROM meta WHERE key LIKE 'lease.wait.%'").fetchall():
            wanted = row["key"][len("lease.wait."):]
            queue = [a for a in json.loads(row["value"]) if (self.agent(a) or {}).get("status") in
                     ("active", "ready", "blocked", "paused", "exited")]
            if not queue or not paths_overlap(wanted, path):
                if not queue:
                    self.db.execute("DELETE FROM meta WHERE key=?", (row["key"],))
                continue
            if any(l["kind"] == "hard" and l["agent"] != queue[0] for l in self.overlapping_leases(wanted)):
                continue  # still held by someone else
            self.post_note("braid", "lease", f"{wanted} is free now: call acquire_lease to take it and continue.",
                           to=queue[0])
            self.set_meta(row["key"], json.dumps(queue[1:]))

    def mark_notes_read(self, agent, upto):
        if upto > int(self.get_meta(f"notes.read.{agent}", "0")):
            self.set_meta(f"notes.read.{agent}", upto)

    def unread_notes(self, agent, topics=("conflict", "blocked")):
        since = int(self.get_meta(f"notes.read.{agent}", "0"))
        return [n for n in self.notes(since, for_agent=agent) if n["topic"] in topics and n["agent"] != agent
                and n["to_agent"] == agent]

    def leases(self):
        self.db.execute("DELETE FROM leases WHERE expires_at < ?", (time.time(),))
        return [dict(r) for r in self.db.execute("SELECT * FROM leases ORDER BY path")]

    def overlapping_leases(self, path):
        return [l for l in self.leases() if paths_overlap(l["path"], path)]

    # ---- snapshots
    def set_snapshot(self, agent, oid):
        self.db.execute("INSERT OR REPLACE INTO snapshots(agent, oid, at) VALUES (?, ?, ?)",
                        (agent, oid, time.time()))

    def snapshot(self, agent):
        r = self.db.execute("SELECT * FROM snapshots WHERE agent=?", (agent,)).fetchone()
        return dict(r) if r else None

    # ---- risks
    def replace_risks(self, risks):
        now = time.time()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute("DELETE FROM risks")
            self.db.executemany(
                "INSERT INTO risks(a, b, severity, files, at) VALUES (?, ?, ?, ?, ?)",
                [(a, b, sev, json.dumps(sorted(files)), now) for a, b, sev, files in risks])
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def risks(self, agent=None):
        q, args = "SELECT * FROM risks", ()
        if agent:
            q, args = q + " WHERE a=? OR b=?", (agent, agent)
        rows = [dict(r) for r in self.db.execute(q + " ORDER BY severity, a, b", args)]
        for r in rows:
            r["files"] = json.loads(r["files"])
        return rows

    # ---- notes
    def post_note(self, agent, topic, text, to=None):
        self.db.execute("INSERT INTO notes(agent, topic, text, to_agent, at) VALUES (?, ?, ?, ?, ?)",
                        (agent, topic, text, to, time.time()))

    def notes(self, since_id=0, topic=None, for_agent=None):
        q, args = "SELECT * FROM notes WHERE id > ?", [since_id]
        if topic:
            q += " AND topic=?"
            args.append(topic)
        if for_agent:
            q += " AND (to_agent IS NULL OR to_agent=? OR agent=?)"
            args += [for_agent, for_agent]
        return [dict(r) for r in self.db.execute(q + " ORDER BY id", args)]

    # ---- reviews
    def add_review(self, agent, reviewer, commit_oid, verdict, comment):
        self.db.execute("INSERT INTO reviews(agent, reviewer, commit_oid, verdict, comment, at) "
                        "VALUES (?, ?, ?, ?, ?, ?)", (agent, reviewer, commit_oid, verdict, comment, time.time()))
        self.event("review", f"{verdict} from {reviewer}: {comment}", agent)

    def reviews(self, agent, commit_oid=None):
        q, args = "SELECT * FROM reviews WHERE agent=?", [agent]
        if commit_oid:
            q += " AND commit_oid=?"
            args.append(commit_oid)
        return [dict(r) for r in self.db.execute(q + " ORDER BY id", args)]

    # ---- decisions (consensus on conflict resolutions)
    def add_decision(self, agent, parties, files, status, proposal_oid, detail):
        cur = self.db.execute(
            "INSERT INTO decisions(agent, parties, files, status, proposal_oid, detail, at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (agent, json.dumps(sorted(parties)), json.dumps(sorted(files)), status, proposal_oid, detail,
             time.time()))
        return cur.lastrowid

    def decision(self, did):
        r = self.db.execute("SELECT * FROM decisions WHERE id=?", (did,)).fetchone()
        return _decode_decision(r) if r else None

    def decisions(self, status=None, agent=None):
        q, args = "SELECT * FROM decisions WHERE 1=1", []
        if status:
            q += " AND status=?"
            args.append(status)
        rows = [_decode_decision(r) for r in self.db.execute(q + " ORDER BY id", args)]
        if agent:
            rows = [d for d in rows if d["agent"] == agent or agent in d["parties"]]
        return rows

    def decide(self, did, status, detail=None):
        if detail:
            self.db.execute("UPDATE decisions SET status=?, decided_at=?, detail=? WHERE id=?",
                            (status, time.time(), detail, did))
        else:
            self.db.execute("UPDATE decisions SET status=?, decided_at=? WHERE id=?", (status, time.time(), did))

    def vote(self, did, agent, vote, reason=""):
        self.db.execute("INSERT OR REPLACE INTO votes(decision_id, agent, vote, reason, at) VALUES (?, ?, ?, ?, ?)",
                        (did, agent, vote, reason, time.time()))

    def votes(self, did):
        return [dict(r) for r in self.db.execute("SELECT * FROM votes WHERE decision_id=?", (did,))]

    # ---- locks
    def lock(self, name):
        return FileLock(self.dir / f"{name}.lock")


def _decode_decision(r):
    d = dict(r)
    d["parties"] = json.loads(d["parties"])
    d["files"] = json.loads(d["files"])
    return d


def _not_zombie(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[-1].split()[0] != "Z"
    except OSError:
        return True


class FileLock:
    """Exclusive inter-process lock (blocking)."""

    def __init__(self, path):
        self.path = path
        self.f = None

    def __enter__(self):
        import fcntl
        self.f = open(self.path, "w")
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        import fcntl
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def paths_overlap(a, b):
    """True if two repo-relative paths/globs could refer to the same file."""
    a, b = a.rstrip("/"), b.rstrip("/")
    if a == b or fnmatch.fnmatch(a, b) or fnmatch.fnmatch(b, a):
        return True
    return a.startswith(b + "/") or b.startswith(a + "/")
