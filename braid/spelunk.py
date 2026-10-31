"""Optional Spelunk support: braid works without it, and gets sharper with it.

[Spelunk](https://github.com/ar-0911/spelunk) indexes a repository with tree-sitter: symbols, calls, imports,
routes, tests and risks, in 19 languages. When the `spelunk` command is on PATH (setting `spelunk`: `auto`, the
default; `on` or `off` to force it) braid uses it in five places:

1. `braid do`: the planner gets Spelunk's module map and dependency graph, so tasks follow real module lines.
2. Agents get Spelunk's MCP tools (where, trace, impact, ...) next to braid's, instead of grepping.
3. Semantic conflicts: definitions and call sites come from Spelunk's parsers instead of a regex, so methods,
   other languages and changed signatures count too.
4. Approvals: the summary lists the routes the change reaches, the tests to run, changed code no test reaches
   and risks in the changed lines (`spelunk impact`).
5. The merge driver: brace languages (JS/TS, Go, Rust, Java, ...) are split with Spelunk's tree-sitter outline
   instead of a column-0 heuristic, so two methods added to the same class merge cleanly (`spelunk outline`).

Everything goes through Spelunk's command line with JSON, so neither tool imports the other. Any failure
(not installed, too old, timed out) falls back to what braid does on its own.
"""
import json
import shlex
import shutil
import subprocess
from pathlib import Path

from . import gitutil

TIMEOUT = 600  # a first scan of a big repo takes a minute or two; later ones only re-read changed files


def command(store):
    return shlex.split(store.cfg("spelunk.command") or "spelunk")


def enabled(store):
    mode = (store.cfg("spelunk") or "auto").lower()
    if mode in ("off", "no", "false", "0"):
        return False
    cmd = command(store)
    return bool(cmd) and (mode in ("on", "yes", "true", "1") or shutil.which(cmd[0]) is not None)


