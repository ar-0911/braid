"""Landing: review gate, merge queue, conflict resolution with consensus, tests, and push.

Landing an agent means: merge its branch into the base branch in a private integration worktree
(using the code-aware merge driver and rerere), resolve whatever still conflicts, run the tests,
give the agents involved a chance to object, then move the base branch forward atomically.
"""
import re
import shlex
import subprocess
import time
from pathlib import Path

from . import approve, gitutil

MARKER = re.compile(r"^(<<<<<<<|>>>>>>>)( |$)", re.M)


class LandResult:
    def __init__(self, ok, message, waiting=False):
        self.ok, self.message, self.waiting = ok, message, waiting

    def __repr__(self):
        return f"LandResult(ok={self.ok}, waiting={self.waiting}, {self.message!r})"


def integration_dir(store):
    return store.repo.parent / f"{store.repo.name}.agents" / ".integration"


# ------------------------------------------------------------------ review

def review_gate(store, agent):
    """Return (ok, reason). Peer reviews are recorded per branch head, so new commits need a new review."""
    mode = store.cfg("review.required").lower()
    if mode in ("no", "false", "off", "0"):
        return True, "reviews not required"
    head = gitutil.rev(agent["branch"], cwd=store.repo)
    reviews = [r for r in store.reviews(agent["name"], head) if r["reviewer"] != agent["name"]]
    if reviews and reviews[-1]["verdict"] == "approve":
        return True, f"approved by {reviews[-1]['reviewer']}"
    if reviews and reviews[-1]["verdict"] == "changes":
        return False, f"changes requested by {reviews[-1]['reviewer']}: {reviews[-1]['comment']}"
    if store.cfg("review.command"):
        verdict, comment = auto_review(store, agent)
        store.add_review(agent["name"], "auto-reviewer", head, verdict, comment)
        return (verdict == "approve"), f"auto-reviewer: {verdict}: {comment}"
    if mode in ("yes", "true", "on", "1"):
        return False, "waiting for a review"
    peers = [p["name"] for p in store.agents(("active", "ready"))
             if p["name"] != agent["name"] and store.process_alive(p)]
    if peers:
        return False, f"waiting for a review from a peer ({', '.join(peers)})"
    return True, "no peer available to review"


def auto_review(store, agent):
    base = store.agent_base(agent)
    diff = gitutil.out("diff", f"{base}...{agent['branch']}", cwd=store.repo)[:60000]
    prompt = (f"Review this change for correctness and for breaking other code. Task was: {agent['task']}\n\n"
              f"```diff\n{diff}\n```\n\nEnd your answer with exactly one line: "
              "'VERDICT: approve' or 'VERDICT: changes', preceded by a one-paragraph reason.")
    proc = run_template(store.cfg("review.command"), prompt, cwd=agent["worktree"], timeout=900)
    text = proc.stdout.strip()
    m = re.search(r"VERDICT:\s*(approve|changes)", text, re.I)
    verdict = m.group(1).lower() if m else "changes"
    reason = text[: m.start()].strip().splitlines()[-1] if m and text[: m.start()].strip() else text[-300:]
    return verdict, reason or "no reason given"


# ------------------------------------------------------------------ helpers

def run_template(template, prompt, cwd, timeout, **extra):
    cmd = template.format(prompt=shlex.quote(prompt), **{k: shlex.quote(str(v)) for k, v in extra.items()})
    return subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                          stdin=subprocess.DEVNULL)


def run_tests(store, cwd):
    cmd = store.cfg("test.command")
    if not cmd:
        return True, "no test command configured"
    try:
        proc = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=3600,
                              stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return False, "tests timed out"
    tail = (proc.stdout + proc.stderr)[-3000:]
    return proc.returncode == 0, tail


def prepare_integration(store, base_oid):
    path = integration_dir(store)
    if not (path / ".git").exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        gitutil.git("worktree", "prune", cwd=store.repo)
        gitutil.git("worktree", "add", "--detach", str(path), base_oid, cwd=store.repo)
    else:
        gitutil.git("merge", "--abort", cwd=path, check=False)
        gitutil.git("checkout", "--detach", "-f", base_oid, cwd=path)
        gitutil.git("clean", "-fd", cwd=path)
    return path


