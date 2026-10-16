"""Conflict prediction: snapshot every agent's worktree, then dry-run merges between them.

Merges run through `git merge-tree --write-tree`, which never touches a worktree or index and uses the
braid code-aware merge driver set up by `braid init`. So "two agents added different functions to the
same file" shows up as a harmless overlap, and only real clashes show up as conflicts.
"""
from itertools import combinations
from pathlib import Path

from . import gitutil


def snapshot_all(store):
    """Snapshot each live agent and pin the snapshot under refs/braid/wip/<agent>."""
    snaps = {}
    for a in store.live_agents():
        wt = a["worktree"]
        if not Path(wt).is_dir():
            continue
        try:
            oid = gitutil.snapshot_worktree(wt)
        except gitutil.GitError:
            continue  # mid-rebase or similar; try again next pass
        gitutil.git("update-ref", f"refs/braid/wip/{a['name']}", oid, cwd=store.repo)
        store.set_snapshot(a["name"], oid)
        snaps[a["name"]] = oid
    return snaps


def predict(store, snaps):
    """Return risks as (a, b, severity, files).

    conflict: git (with the code-aware driver) cannot merge the two as they are now.
    overlap: both touched the same files, but they merge cleanly today.
    b is another agent, or '@<base>' when the agent conflicts with the base branch as it is now.
    """
    repo = store.repo
    bases = {a["name"]: store.agent_base(a) for a in store.live_agents()}
    changed = {name: gitutil.changed_paths(bases[name], oid, cwd=repo) for name, oid in snaps.items()}
    risks = []

    for a, b in combinations(sorted(snaps), 2):
        shared = changed[a] & changed[b]
        if bases[a] != bases[b] or not shared:
            continue  # disjoint files cannot textually conflict; skip the merge
        clean, conflicted = gitutil.merge_preview(snaps[a], snaps[b], cwd=repo)
        risks.append((a, b, "overlap", shared) if clean else (a, b, "conflict", set(conflicted)))

    for name, oid in snaps.items():
        base = bases[name]
        base_oid = gitutil.rev(base, cwd=repo)
        if base_oid:
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
        files_s = ", ".join(sorted(files))
        if b.startswith("@"):
            store.post_note("braid", "conflict",
                            f"Your work conflicts with the {b[1:]} branch in: {files_s}. "
                            "Call sync to bring it in and resolve now, while it's small.", to=a)
        else:
            for me, other in ((a, b), (b, a)):
                store.post_note("braid", "conflict",
                                f"Predicted conflict with {other} in: {files_s}. Read their intents with peers, "
                                f"then agree with them via post_note who changes what.", to=me)
        store.event("conflict", f"predicted with {b} in {files_s}", a)
    for name in snaps:
        store.heartbeat(name)
    return risks, new
