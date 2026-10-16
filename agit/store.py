"""Shared memory: one SQLite file in the repo's common git dir, used by every agent."""
import fnmatch
import json
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
    status TEXT NOT NULL DEFAULT 'active',
    heartbeat REAL
);
CREATE TABLE IF NOT EXISTS intents (
    id INTEGER PRIMARY KEY,
    agent TEXT NOT NULL,
    paths TEXT NOT NULL,          -- JSON list of paths/globs
    description TEXT NOT NULL,
    at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS leases (
    agent TEXT NOT NULL,
    path TEXT NOT NULL,           -- path or glob, repo-relative
    kind TEXT NOT NULL,           -- 'soft' warns, 'hard' blocks other agents' commits
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
    b TEXT NOT NULL,              -- another agent, or '@<base>' for the base branch
    severity TEXT NOT NULL,       -- 'conflict' or 'overlap'
    files TEXT NOT NULL,          -- JSON list
    at REAL NOT NULL,
    PRIMARY KEY (a, b)
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY,
    agent TEXT NOT NULL,
    topic TEXT NOT NULL,
    text TEXT NOT NULL,
    at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def db_path(repo):
    return gitutil.common_dir(repo) / "agit" / "state.db"


class Store:
    def __init__(self, repo):
        self.repo = Path(repo)
        path = db_path(repo)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass  # some network filesystems refuse WAL; default journaling still works
        self.db.executescript(SCHEMA)

    # meta
    def get_meta(self, key, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))

    def base_branch(self):
        return self.get_meta("base_branch", "main")

    # agents
    def add_agent(self, name, branch, worktree, task):
        self.db.execute(
            "INSERT OR REPLACE INTO agents(name, branch, worktree, task, status, heartbeat) "
            "VALUES (?, ?, ?, ?, 'active', ?)", (name, branch, str(worktree), task, time.time()))

    def agents(self, active_only=True):
        q = "SELECT * FROM agents" + (" WHERE status='active'" if active_only else "") + " ORDER BY name"
        return [dict(r) for r in self.db.execute(q)]

    def agent(self, name):
        r = self.db.execute("SELECT * FROM agents WHERE name=?", (name,)).fetchone()
        return dict(r) if r else None

    def agent_for_worktree(self, worktree):
        wt = str(Path(worktree).resolve())
        for a in self.agents(active_only=False):
            if str(Path(a["worktree"]).resolve()) == wt:
                return a
        return None

    def set_status(self, name, status):
        self.db.execute("UPDATE agents SET status=? WHERE name=?", (status, name))

    def heartbeat(self, name):
        self.db.execute("UPDATE agents SET heartbeat=? WHERE name=?", (time.time(), name))

    # intents
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

    # leases
    def acquire_lease(self, agent, path, kind="soft", ttl=3600):
        """Take a lease unless another agent holds an overlapping hard lease. Returns (ok, holders)."""
        others = [l for l in self.overlapping_leases(path) if l["agent"] != agent]
        if any(l["kind"] == "hard" for l in others) or (kind == "hard" and others):
            return False, others
        self.db.execute("INSERT OR REPLACE INTO leases(agent, path, kind, expires_at) VALUES (?, ?, ?, ?)",
                        (agent, path, kind, time.time() + ttl))
        return True, others

    def release_lease(self, agent, path=None):
        if path is None:
            self.db.execute("DELETE FROM leases WHERE agent=?", (agent,))
        else:
            self.db.execute("DELETE FROM leases WHERE agent=? AND path=?", (agent, path))

    def leases(self):
        self.db.execute("DELETE FROM leases WHERE expires_at < ?", (time.time(),))
        return [dict(r) for r in self.db.execute("SELECT * FROM leases ORDER BY path")]

    def overlapping_leases(self, path):
        return [l for l in self.leases() if paths_overlap(l["path"], path)]

    # snapshots
    def set_snapshot(self, agent, oid):
        self.db.execute("INSERT OR REPLACE INTO snapshots(agent, oid, at) VALUES (?, ?, ?)",
                        (agent, oid, time.time()))

    def snapshot(self, agent):
        r = self.db.execute("SELECT * FROM snapshots WHERE agent=?", (agent,)).fetchone()
        return dict(r) if r else None

    # risks
    def replace_risks(self, risks):
        """Atomically swap in a fresh set of risks: list of (a, b, severity, files)."""
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

    # notes
    def post_note(self, agent, topic, text):
        self.db.execute("INSERT INTO notes(agent, topic, text, at) VALUES (?, ?, ?, ?)",
                        (agent, topic, text, time.time()))

    def notes(self, since_id=0, topic=None):
        q, args = "SELECT * FROM notes WHERE id > ?", [since_id]
        if topic:
            q += " AND topic=?"
            args.append(topic)
        return [dict(r) for r in self.db.execute(q + " ORDER BY id", args)]


def paths_overlap(a, b):
    """True if two repo-relative paths/globs could refer to the same file."""
    a, b = a.rstrip("/"), b.rstrip("/")
    if a == b:
        return True
    if fnmatch.fnmatch(a, b) or fnmatch.fnmatch(b, a):
        return True
    # directory prefix: "src/auth" covers "src/auth/session.py"
    return a.startswith(b + "/") or b.startswith(a + "/")