def landed_agents_touching(store, since, until, files):
    """Agents whose landings between since..until touched any of files (from Braid-Agent trailers)."""
    names = set()
    for f in files:
        log = gitutil.out("log", "--first-parent", "--format=%(trailers:key=Braid-Agent,valueonly)",
                          f"{since}..{until}", "--", f,
                          cwd=store.repo)
        names |= {n.strip() for n in log.splitlines() if n.strip()}
    return names or {"human"}


def has_markers(path):
    try:
        return bool(MARKER.search(Path(path).read_text(errors="replace")))
    except OSError:
        return False


# ------------------------------------------------------------------ resolution with consensus

def resolve(store, agent, parties, files, cwd):
    """Ask the resolver to fix the remaining conflicts in the integration worktree. Returns (ok, detail)."""
    template = store.cfg("resolve.command")
    if not template:
        return False, "no resolver configured"
    context = []
    for p in sorted(parties | {agent["name"]}):
        a = store.agent(p)
        if a:
            intents = "; ".join(i["description"] for i in store.intents(p)) or "none declared"
            context.append(f"- {p}: task \"{a['task']}\"; intents: {intents}")
    notes = [n for n in store.notes() if n["agent"] in parties | {agent["name"]}][-15:]
    prompt = (
        "You are the neutral resolver for a merge between parallel coding agents. A merge is in progress in "
        "this directory and these files still contain conflict markers:\n"
        + "\n".join(f"- {f}" for f in files)
        + f"\n\n'ours' is the base branch (already contains: {', '.join(sorted(parties))}); 'theirs' is the "
        f"incoming work of {agent['name']}.\nWhat each side was trying to do:\n" + "\n".join(context)
        + ("\n\nTheir recent notes:\n" + "\n".join(f"- {n['agent']}: {n['text']}" for n in notes) if notes else "")
        + "\n\nEdit only those files so that BOTH sides' intent is preserved and the code is correct. Remove every "
        "conflict marker. Do not run git commands, do not commit, and do not touch other files. Finish with "
        "one sentence describing how you combined them."
    )
    try:
        proc = run_template(template, prompt, cwd=cwd, timeout=1800)
    except subprocess.TimeoutExpired:
        return False, "resolver timed out"
    left = [f for f in files if has_markers(Path(cwd) / f)]
    if left:
        return False, f"resolver left conflict markers in {', '.join(left)}"
    gitutil.git("add", "--", *files, cwd=cwd)
    summary = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "resolved"
    return True, summary[:500]


def await_consensus(store, did, parties):
    """Parties may object during the consensus window. Returns (accepted, detail)."""
    window = float(store.cfg("consensus.window") or 0)
    deadline = time.time() + window
    while True:
        votes = store.votes(did)
        objections = [v for v in votes if v["vote"] == "object"]
        if objections:
            return False, "; ".join(f"{v['agent']} objected: {v['reason']}" for v in objections)
        voters = {v["agent"] for v in votes if v["vote"] == "accept"}
        if parties and set(parties) <= voters:
            return True, "all parties accepted"
        if time.time() >= deadline:
            return True, "no objections" + (f" within {int(window)}s" if window else "")
        time.sleep(min(2, max(0.1, deadline - time.time())))


# ------------------------------------------------------------------ land

def land(store, name, push=None):
    with store.lock("land"):
        return _land(store, name, push)