def run(store, args, cwd, stdin=None, timeout=TIMEOUT):
    """Spelunk's stdout, or None when it isn't available or fails."""
    if not enabled(store):
        return None
    try:
        proc = subprocess.run(command(store) + args, cwd=cwd, input=stdin, capture_output=True, text=True,
                              timeout=timeout, stdin=None if stdin is not None else subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


def run_json(store, args, cwd, stdin=None, timeout=TIMEOUT):
    text = run(store, args, cwd, stdin, timeout)
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def checkout_dir(store):
    # named like the repo, since Spelunk names the project after its folder
    repo = store.repo.resolve()
    return repo.parent / f"{repo.name}.agents" / ".spelunk" / repo.name


def checkout(store, oid):
    """A detached worktree at `oid` for Spelunk to index, kept between calls so rescans are incremental.

    Callers hold store.lock("spelunk") while they use it."""
    path = checkout_dir(store)
    if not (path / ".git").exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        gitutil.git("worktree", "prune", cwd=store.repo, check=False)
        rc, _ = gitutil.git("worktree", "add", "-q", "--detach", str(path), oid, cwd=store.repo, check=False)
        if rc != 0:
            return None
        return path
    rc, _ = gitutil.git("checkout", "-q", "--detach", "-f", oid, cwd=path, check=False)
    return path if rc == 0 else None


# ------------------------------------------------------------------ 1. planner context

def overview(store, base):
    """Spelunk's overview of `base` (modules, what depends on what, entry points, commands), or ""."""
    if not enabled(store):
        return ""
    oid = gitutil.rev(base, cwd=store.repo)
    if not oid:
        return ""
    with store.lock("spelunk"):
        path = checkout(store, oid)
        text = run(store, ["overview"], cwd=path) if path else None
    return (text or "").strip()[:12000]


# ------------------------------------------------------------------ 2. agents' MCP tools

def mcp_server(store, worktree):
    """The mcpServers entry that gives an agent Spelunk's tools over its own worktree, or None."""
    if not enabled(store):
        return None
    cmd = command(store)
    return {"command": cmd[0], "args": cmd[1:] + ["mcp", "-C", str(worktree)]}


AGENT_HINT = """
Spelunk's MCP tools (`spelunk`) index this worktree: `where` finds the code for a feature, error or name;
`trace` shows what calls a function or route and what it calls; `dependents` and `impact` say what your change
reaches. Use them before grepping or reading whole directories.
"""


# ------------------------------------------------------------------ 3. semantic conflicts

class Parser:
    """Symbols and call sites per file, from `spelunk facts`, cached by blob id. Hashable, for lru_cache."""

    def __init__(self, store):
        self.store = store
        self.cache = {}
        self.broken = False

    def facts(self, files):
        """files: {(path, blob_oid): text}. Returns {(path, blob_oid): facts or None}."""
        want = {k: v for k, v in files.items() if k not in self.cache}
        if want and not self.broken:
            payload = json.dumps({"files": [{"path": p, "text": t} for (p, _), t in want.items()]})
            data = run_json(self.store, ["facts"], cwd=self.store.repo, stdin=payload, timeout=120)
            if not isinstance(data, dict):
                self.broken = True  # an old Spelunk without `facts`: use braid's own parsing from now on
            else:
                got = {f.get("path"): f for f in data.get("files", [])}
                for (p, oid) in want:
                    self.cache[(p, oid)] = got.get(p)
        return {k: self.cache.get(k) for k in files}


_parsers = {}


def parser(store):
    """One Parser per repo and command, so the cache survives watcher passes. None when Spelunk is off."""
    if not enabled(store):
        return None
    key = (str(store.repo), tuple(command(store)))
    if key not in _parsers:
        _parsers[key] = Parser(store)
    return _parsers[key]


# ------------------------------------------------------------------ 4. impact for approvals

def impact(store, base_oid, new_oid):
    """A short summary of `spelunk impact` between two commits, or None."""
    if not enabled(store):
        return None
    with store.lock("spelunk"):
        path = checkout(store, new_oid)
        data = run_json(store, ["impact", base_oid, "--head", new_oid, "--json"], cwd=path) if path else None
    if not isinstance(data, dict):
        return None
    return summarize(data)


def summarize(i):
    risks = [{"title": r.get("title", ""), "severity": r.get("severity", ""),
              "where": next((f"{l['path']}:{l.get('line') or ''}".rstrip(":") for l in r.get("locations", [])), "")}
             for r in i.get("risks", [])]
    return {
        "routes": [{"method": r["method"], "path": r["path"], "where": f"{r['file']}:{r['line']}",
                    "reason": r.get("reason", "")} for r in i.get("routes", [])][:20],
        "tests": [t["path"] for t in i.get("tests", [])][:30],
        "untested": i.get("untested", [])[:20],
        "dependents": len(i.get("dependents", [])),
        "modules": [m["path"] or "(root)" for m in i.get("modules", [])][:12],
        "env": sorted({e["name"] for e in i.get("env", [])})[:20],
        "risks": risks[:12],
    }


def impact_text(s):
    """One or two sentences for the approval message."""
    if not s:
        return ""
    parts = []
    if s["routes"]:
        names = ", ".join(f"{r['method']} {r['path']}" for r in s["routes"][:5])
        parts.append(f"Reaches {len(s['routes'])} route{'s' * (len(s['routes']) != 1)} ({names}"
                     f"{', ...' if len(s['routes']) > 5 else ''}).")
    if s["dependents"]:
        parts.append(f"{s['dependents']} file{'s' * (s['dependents'] != 1)} depend on the changed code.")
    if s["untested"]:
        parts.append(f"No test reaches {', '.join(s['untested'][:4])}{' and more' if len(s['untested']) > 4 else ''}.")
    if s["env"]:
        parts.append(f"Reads settings {', '.join(s['env'][:5])}.")
    bad = [r for r in s["risks"] if r["severity"] == "high"]
    if bad:
        parts.append(f"{len(bad)} high-severity risk{'s' * (len(bad) != 1)} in the changed lines.")
    return " ".join(parts)


def installed_version(store):
    out = run(store, ["--version"], cwd=Path.cwd(), timeout=20)
    return out.strip() if out else None


# ------------------------------------------------------------------ 5. structural merges

OUTLINE_TIMEOUT = 30


def outliner(store):
    """outline(texts, path) -> one outline per text, or None; for the merge driver. None when Spelunk is off.

    Parses the texts as if they were `path` (git hands the driver temp files with no extension). Older Spelunks
    without the outline command fail, and the driver falls back to its own splitting."""
    if not enabled(store):
        return None

    def outline(texts, path):
        req = json.dumps({"files": [{"path": path, "text": t} for t in texts]})
        data = run_json(store, ["outline"], cwd=store.repo, stdin=req, timeout=OUTLINE_TIMEOUT)
        files = data.get("files") if isinstance(data, dict) else None
        return files if isinstance(files, list) and len(files) == len(texts) else None
    return outline
