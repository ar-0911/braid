# Agentic Version Control: research and proposed design

_2026-10-16. Research only; no repository attached yet._

## TL;DR

- **Don't fork git.** Git already has every low-level primitive we need: a shared content-addressed object store, cheap worktrees, and a merge engine that can run headless (`git merge-tree --write-tree`) without touching anyone's files. The missing piece is a **coordination daemon** that sits above git.
- **Pieces of this exist online, but nobody ships the whole loop.** There are tools for file leases + messaging (MCP Agent Mail), conflict prediction across worktrees (Clash, git-kura), and smarter merging (Weave, Mergiraf, jj). None of them combine *continuous prediction + shared memory + automatic negotiated resolution + push*.
- **Build first:** a small local daemon (`agit`) that snapshots every agent's worktree every few seconds, runs pairwise `git merge-tree` against every other agent and against `main`, and publishes the result to a shared SQLite store that agents read and write through an MCP server. Consensus/auto-resolution comes second, on top of that signal.

---

## 1. What we can take from git's implementation

I checked these against git 2.43 in a sandbox (demo at the end of this section).

| Git piece | What it is internally | How we use it |
|---|---|---|
| **Object store** (`.git/objects`, blobs/trees/commits addressed by hash) | Immutable, deduplicated, safe for many concurrent writers (objects are written to temp files then renamed). | All agents share **one** object store. Every agent snapshot is just new objects; no copying, near-free. |
| **Worktrees** (`git worktree add`) | Extra working dirs + their own `HEAD` and index, sharing the object store and refs. | One worktree per agent, so agents never step on each other's files. This solves your "only one branch at a time" problem today. |
| **`git merge-tree --write-tree A B`** | The modern `ort` merge engine run in memory. Outputs a merged tree OID, the list of conflicted files, and exit code 0 (clean) / 1 (conflict). Never touches a worktree or index; works in a bare repo. | **The core conflict predictor.** Run it continuously between every pair of agent branches and against `main`. |
| **Temporary index trick** (`GIT_INDEX_FILE=… git add -A && git write-tree`, then `git commit-tree`) | Builds a tree/commit from files on disk without disturbing the agent's real index. | Snapshot an agent's **uncommitted** work so we predict conflicts *before* they commit, not at merge time. |
| **Refs / namespaces** (`refs/…`, `update-ref` with old-value check) | Atomic compare-and-swap on a pointer. | Store snapshots under `refs/agents/<name>/wip` so they are visible to every agent and to tooling, and use CAS as a cheap lock for "who lands on main next". |
| **`git notes`** | Arbitrary metadata attached to commits, stored as git objects. | Optional: attach "why" / intent / review verdicts to commits so memory travels with history. |
| **Hooks** (`pre-commit`, `pre-push`, `reference-transaction`) | Scripts git runs at key moments. | `pre-commit` refuses commits that touch files another agent holds a lease on; `reference-transaction` notifies the daemon instantly when any branch moves. |
| **`rerere`** (reuse recorded resolution) | Records how a conflict hunk was resolved and replays it next time. | Once agents agree on a resolution, rerere makes it stick across rebases. |
| **Custom merge drivers** (`.gitattributes merge=…`) | Plug a different merge algorithm per file type. | Plug in a structural (AST) merger so "two agents added different functions to the same file" stops being a conflict. |
| **`git rebase --update-refs`, `range-diff`** | Stack-aware rebasing; compare two versions of a patch series. | Keeping agent branches fresh on `main`; reviewers see exactly what changed between revisions. |

Sandbox demo (`git merge-tree` as predictor):

```
two agents edit the same line        -> exit=1, "CONFLICT (content): Merge conflict in m.py"
agents edit different functions      -> exit=0, clean merged tree OID
agent A's *uncommitted* edit vs B    -> exit=1, detected via temp-index snapshot, A's index untouched
```

### What's worth borrowing from other VCSs

