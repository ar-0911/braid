"""Conflict prediction: snapshot every agent's worktree, then dry-run merges between them.

Merges run through `git merge-tree --write-tree`, which never touches a worktree or index and uses the
braid code-aware merge driver set up by `braid init`. So "two agents added different functions to the
same file" shows up as a harmless overlap, and only real clashes show up as conflicts.
"""
from itertools import combinations
from pathlib import Path

from . import gitutil, regen, semantic, spelunk

_seen = {}  # worktree -> (fingerprint, snapshot oid), so an untouched worktree isn't snapshotted again

SEVERITY = {"conflict": 3, "semantic": 2, "overlap": 1}


def snapshot_all(store):
    """Snapshot each live agent and pin the snapshot under refs/braid/wip/<agent>."""
    snaps = {}
    for a in store.live_agents():
        wt = a["worktree"]
        if not Path(wt).is_dir():
            continue
        fp = gitutil.worktree_fingerprint(wt)
        prev = _seen.get(wt)
        if fp and prev and prev[0] == fp:
            snaps[a["name"]] = prev[1]  # nothing changed since the last pass
            continue
        try:
            oid = gitutil.snapshot_worktree(wt)
        except gitutil.GitError:
            continue  # mid-rebase or similar; try again next pass
        _seen[wt] = (fp, oid)
        if not prev or prev[1] != oid:
            gitutil.git("update-ref", f"refs/braid/wip/{a['name']}", oid, cwd=store.repo)
            store.set_snapshot(a["name"], oid)
        snaps[a["name"]] = oid
    return snaps


def _add(found, a, b, severity, files):
    """Keep the most severe risk per pair; merge the file lists of equally severe ones."""
    key = (a, b) if (a, b) in found or (b, a) not in found else (b, a)
    cur = found.get(key)
    if not cur or SEVERITY[severity] > SEVERITY[cur[0]]:
        found[key] = (severity, set(files))
    elif cur[0] == severity:
        cur[1].update(files)


def predict(store, snaps):
    """Return risks as (a, b, severity, files).

    conflict: git (with the code-aware driver) cannot merge the two as they are now.
    overlap: both touched the same files, but they merge cleanly today.
    semantic: one side removed or renamed a function/class that the other side's new code still uses, or
    the two merge cleanly but the tests fail on the merged result (see test_merges).
    b is another agent, or '@<base>' when the agent conflicts with the base branch as it is now.
    """
    repo = store.repo
    bases = {a["name"]: store.agent_base(a) for a in store.live_agents()}
    changed = {name: gitutil.changed_paths(bases[name], oid, cwd=repo) for name, oid in snaps.items()}
    rules = regen.rules(store)
    parser = spelunk.parser(store)
    found = {}

    for a, b in combinations(sorted(snaps), 2):
        if bases[a] != bases[b]:
            continue
        for remover, user in ((a, b), (b, a)):
            hits = semantic.broken_uses(bases[a], snaps[remover], snaps[user], repo, parser)
            if hits:
                _add(found, a, b, "semantic", semantic.describe(hits))
        shared = changed[a] & changed[b]
        if not shared:
            continue  # disjoint files cannot textually conflict; skip the merge
        _, clean, conflicted = gitutil.merge_result(snaps[a], snaps[b], repo)
        conflicted = set(conflicted) - regen.generated(conflicted, rules)  # those get rebuilt at landing
        if conflicted:
            _add(found, a, b, "conflict", conflicted)
            continue
        _add(found, a, b, "overlap", shared)
        failed = store.get_meta(f"predict.mergefail.{a}.{b}")  # set by test_merges for the current commits
        if failed and not failed.startswith("ok:"):
            ha, hb = (gitutil.rev(store.agent(n)["branch"], cwd=repo) for n in (a, b))
            if gitutil.merge_result(ha, hb, repo)[0] == failed:
                _add(found, a, b, "semantic", ["tests fail when merged"])

    for name, oid in snaps.items():
        base = bases[name]
        base_oid = gitutil.rev(base, cwd=repo)
        if not base_oid:
            continue
        mb = gitutil.out("merge-base", base_oid, oid, cwd=repo)
        if mb == base_oid:
            continue  # base hasn't moved since this agent branched
        _, clean, conflicted = gitutil.merge_result(oid, base_oid, repo)
        conflicted = set(conflicted) - regen.generated(conflicted, rules)
        if conflicted:
            _add(found, name, f"@{base}", "conflict", conflicted)
            continue
        hits = semantic.hits_between(mb, base_oid, mb, oid, repo, parser)
        if hits:
            _add(found, name, f"@{base}", "semantic", semantic.describe(hits))
    return [(a, b, sev, files) for (a, b), (sev, files) in found.items()]


