# agit

Run several coding agents on one repo at the same time. Each gets its own branch and worktree; all of them share a memory and get warned about merge conflicts **while they are still working**, not at merge time.

Milestone 1 of the design in [`../README.md`](../README.md). Python 3.10+, git 2.38+, no other dependencies.

## Quick start

```sh
# from inside any git repo
export PYTHONPATH=/path/to/agit        # or: alias agit='PYTHONPATH=/path/to/agit python3 -m agit'
python3 -m agit init                   # records base branch, installs pre-commit lease check
python3 -m agit run "add OAuth login" "billing CSV export" --launch
python3 -m agit watch                  # keep conflict predictions fresh (another terminal)
python3 -m agit status                 # agents, leases, predicted conflicts, recent notes
```

Without `--launch`, `run` prints the `claude` command to start each agent yourself (interactive).

## What happens

- `run` creates branch `agent/<name>` and worktree `<repo>.agents/<name>` per task, registers the agent, and writes an MCP config so that agent's Claude Code session gets the `agit` tools under its own identity.
- `watch` / `check` / the `risks` tool snapshot every worktree (including **uncommitted** edits, via a throwaway index, so nothing in the agent's checkout changes), then dry-run merges between every pair of agents and against the base branch with `git merge-tree --write-tree`. Results:
  - `CONFLICT`: git cannot merge these two as they are now.
  - `OVERLAP`: same files touched, but they merge cleanly today.
  - New conflicts are posted as notes, so both agents read about them mid-task.
- The pre-commit hook blocks a commit that touches a file another agent holds a **hard** lease on, and warns on soft leases.

## Agent tools (MCP)

| tool | purpose |
|---|---|
| `whoami` | own name, branch, worktree, task |
| `peers` | other agents with their tasks, declared intents and leases |
| `risks` | fresh conflict/overlap prediction for me |
| `declare_intent` | files/globs I plan to change, and why |
| `acquire_lease` / `release_lease` | claim files (soft = signal, hard = blocks others' commits) |
| `post_note` / `read_notes` | shared notes: API changes, agreements, conflict alerts |

## Where state lives

`<repo>/.git/agit/state.db` (SQLite, shared by all worktrees), WIP snapshots under `refs/agit/wip/<agent>`, agent configs/prompts/logs under `.git/agit/`.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

## Not yet (next milestones)

Structural (AST) merge driver + rerere, automatic negotiation/consensus with a reviewer agent and test-based judging, merge queue that lands to the base branch and pushes.
