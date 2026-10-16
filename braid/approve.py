"""Human approval before work lands: summarize the change, notify the owner, wait for a yes.

With `approve.required` on, a landing that has passed review, conflict resolution and tests stops just before
the base branch moves. braid records the proposed merge commit, writes a summary (what changed, how it affects
the rest of the code, test results), sends it over the configured channels (email, WhatsApp, Telegram, or any
command), and waits. A yes (a click on the review page, a reply, or `braid approve`) lands exactly the commit that
was reviewed; a no sends the work back to its agent with the reason.
"""
import ast
import json
import re
import secrets
import shlex
import subprocess
import time

from . import gitutil
from .store import DEFAULTS

DEFAULTS.update({
    "approve.required": "no",          # yes: every landing waits for a human yes
    "approve.channels": "",            # comma list of: cloudflare, email, whatsapp, telegram, command
    "approve.cloudflare.url": "",      # your braid worker, e.g. https://braid-approvals.you.workers.dev
    "approve.summary_command": "claude -p {prompt}",  # writes the summary; empty for the built-in one
    "approve.inline_diff_lines": "40",  # diffs up to this many lines go in the message itself
    "approve.push": "true",            # push the base branch after an approved landing
    "approve.public_url": "",          # where the review page is reachable from your phone, if you host it
    "approve.tunnel": "",              # cloudflared: open a free public tunnel to the review page
    "approve.port": "8765",
    "approve.bind": "127.0.0.1",
    "approve.poll_interval": "15",     # seconds between checks for replies
    "approve.email.to": "",
    "approve.email.from": "",          # default: approve.email.user
    "approve.email.smtp": "smtp.gmail.com:587",
    "approve.email.imap": "",          # default: the smtp host with smtp -> imap, port 993
    "approve.email.user": "",          # password: braid approvals secret BRAID_SMTP_PASSWORD
    "approve.whatsapp.to": "",         # your number, e.g. +447700900123
    "approve.whatsapp.from": "+14155238886",  # Twilio sandbox number, or your Twilio WhatsApp sender
    "approve.whatsapp.content_sid": "",  # approved Twilio template, needed outside the 24h reply window
    "approve.telegram.chat_id": "",
    "approve.command": "",             # any notifier; {message}, {url}, {code}, {title} are filled in
})

SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY,
    agent TEXT NOT NULL,
    head_oid TEXT NOT NULL,       -- the agent's branch head being approved
    base_oid TEXT NOT NULL,       -- base branch when the proposal was made
    proposal_oid TEXT NOT NULL,   -- the merge commit that lands on yes
    status TEXT NOT NULL,         -- pending | approved | rejected | landed | failed
    token TEXT NOT NULL,          -- secret in review-page links
    code TEXT NOT NULL,           -- short code for replies: YES 7K2Q
    report TEXT NOT NULL,         -- JSON: title, summary, impact, tests, files, entities ...
    diff TEXT NOT NULL,
    sent TEXT NOT NULL DEFAULT '',  -- channels the request went to
    created_at REAL NOT NULL,
    decided_at REAL,
    decided_by TEXT,
    comment TEXT,
    result TEXT                   -- what happened when it was applied
);
"""

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def ensure(store):
    store.db.executescript(SCHEMA)


def required(store):
    return store.cfg_bool("approve.required")


def _decode(row):
    if not row:
        return None
    a = dict(row)
    a["report"] = json.loads(a["report"])
    return a


def get(store, ref):
    """An approval by id or by reply code."""
    ensure(store)
    ref = str(ref).strip().lstrip("#")
    row = store.db.execute("SELECT * FROM approvals WHERE code=? ORDER BY id DESC LIMIT 1", (ref.upper(),)).fetchone()
    if not row and ref.isdigit():
        row = store.db.execute("SELECT * FROM approvals WHERE id=?", (int(ref),)).fetchone()
    return _decode(row)


def all_approvals(store, status=None):
    ensure(store)
    q, args = "SELECT * FROM approvals", ()
    if status:
        q, args = q + " WHERE status=?", (status,)
    return [_decode(r) for r in store.db.execute(q + " ORDER BY id", args)]


def lookup(store, agent, head):
    """Latest approval for this exact agent head, or None."""
    ensure(store)
    return _decode(store.db.execute("SELECT * FROM approvals WHERE agent=? AND head_oid=? ORDER BY id DESC LIMIT 1",
                                    (agent, head)).fetchone())


def _set(store, aid, **fields):
    cols = ", ".join(f"{k}=?" for k in fields)
    store.db.execute(f"UPDATE approvals SET {cols} WHERE id=?", (*fields.values(), aid))


def waiting_message(a):
    return f"waiting for your approval (#{a['id']}, reply YES {a['code']} or run: braid approve {a['id']})"


def rejection_message(a):
    who = a["decided_by"] or "the owner"
    return f"sent back by {who} before landing: {a['comment'] or 'no reason given'}"


# ------------------------------------------------------------------ request

def request(store, agent, base, base_oid, new_oid, tests, reviewers, resolution=None):
    """Record a pending approval for landing new_oid, write its report and notify. Returns the approval."""
    ensure(store)
    head = gitutil.rev(agent["branch"], cwd=store.repo)
    gitutil.git("update-ref", f"refs/braid/approvals/{agent['name']}", new_oid, cwd=store.repo)  # keep it from gc
    diff = gitutil.out("diff", "--find-renames", base_oid, new_oid, cwd=store.repo)
    report = build_report(store, agent, base, base_oid, new_oid, diff, tests, reviewers, resolution)
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(4))
    cur = store.db.execute(
        "INSERT INTO approvals(agent, head_oid, base_oid, proposal_oid, status, token, code, report, diff, created_at)"
        " VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)",
        (agent["name"], head, base_oid, new_oid, secrets.token_urlsafe(24), code, json.dumps(report), diff,
         time.time()))
    a = get(store, cur.lastrowid)
    store.event("approval", f"#{a['id']} asked for approval to land on {base}: {report['title']}", agent["name"])
    from . import notify
    sent = notify.send_request(store, a)
    _set(store, a["id"], sent=",".join(sent))
    return get(store, a["id"])


def decide(store, ref, approve_it, by, comment="", apply=True):
    """Record a yes or no. On yes, land it now (unless apply=False). Returns (approval, message)."""
    a = get(store, ref)
    if not a:
        return None, f"no approval {ref}"
    if a["status"] != "pending":
        return a, f"#{a['id']} is already {a['status']}"
    status = "approved" if approve_it else "rejected"
    _set(store, a["id"], status=status, decided_at=time.time(), decided_by=by, comment=comment or "")
    store.event("approval", f"#{a['id']} {status} by {by}" + (f": {comment}" if comment else ""), a["agent"])
    if not approve_it:
        from . import land
        a = get(store, a["id"])
        land.block(store, a["agent"], rejection_message(a))  # the watcher relaunches the agent to address it
        _set(store, a["id"], result="sent back to the agent")
        _report_back(store, a["id"])
        gitutil.git("update-ref", "-d", f"refs/braid/approvals/{a['agent']}", cwd=store.repo, check=False)
        return get(store, a["id"]), f"#{a['id']} sent back to {a['agent']}"
    if not apply:
        return get(store, a["id"]), f"#{a['id']} approved"
    return apply_approved(store, a["id"])


def apply_approved(store, aid):
    from . import land
    a = get(store, aid)
    r = land.land(store, a["agent"], push=store.cfg_bool("approve.push"))
    if r.ok:
        if get(store, aid)["status"] != "landed":
            landed(store, aid, r.message)
    elif not r.waiting:
        _set(store, aid, status="failed", result=r.message)
        _report_back(store, aid)
    else:  # approved but can't land yet (e.g. uncommitted changes where main is checked out): retried by the watcher
        _set(store, aid, result=r.message)
        _report_back(store, aid)
    return get(store, aid), r.message


def landed(store, aid, message):
    _set(store, aid, status="landed", result=message)
    gitutil.git("update-ref", "-d", f"refs/braid/approvals/{get(store, aid)['agent']}", cwd=store.repo, check=False)
    _report_back(store, aid)


def _report_back(store, aid):
    from . import notify
    notify.update_remote(store, get(store, aid))


# ------------------------------------------------------------------ report

def build_report(store, agent, base, base_oid, new_oid, diff, tests, reviewers, resolution):
    passed, output = tests
    files = numstat(store, base_oid, new_oid)
    entities = changed_entities(store, base_oid, new_oid, [f["path"] for f in files])
    report = {
        "agent": agent["name"],
        "task": agent["task"],
        "agent_summary": agent.get("summary") or "",
        "base": base,
        "base_oid": base_oid,
        "proposal_oid": new_oid,
        "files": files,
        "added": sum(f["added"] for f in files),
        "removed": sum(f["removed"] for f in files),
        "diff_lines": diff.count("\n"),
        "entities": entities,
        "tests": {"ran": bool(store.cfg("test.command")), "passed": passed, "command": store.cfg("test.command"),
                  "counts": test_counts(output), "output": output[-4000:]},
        "reviewers": reviewers,
        "reviews": [{"reviewer": r["reviewer"], "verdict": r["verdict"], "comment": r["comment"]}
                    for r in store.reviews(agent["name"]) if r["reviewer"] != agent["name"]][-5:],
        "resolution": resolution,
        "commits": gitutil.out("log", "--format=%h %s", "--no-merges", f"{base_oid}..{new_oid}",
                               cwd=store.repo).splitlines()[:30],
    }
    report.update(fallback_summary(report))
    llm = llm_summary(store, report, diff)
    if llm:
        report.update({k: v for k, v in llm.items() if v})
        report["summary_by"] = "model"
    return report


def numstat(store, a, b):
    files = []
    for line in gitutil.out("diff", "--numstat", "--find-renames", a, b, cwd=store.repo).splitlines():
        add, rem, path = line.split("\t", 2)
        files.append({"path": path, "added": int(add) if add.isdigit() else 0,
                      "removed": int(rem) if rem.isdigit() else 0, "binary": add == "-", "note": ""})
    return files


def _show(store, oid, path):
    rc, text = gitutil.git("show", f"{oid}:{path}", cwd=store.repo, check=False)
    return text if rc == 0 else None


def py_defs(text):
    """{qualified name: source} for functions and classes (and methods) in Python source."""
    out = {}
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return out
    lines = text.splitlines()

    def walk(nodes, prefix):
        for n in nodes:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + n.name
                start = min([n.lineno] + [d.lineno for d in n.decorator_list])
                body = "\n".join(lines[start - 1:n.end_lineno])
                if isinstance(n, ast.ClassDef):
                    walk(n.body, name + ".")
                    body = "\n".join(l for l in body.splitlines() if l.strip())  # class header + members
                out[name] = (body, "class" if isinstance(n, ast.ClassDef) else "function")
    walk(tree.body, "")
    return out


DEF_RE = re.compile(r"^\s*(?:export\s+)?(?:pub\s+)?(?:async\s+)?(?:def|function|func|fn|class|interface|struct)\s+"
                    r"(?:\([^)]*\)\s*)?([A-Za-z_][\w]*)", re.M)


def changed_entities(store, a, b, paths):
    """Functions and classes added, changed or removed, and where else the changed ones are used."""
    result = []
    for path in paths:
        before, after = _show(store, a, path), _show(store, b, path)
        if path.endswith(".py"):
            old, new = py_defs(before or ""), py_defs(after or "")
            for name in sorted(set(old) | set(new)):
                if name not in old:
                    result.append({"path": path, "name": name, "kind": new[name][1], "change": "added"})
                elif name not in new:
                    result.append({"path": path, "name": name, "kind": old[name][1], "change": "removed"})
                elif old[name][0] != new[name][0] and new[name][1] == "function":
                    result.append({"path": path, "name": name, "kind": "function", "change": "changed"})
        else:
            old = set(DEF_RE.findall(before or ""))
            new = set(DEF_RE.findall(after or ""))
            for name in sorted(new - old):
                result.append({"path": path, "name": name, "kind": "definition", "change": "added"})
            for name in sorted(old - new):
                result.append({"path": path, "name": name, "kind": "definition", "change": "removed"})
            hunks = gitutil.out("diff", "-U0", a, b, "--", path, cwd=store.repo)
            for name in sorted(set(re.findall(r"^@@[^@]*@@.*?\b([A-Za-z_]\w*)\s*\(", hunks, re.M)) & old & new):
                result.append({"path": path, "name": name, "kind": "definition", "change": "changed"})
    for e in result[:40]:
        if e["change"] == "added":
            continue
        short = e["name"].rsplit(".", 1)[-1]
        if len(short) < 4 or short.startswith("__"):
            continue
        rc, hits = gitutil.git("grep", "-l", "-w", "-F", short, b, "--", cwd=store.repo, check=False)
        users = sorted({h.split(":", 1)[1] for h in hits.splitlines() if ":" in h} - {e["path"]})
        e["used_by"] = users[:10]
    return result[:60]


def test_counts(output):
    for pat in (r"Ran (\d+) tests?", r"(\d+) passed"):
        m = re.search(pat, output or "")
        if m:
            failed = re.search(r"(\d+) failed|failures=(\d+)", output)
            return {"passed": int(m.group(1)),
                    "failed": int(next(g for g in failed.groups() if g)) if failed else 0}
    return None


def fallback_summary(r):
    """A summary built from the facts alone, used when no model is configured or it fails."""
    n = len(r["files"])
    title = r["agent_summary"] or r["task"]
    parts = [f"{r['agent']} worked on \"{r['task']}\" and changed {n} file{'s' * (n != 1)} "
             f"(+{r['added']} -{r['removed']})."]
    by_change = {}
    for e in r["entities"]:
        by_change.setdefault(e["change"], []).append(e["name"])
    for change in ("added", "changed", "removed"):
        names = by_change.get(change)
        if names:
            parts.append(f"{change.capitalize()}: {', '.join(names[:8])}{' and more' if len(names) > 8 else ''}.")
    if r["resolution"]:
        parts.append(f"A conflict with other agents' work was resolved automatically: {r['resolution']}")
    impact = []
    for e in r["entities"]:
        if e.get("used_by"):
            impact.append(f"{e['name']} ({e['change']}) is used in {', '.join(e['used_by'][:5])}")
    risk = "low"
    if any(e["change"] == "removed" and e.get("used_by") for e in r["entities"]) or r["resolution"]:
        risk = "high"
    elif impact or r["added"] + r["removed"] > 400:
        risk = "medium"
    return {"title": title[:120], "summary": " ".join(parts),
            "impact": ("; ".join(impact) + ".") if impact else "No other files use what changed.",
            "risk": risk, "summary_by": "braid"}


def llm_summary(store, report, diff):
    template = store.cfg("approve.summary_command")
    if not template:
        return None
    facts = {k: report[k] for k in ("task", "agent_summary", "base", "files", "entities", "reviews", "resolution")}
    facts["tests"] = {k: report["tests"][k] for k in ("ran", "passed", "counts")}
    prompt = (
        "You are writing the approval summary a busy developer reads on their phone before letting an AI agent's "
        "change land on their main branch. Be concrete and short. Facts about the change:\n"
        f"```json\n{json.dumps(facts, indent=1)[:12000]}\n```\nThe diff:\n```diff\n{diff[:60000]}\n```\n"
        "Reply with only a JSON object with these keys:\n"
        '"title": under 70 characters, what this change does;\n'
        '"summary": 2-4 plain sentences on what changed and why;\n'
        '"impact": 1-3 sentences on how it affects the rest of the codebase and its users: behaviour changes, '
        "breaking changes, new dependencies, config or migrations, anything risky. Say so plainly if nothing;\n"
        '"risk": "low", "medium" or "high";\n'
        '"files": an object mapping each changed file path to a one-line note.'
    )
    try:
        proc = subprocess.run(template.format(prompt=shlex.quote(prompt)), shell=True, cwd=store.repo,
                              capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
    except (subprocess.TimeoutExpired, OSError):
        return None
    text = proc.stdout
    start, end = text.find("{"), text.rfind("}")
    if proc.returncode != 0 or start < 0:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    notes = data.pop("files", None)
    if isinstance(notes, dict):
        for f in report["files"]:
            f["note"] = str(notes.get(f["path"], ""))[:200]
    out = {k: str(data[k])[:1500] for k in ("title", "summary", "impact") if data.get(k)}
    if str(data.get("risk", "")).lower() in ("low", "medium", "high"):
        out["risk"] = data["risk"].lower()
    return out
