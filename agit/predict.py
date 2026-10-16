"""Conflict prediction: snapshot every agent's worktree, then dry-run merges between them."""
from itertools import combinations
from pathlib import Path

from . import gitutil


def snapshot_all(store):
    """Snapshot each active agent and pin the snapshot under refs/agit/wip/<agent>."""
    snaps = {}
    for a in store.agents():
        wt = a["worktree"]
        if not Path(wt).is_dir():
            store.set_status(a["name"], "missing")
            continue
        oid = gitutil.snapshot_worktree(wt)
        gitutil.git("update-ref", f"refs/agit/wip/{a['name']}", oid, cwd=store.repo)
        store.set_snapshot(a["name"], oid)
        snaps[a["name"]] = oid
    return snaps


def predict(store, snaps):
    """Return risks as (a, b, severity, files).

    severity 'conflict': git cannot merge the two snapshots cleanly.
    severity 'overlap': both touched the same files but git merges them cleanly today.
    b is another agent, or '@<base>' when the agent conflicts with the base branch as it is now.
    """
    repo = store.repo
    base = store.base_branch()
    base_oid = gitutil.rev(base, cwd=repo)
    changed = {name: gitutil.changed_paths(base, oid, cwd=repo) for name, oid in snaps.items()}
    risks = []

    for a, b in combinations(sorted(snaps), 2):
        shared = changed[a] & changed[b]
        if not shared:
            continue  # disjoint files can't textually conflict; skip the merge
        clean, conflicted = gitutil.merge_preview(snaps[a], snaps[b], cwd=repo)
        if clean:
            risks.append((a, b, "overlap", shared))
        else:
            risks.append((a, b, "conflict", set(conflicted)))

    if base_oid:
        for name, oid in snaps.items():
            if gitutil.out("merge-base", base_oid, oid, cwd=repo) == base_oid:
                continue  # base hasn't moved since this agent branched
            clean, conflicted = gitutil.merge_preview(oid, base_oid, cwd=repo)
            if not clean:
                risks.append((name, f"@{base}", "conflict", set(conflicted)))
    return risks


def check(store):
    """One full pass: snapshot, predict, publish. Returns (risks, new_conflicts)."""
    before = {(r["a"], r["b"]) for r in store.risks() if r["severity"] == "conflict"}
    snaps = snapshot_all(store)
    risks = predict(store, snaps)
    store.replace_risks(risks)
    new = [r for r in risks if r[2] == "conflict" and (r[0], r[1]) not in before]
    for a, b, _, files in new:
        # Tell both sides through shared notes, so agents hear about it mid-task.
        who = b if not b.startswith("@") else f"the {b[1:]} branch"
        store.post_note("agit", "conflict",
                        f"Predicted conflict between {a} and {who} in: {', '.join(sorted(files))}. "
                        "Coordinate before continuing on these files.")
    for name in snaps:
        store.heartbeat(name)
    return risks, new