def test_merges(store, budget=2):
    """Run the tests on the merged commits of agents whose work overlaps but merges cleanly.

    This catches conflicts no text check can, like a changed return type. It uses committed work only
    (half-typed files would fail on their own), and a failure counts only when both sides pass on their
    own, so it points at the combination. Results are cached by tree, so nothing is tested twice.
    Runs at most `budget` test suites per call. Returns [(a, b, merged_passed)].
    """
    from . import land
    if not store.cfg("test.command") or not store.cfg_bool("predict.tests"):
        return []
    repo, ran, spent = store.repo, [], [0]
    heads = {}
    for a in store.agents(("active", "ready")):
        base_oid, head = gitutil.rev(store.agent_base(a), cwd=repo), gitutil.rev(a["branch"], cwd=repo)
        if head and base_oid and head != base_oid and gitutil.out("merge-base", base_oid, head, cwd=repo) != head:
            heads[a["name"]] = (store.agent_base(a), head)

    def tested(tree, parents):
        cached = store.get_meta(f"predict.tests.{tree}")
        if cached is None:
            if spent[0] >= budget:
                return None
            spent[0] += 1
            passed, output = land.run_tests_on_tree(store, tree, parents)
            cached = "pass" if passed else (output[-1500:] or "fail")
            store.set_meta(f"predict.tests.{tree}", cached)
        return cached

    for a, b in combinations(sorted(heads), 2):
        (base_a, ha), (base_b, hb) = heads[a], heads[b]
        if base_a != base_b or land.base_tests_red(store, base_a):
            continue
        if not (gitutil.changed_paths(base_a, ha, cwd=repo) & gitutil.changed_paths(base_b, hb, cwd=repo)):
            continue
        tree, clean, _ = gitutil.merge_result(ha, hb, repo)
        key = f"predict.mergefail.{a}.{b}"
        if not clean or store.get_meta(key) in (tree, f"ok:{tree}"):
            continue
        merged = tested(tree, [ha, hb])
        if merged is None:
            break
        if merged == "pass":
            store.set_meta(key, f"ok:{tree}")
            ran.append((a, b, True))
            continue
        alone = [tested(gitutil.out("rev-parse", f"{h}^{{tree}}", cwd=repo), [h]) for h in (ha, hb)]
        if None in alone:
            break
        if alone != ["pass", "pass"]:
            store.set_meta(key, f"ok:{tree}")  # one side is broken by itself; that's its own problem
            continue
        store.set_meta(key, tree)
        ran.append((a, b, False))
        for me, other in ((a, b), (b, a)):
            store.post_note("braid", "conflict",
                            f"Your committed work and {other}'s each pass the tests and merge cleanly, but the "
                            f"tests fail on the combination. Talk to {other} with post_note. Test output:\n"
                            f"{merged[-1500:]}", to=me)
        store.event("conflict", f"tests fail when merged with {b}", a)
    return ran


def check(store):
    """One full pass: snapshot, predict, publish. Returns (risks, new_conflicts)."""
    before = {(r["a"], r["b"], r["severity"]) for r in store.risks() if r["severity"] in ("conflict", "semantic")}
    snaps = snapshot_all(store)
    risks = predict(store, snaps)
    store.replace_risks(risks)
    new = [r for r in risks if r[2] in ("conflict", "semantic") and (r[0], r[1], r[2]) not in before]
    for a, b, sev, files in new:
        files_s = ", ".join(sorted(files))
        if sev == "semantic":
            if files_s == "tests fail when merged":
                continue  # test_merges already told them, with the output
            where = f"the {b[1:]} branch" if b.startswith("@") else b
            what = ("changed the parameters of a function the other side calls" if "whose parameters changed" in files_s
                    and " uses " not in files_s else "removed or renamed a name the other side still uses")
            text = (f"Likely semantic conflict with {where}: one side {what} ({files_s}). The text merges, but the "
                    f"code would break. ")
            text += ("Call sync and update your code to match." if b.startswith("@") else
                     "Agree with them via post_note who adapts.")
            for me in ((a,) if b.startswith("@") else (a, b)):
                store.post_note("braid", "conflict", text, to=me)
        elif b.startswith("@"):
            store.post_note("braid", "conflict",
                            f"Your work conflicts with the {b[1:]} branch in: {files_s}. "
                            "Call sync to bring it in and resolve now, while it's small.", to=a)
        else:
            for me, other in ((a, b), (b, a)):
                store.post_note("braid", "conflict",
                                f"Predicted conflict with {other} in: {files_s}. Read their intents with peers, "
                                f"then agree with them via post_note who changes what.", to=me)
        store.event("conflict", f"predicted {sev} with {b} in {files_s}", a)
    for name in snaps:
        store.heartbeat(name)
    return risks, new