- **Jujutsu (jj)**, git-compatible: the working copy *is* a commit (auto-snapshotted), conflicts are stored as first-class objects instead of blocking the operation, and every operation is in an undoable op log. These are exactly the semantics agents want. We copy the ideas (auto-snapshot, "conflicted but keep going", op log) rather than depending on jj, which still warns about on-disk format changes before 1.0.
- **Structural merge**: [Weave](https://github.com/Ataraxy-Labs/weave) (tree-sitter merge driver for git; reported 31/31 clean merges vs git's 15/31 on its benchmark) and Mergiraf do entity-level merges. Plugging one in as a merge driver removes a big class of false conflicts.

## 2. Does a shared-memory solution already exist?

Partially. What I found:

| Tool | What it does | Gap vs. what you want |
|---|---|---|
| [MCP Agent Mail](https://github.com/dicklesworthstone/mcp_agent_mail) | Agent identities, inbox/threads, **advisory file reservations (leases)** with a pre-commit guard, web UI. Git for audit trail + SQLite for queries. | Closest match for the "shared memory + see what others do" half. No conflict prediction, no resolution. |
| Clash (open source, early; [Product Hunt](https://hunted.space/product/clash-5)) | Watches worktrees and flags overlapping edits before merge; hooks into Claude Code. | Detects, doesn't negotiate or resolve. |
| [git-kura](https://pkg.go.dev/github.com/tooppoo/git-kura) | One keyed worktree per task + "path seals" (claims) checked by a pre-commit hook. | Claims are path-level only; no messaging or resolution. |
| [agent-traffic-control](https://github.com/wan-huiyan/agent-traffic-control) | Claim-a-task-and-file-scope protocol. | Convention, not a system. |
| [mcp-agent-memory](https://github.com/justanotherspy/mcp-agent-memory) | Shared JSON key/value notes over MCP with file locking. | Generic notes; no notion of code, branches, or conflicts. |
| Claude Code agent teams | Shared task list, mailbox between teammates, per-agent worktree isolation. | Coordination exists, but merging is still left to the end; guidance is "give each agent its own files". |

Why it matters: a 2026 study of 33,596 agent PRs found agent PRs overlap in time constantly, and conflicts between *different* agents happened at ~2x the rate of same-agent ones (41.7% vs 19.8% of replayed merges); 27% of agent PRs conflicted in a larger dataset ([summary](https://codex.danielvaughan.com/2026/07/28/agent-pr-merge-conflicts-concurrent-coding-agents-codex-cli-worktree-isolation-coordination-defence/)). Detecting late is the expensive part.

**Conclusion:** we should build the coordinator, and either reuse MCP Agent Mail for messaging/leases or copy its design (Git for durable log, SQLite for live state). Nothing does continuous prediction + consensus.

## 3. Proposed architecture

```
                 you:  agit run "auth" "billing" "search"
                                   |
                     +-------------v--------------+
                     |   agitd (local daemon)     |
                     |  - snapshotter (every Ns)  |
                     |  - predictor (merge-tree)  |
                     |  - arbiter (consensus)     |
                     |  - integrator (merge queue)|
                     +--+-----------+----------+--+
            MCP tools   |           |          |  git refs/hooks
     +------------------v-+   +-----v-----+  +-v----------------------+
     | shared memory      |   | one .git  |  | worktrees              |
     | (SQLite + git log) |   | objects + |  | wt/auth  wt/billing ...|
     +--------------------+   | refs      |  | agent per worktree     |
                              +-----------+  +------------------------+
```

### 3.1 Shared memory (the "blackboard")

One SQLite file (WAL mode, safe for many local readers/writers), exposed to every agent as MCP tools. Durable events also appended to a git ref (`refs/agit/log`) so history is auditable and survives the daemon.

Tables:
- `agents(name, branch, worktree, task, status, heartbeat)`
- `intents(agent, paths/globs, symbols, description)` — what I *plan* to touch, declared up front
- `leases(agent, path_or_symbol, kind[soft|hard], expires_at)`
- `snapshots(agent, commit_oid, at)` — latest WIP snapshot
- `risks(agent_a, agent_b, files, symbols, score, kind[predicted|actual], at)`
- `decisions(id, conflict, proposal, votes, outcome)` — the consensus record
- `notes(agent, topic, text)` — findings other agents should know ("API X now returns a list")

MCP tools agents get: `whoami`, `declare_intent`, `acquire_lease`, `peers()` (what others are doing), `risks()` (who I'm about to collide with), `post_note` / `read_notes`, `propose_resolution`, `vote`, `ready_to_land`.

### 3.2 Conflict prediction (continuous)

Every few seconds, or instantly on a `reference-transaction` hook:
1. Snapshot each agent worktree with the temp-index trick into `refs/agents/<name>/wip`.
2. For every pair (A, B) and for (A, main): `git merge-tree --write-tree --name-only`. That's O(n²) but each run is milliseconds for typical repos; skip pairs whose changed-path sets don't intersect (`git diff --name-only` first).
3. Score each pair: textual conflict (hard), same file different hunks (soft), same symbol via tree-sitter (soft+), touches high-risk zones like lockfiles, migrations, shared types (configurable).
4. Write to `risks` and push a message to both agents' inboxes so they find out **mid-task**, not at merge.

### 3.3 Resolution by auto-consensus

Escalating ladder; most cases stop at step 1 or 2:

1. **Avoid.** Intents and soft leases are checked when an agent starts a subtask. If someone else already owns `auth/session.ts`, the agent reads their note and works around it, or asks.
2. **Mechanical merge.** Structural merge driver + `rerere`. If `merge-tree` is clean after that, no conversation needed.
3. **Negotiate (the consensus step).** For a real conflict between A and B:
   - The arbiter opens a `decision` with both diffs, both agents' intents, and the merge-base.
   - Each agent proposes a resolution (a resolved tree), or concedes.
   - A **third, uninvolved reviewer agent** checks proposals by actually building the merged tree in a scratch worktree and running tests.
   - Rule: pick the proposal that passes tests; ties go to whichever branch *lands first* on main (the other rebases). Agreement = both parties accept, or reviewer + one party. Fixed round limit (e.g. 2) so it never loops.
4. **Escalate.** If no proposal passes tests within the limit, mark the conflict first-class (jj-style: recorded, not blocking), the losing agent keeps working on other parts, and you get one notification with the two options.

Why this works as "consensus": tests are the objective judge, the reviewer is a tie-breaker with no stake, and a deterministic fallback rule (land order) guarantees progress.

### 3.4 Cross-checking and push (integrator)

- When an agent calls `ready_to_land`, another agent reviews the diff (`range-diff` against the last reviewed version) and records a verdict in `decisions`/notes.
- A local **merge queue**: rebase onto latest main, run tests, fast-forward main with `git update-ref` compare-and-swap (atomic, so two agents can't land at once), then push. Other agents' branches are then auto-rebased and their risks recomputed.

### 3.5 The one command

```
agit run "add OAuth login" "billing export" "search filters"
```
creates a worktree + branch per task, starts an agent in each with the MCP server attached, and starts `agitd`. `agit status` shows each agent, its task, current risks and pending decisions. `agit land` drains the merge queue.

## 4. What to build first

**Milestone 1: the predictor + blackboard (worth having on its own).**
1. `agit run` that creates worktrees and launches N Claude Code agents, one per task.
2. `agitd` snapshotter + pairwise `git merge-tree` predictor writing to SQLite.
3. An MCP server with `peers`, `risks`, `declare_intent`, `post_note`, `read_notes`.
4. A `pre-commit` hook that warns on lease overlap.

That alone gives agents shared memory and early warnings, and it's small (a few hundred lines; Python or TypeScript). It needs a repo to live in and a test repo to run agents against.

**Milestone 2:** structural merge driver + rerere, then the consensus arbiter with the reviewer agent and test-based judging.

**Milestone 3:** merge queue with CAS on main, auto-rebase of the remaining agents, push.

Decision to make before coding: reuse MCP Agent Mail for messaging/leases (faster start, Python, extra dependency) or write our own small blackboard (one schema that also holds risks and decisions). My recommendation is our own, since risks and decisions are the core and they don't fit Agent Mail's model, but borrowing its layout (git for the log, SQLite for live state).