def _land(store, name, push):
    agent = store.agent(name)
    if not agent:
        return LandResult(False, f"no agent named {name}")
    if agent["status"] in ("landed", "done"):
        return LandResult(False, f"{name} is already {agent['status']}")
    repo, base, branch = store.repo, store.agent_base(agent), agent["branch"]
    if Path(agent["worktree"]).is_dir() and not gitutil.is_clean(agent["worktree"]):
        return LandResult(False, f"{name} has uncommitted changes; commit them first", waiting=True)
    base_oid = gitutil.rev(base, cwd=repo)
    head = gitutil.rev(branch, cwd=repo)
    if gitutil.out("rev-list", "--count", f"{base_oid}..{head}", cwd=repo) == "0":
        store.set_status(name, "done", "nothing new to land")
        return LandResult(True, f"{name} has nothing that isn't already on {base}")

    ok, why = review_gate(store, agent)
    if not ok:
        return LandResult(False, why, waiting=True)

    approval = approve.lookup(store, name, head) if approve.required(store) else None
    if approval and approval["status"] == "pending":
        return LandResult(False, approve.waiting_message(approval), waiting=True)
    if approval and approval["status"] == "rejected":
        return _block(store, name, approve.rejection_message(approval))
    if approval and approval["status"] == "failed":
        approval["status"] = "approved"  # you already said yes to this exact work: retry, don't ask again
    if approval and approval["status"] == "approved" and approval["base_oid"] == base_oid:
        return _finish(store, agent, base_oid, approval["proposal_oid"], push, approval)  # exactly what was approved

    integ = prepare_integration(store, base_oid)
    reviewers = [r["reviewer"] for r in store.reviews(name, head) if r["verdict"] == "approve"]
    msg = (f"braid: land {name}\n\n{agent['task']}\n\nBraid-Agent: {name}\n"
           + "".join(f"Reviewed-by: {r}\n" for r in sorted(set(reviewers))))
    rc, _ = gitutil.git("merge", "--no-ff", "-m", msg, branch, cwd=integ, check=False)

    did, parties = None, set()
    if rc != 0:
        files = gitutil.conflicted_files(integ)
        if not files:
            gitutil.git("merge", "--abort", cwd=integ, check=False)
            return LandResult(False, f"merging {name} failed for a reason other than conflicts")
        mb = gitutil.out("merge-base", base_oid, head, cwd=repo)
        parties = landed_agents_touching(store, mb, base_oid, files)
        store.event("resolve", f"conflicts with {', '.join(sorted(parties))} in {', '.join(files)}; resolving", name)
        resolved, detail = resolve(store, agent, parties, files, integ)
        if not resolved:
            gitutil.git("merge", "--abort", cwd=integ, check=False)
            did = store.add_decision(name, parties, files, "escalated", None, detail)
            return _block(store, name, f"could not auto-resolve conflicts in {', '.join(files)} ({detail}). "
                          f"Call sync to merge {base} into your branch and resolve it yourself.")
        gitutil.git("commit", "--no-edit", cwd=integ)
        did = store.add_decision(name, parties, files, "proposed", gitutil.rev("HEAD", cwd=integ), detail)
        for p in parties | {name}:
            store.post_note("braid", "decision",
                            f"Decision #{did}: conflicts between {name} and {', '.join(sorted(parties))} in "
                            f"{', '.join(files)} were resolved: {detail}. Use vote to accept or object.", to=p)

    passed, output = run_tests(store, integ)
    if not passed:
        if did:
            store.decide(did, "rejected", "tests failed on the resolution")
        return _block(store, name, f"tests fail after merging with {base}:\n{output}")

    if did:
        accepted, detail = await_consensus(store, did, [p for p in parties | {name} if p != "human"])
        if not accepted:
            store.decide(did, "rejected", detail)
            return _block(store, name, f"resolution #{did} rejected: {detail}")
        store.decide(did, "accepted")

    new_oid = gitutil.rev("HEAD", cwd=integ)
    # an earlier yes still counts after the base moved, unless landing needed a new conflict resolution
    if approve.required(store) and not (approval and approval["status"] == "approved" and not did):
        a = approve.request(store, agent, base, base_oid, new_oid, (passed, output), sorted(set(reviewers)),
                            store.decision(did)["detail"] if did else None)
        return LandResult(False, approve.waiting_message(a), waiting=True)
    return _finish(store, agent, base_oid, new_oid, push, approval)


