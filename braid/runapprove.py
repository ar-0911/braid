"""approve.mode run: agents land on a staging branch (braid-run/<base>) and the whole run asks for one yes.

When nothing is left working on a staging branch, the combined change goes out as a single approval
(summary, diff, review page, tests). Yes moves the base branch to it and pushes; no keeps the staging
branch for you to look at.
"""
from . import approve, gitutil
from .store import RUN_PREFIX


def _runs(store):
    """Staging branches that exist, as (staging, base)."""
    out = gitutil.out("for-each-ref", "--format=%(refname:short)", f"refs/heads/{RUN_PREFIX}", cwd=store.repo)
    return [(s, s[len(RUN_PREFIX):]) for s in out.splitlines() if s]


def _busy(store, staging, base):
    if any(store.agent_base(a) == staging for a in store.live_agents()):
        return True
    return any((p["base"] or store.base_branch()) == base for p in store.plans("running"))


def _landed_agents(store, staging, base):
    """Agents whose work is on staging but not yet on base."""
    found = []
    for a in store.agents(("landed",)):
        head = gitutil.rev(a["branch"], cwd=store.repo)
        if not head or (a.get("base") or store.base_branch()) != base:
            continue
        on_staging = gitutil.git("merge-base", "--is-ancestor", head, staging, cwd=store.repo, check=False)[0] == 0
        on_base = gitutil.git("merge-base", "--is-ancestor", head, base, cwd=store.repo, check=False)[0] == 0
        if on_staging and not on_base:
            found.append(a)
    return found


def _catch_up(store, staging, base):
    """Merge commits that reached base directly (someone pushed) into staging. Returns an error or ''."""
    repo = store.repo
    if gitutil.git("merge-base", "--is-ancestor", base, staging, cwd=repo, check=False)[0] == 0:
        return ""
    rc, tree = gitutil.git("merge-tree", "--write-tree", staging, base, cwd=repo, check=False)
    if rc != 0:
        return f"{base} changed underneath this run and conflicts with it; merge {base} into {staging} by hand"
    head = gitutil.rev(staging, cwd=repo)
    new = gitutil.out("commit-tree", tree.split()[0], "-p", head, "-p", gitutil.rev(base, cwd=repo),
                      "-m", f"Merge {base} into {staging}", cwd=repo)
    gitutil.git("update-ref", f"refs/heads/{staging}", new, head, cwd=repo)
    return ""


def check(store):
    """Ask once for every finished run that hasn't been asked about. Returns messages for the feed."""
    if not (approve.required(store) and store.cfg("approve.mode") == "run"):
        return []
    approve.ensure(store)
    messages = []
    for staging, base in _runs(store):
        if not gitutil.rev(base, cwd=store.repo) or _busy(store, staging, base):
            continue
        err = _catch_up(store, staging, base)
        if err:
            if store.get_meta(f"runwait.{staging}") != err:
                store.set_meta(f"runwait.{staging}", err)
                store.event("wait", err, f"run:{base}")
            continue
        base_oid, new_oid = gitutil.rev(base, cwd=store.repo), gitutil.rev(staging, cwd=store.repo)
        if base_oid == new_oid:
            continue
        name = f"run:{base}"
        prior = store.db.execute(
            "SELECT id, status FROM approvals WHERE agent=? AND proposal_oid=? AND base_oid=? "
            "AND status IN ('pending', 'approved', 'rejected') ORDER BY id DESC LIMIT 1",
            (name, new_oid, base_oid)).fetchone()
        if prior:
            continue
        agents = _landed_agents(store, staging, base)
        tasks = [a["task"] for a in agents] or [f"everything on {staging}"]
        pseudo = {"name": name, "branch": staging, "summary": "",
                  "task": tasks[0] if len(tasks) == 1 else "; ".join(f"({i}) {t}" for i, t in enumerate(tasks, 1))}
        ran = bool(store.cfg("test.command"))
        tests = (True, "every landing in this run passed its tests; the last one ran on this combined result"
                 if ran else "")
        a = approve.request(store, pseudo, base, base_oid, new_oid, tests, [])
        messages.append(f"the run on {base} is done ({len(agents)} agent{'s' * (len(agents) != 1)}): "
                        + approve.waiting_message(a))
    return messages


def apply(store, aid):
    """A yes on a whole run: move base to the staging head we showed, push, and clear staging."""
    from . import land
    a = approve.get(store, aid)
    base = a["report"]["base"]
    staging = RUN_PREFIX + base
    if gitutil.rev(base, cwd=store.repo) != a["base_oid"]:
        approve._set(store, aid, status="failed", result=f"{base} moved since you were asked; braid will ask again")
        approve._report_back(store, aid)
        return approve.get(store, aid), approve.get(store, aid)["result"]
    moved, why = land.advance_base(store, base, a["base_oid"], a["proposal_oid"])
    if not moved:  # e.g. uncommitted changes where base is checked out; the watcher retries
        approve._set(store, aid, result=why)
        approve._report_back(store, aid)
        return approve.get(store, aid), why
    store.event("land", f"run landed on {base} as {a['proposal_oid'][:10]}", a["agent"])
    message = f"the run landed on {base} ({a['proposal_oid'][:10]})"
    if store.cfg_bool("approve.push"):
        pushed, out = land.push_base(store)
        message += "; pushed" if pushed else f"; push failed: {out}"
    if gitutil.rev(staging, cwd=store.repo) == a["proposal_oid"]:
        gitutil.git("branch", "-D", staging, cwd=store.repo, check=False)
    approve.landed(store, aid, message)
    return approve.get(store, aid), message


def rejected(store, aid):
    a = approve.get(store, aid)
    staging = RUN_PREFIX + a["report"]["base"]
    note = f"kept on {staging} for you to look at; delete that branch to drop the run"
    approve._set(store, aid, result=note)
    approve._report_back(store, aid)
    store.event("approval", f"run sent back: {note}", a["agent"])
    return approve.get(store, aid), f"#{a['id']} not landed; {note}"


def retry_approved(store):
    """Runs that were approved but couldn't land yet (dirty checkout of base). Returns messages."""
    out = []
    for a in approve.all_approvals(store, "approved"):
        if approve.is_run(a):
            before = a["result"]
            _, msg = apply(store, a["id"])
            if msg != before:
                out.append(msg)
    return out
