# braid: run several coding agents on one repo

braid (https://github.com/ar-0911/braid) is installed and connected as an MCP server called `braid`. It gives you
`delegate`, `start_agents` and `team_status`. Each agent works in its own branch and worktree. braid reviews,
merges, tests and lands their work on the base branch, and asks me for a yes by email before anything lands.

## When to use it

Use braid when a request splits into parts that can be built at the same time: several features, backend and
frontend, a refactor across many modules, "build X with Y and Z". Also use it whenever I say "use braid",
"delegate this" or "get agents on it".

Don't use it for questions, small fixes, single-file changes, or work where every step depends on the one
before. Do those yourself.

## How to use it

1. Commit (or stash) uncommitted work first. Agents branch from the committed base, so they never see
   uncommitted changes.
2. If the repo has tests and braid doesn't know about them yet, tell braid how to run them before delegating:
   `braid settings test.command "<the repo's test command>"`. Nothing lands unless tests pass.
3. Delegate:
   - `delegate` with a clear `goal` when you want braid to plan the split. Say what done looks like and add any
     constraints (stack, files not to touch, style). For a big feature, pass `base: "feature/<name>"` so the
     work collects there instead of on main.
   - `start_agents` with `tasks` when you've already split it. Make each task self-contained, name the files it
     owns, and avoid two tasks editing the same file.
4. Tell me in one or two lines what you started: the plan's tasks and which branch they land on.
5. Follow up with `team_status` when I ask how it's going, or before you report back.

## While agents are working

- Don't edit the files agents are working on, and don't merge, rebase or push their branches. braid lands
  them in order and pushes after I approve.
- Don't push the base branch yourself during a run.
- If `team_status` shows an agent blocked, or an open conflict decision, tell me what it's stuck on. Don't
  fix it in its branch yourself.
- Approvals come to me by email (`braid approvals` lists them; `braid approve <id>` also works). Don't
  approve on my behalf.

## If something's missing

- No `braid` tools in this session: tell me to run `braid connect --scope user`, then restart Claude Code.
- "not in a git repo": braid only works inside a git repo. Ask me before running `git init`.
- Useful commands for me: `braid status`, `braid feed` (activity), `braid approvals`, `braid doctor`.