def _finish(store, agent, base_oid, new_oid, push, approval=None):
    """Move the base branch to the landed commit and tell everyone."""
    name, base = agent["name"], store.agent_base(agent)
    moved, why = advance_base(store, base, base_oid, new_oid)
    if not moved:
        return LandResult(False, why, waiting=True)  # retried every watcher pass until it can move
    gitutil.git("checkout", "--detach", new_oid, cwd=integration_dir(store), check=False)
    store.set_status(name, "landed")
    store.release_lease(name)
    store.event("land", f"landed on {base} as {new_oid[:10]}", name)
    store.post_note("braid", "landed",
                    f"{name} landed on {base} ({agent['task']}). Everyone else: call sync to pick it up.")
    if approval:
        push = push or store.cfg_bool("approve.push")  # a yes from your phone means land and push
    elif push is None:
        push = store.cfg_bool("push.auto")
    message = f"{name} landed on {base} ({new_oid[:10]})"
    if push:
        pushed, out = push_base(store)
        message += "; pushed" if pushed else f"; push failed: {out}"
    if approval:
        approve.landed(store, approval["id"], message)
    return LandResult(True, message)


def block(store, name, why):
    return _block(store, name, why)


def _block(store, name, why):
    store.set_status(name, "blocked", why.splitlines()[0])
    store.post_note("braid", "blocked", why, to=name)
    return LandResult(False, why)


def advance_base(store, base, old, new):
    """Move the base branch from old to new without clobbering anyone's checkout."""
    for wt in gitutil.worktrees(store.repo):
        if wt.get("branch") == base:
            if not gitutil.is_clean(wt["path"]):
                return False, (f"{base} is checked out with uncommitted changes in {wt['path']}; commit or stash "
                               "them and braid lands it on its next pass")
            rc, _ = gitutil.git("merge", "--ff-only", "-q", new, cwd=wt["path"], check=False)
            return (rc == 0), ("" if rc == 0 else f"{base} moved; try again")
    rc, _ = gitutil.git("update-ref", f"refs/heads/{base}", new, old, cwd=store.repo, check=False)
    return (rc == 0), ("" if rc == 0 else f"{base} moved while landing; try again")


def land_ready(store, push=None):
    """Land every ready agent in the order they became ready. Returns list of (name, LandResult)."""
    results = []
    ready = sorted(store.agents(("ready",)), key=lambda a: a["ready_at"] or 0)
    for a in ready:
        results.append((a["name"], land(store, a["name"], push=False)))
    if push is None:
        push = store.cfg_bool("push.auto")
    if push and any(r.ok for _, r in results):
        push_base(store)
    return results


# ------------------------------------------------------------------ sync and push

def sync(store, name):
    """Merge the latest base into an agent's branch, in its worktree. Returns (ok, message, conflicted_files)."""
    agent = store.agent(name)
    wt = agent["worktree"]
    base = store.agent_base(agent)
    rc, out = gitutil.git("merge", "--autostash", "--no-edit", base, cwd=wt, check=False)
    if rc == 0:
        if agent["status"] == "blocked":
            store.set_status(name, "active", "synced with base")
        return True, out.strip().splitlines()[-1] if out.strip() else "up to date", []
    files = gitutil.conflicted_files(wt)
    if not files:
        return False, out.strip()[-500:], []
    return False, (f"conflicts in {', '.join(files)}; edit them to keep both changes, then git add and "
                   "git commit to finish the merge"), files


def push_base(store, branches=False):
    remote = store.cfg("remote")
    rc, _ = gitutil.git("remote", "get-url", remote, cwd=store.repo, check=False)
    if rc != 0:
        return False, f"no remote named {remote}; add one with: braid remote add {remote} <url>"
    refs = [b for b in store.bases_in_use() if gitutil.rev(b, cwd=store.repo)]
    if branches:
        refs += [a["branch"] for a in store.live_agents()]
    proc = subprocess.run(["git", "push", remote, *refs], cwd=store.repo, capture_output=True, text=True)
    ok = proc.returncode == 0
    detail = (proc.stdout + proc.stderr).strip()
    store.event("push", f"pushed {', '.join(refs)} to {remote}" if ok else f"push failed: {detail[-300:]}")
    return ok, detail or f"pushed {', '.join(refs)} to {remote}"
