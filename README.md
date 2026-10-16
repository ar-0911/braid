# braid

**Run many coding agents on one repo at once, and braid their work back together.**

```sh
braid start "add OAuth login" "billing CSV export" "search filters"
```

Each task gets its own agent, branch and worktree. The agents share a memory, see what the others are doing, get warned about merge conflicts *while they are still typing*, review each other's work, and braid lands it on `main`: merging code-aware, resolving what still clashes, running your tests, and pushing when you say so. Everything else is plain git: `braid commit`, `braid log`, `braid rebase` just run git.

Or give it one goal: `braid do "build X"` plans the work, splits it across agents in dependency order, and lands it, on `main` or on a feature branch.

- No dependencies beyond Python 3.10+ and git 2.38+.
- Agents are [Claude Code](https://claude.com/claude-code) sessions by default; any CLI agent can be plugged in.
- All state lives inside your repo's `.git/`; nothing is uploaded anywhere.

---

## Install

```sh
pip install git+https://github.com/ar-0911/braid   # or, from a checkout: pip install .
braid doctor                                          # checks git, python, the agent CLI
```

## Use it

```sh
cd my-project
braid init --test "pytest -q"      # once: merge driver, hooks, rerere, test gate
braid start "task one" "task two"  # launches agents + the background watcher
braid status --live                # who's doing what, predicted conflicts, decisions
braid feed -f                      # live activity feed
braid ship                         # land everything that's ready, then push
```

That's the whole loop. While agents work, the watcher lands each one as soon as it is reviewed and its tests pass.

### One goal, many agents: `braid do`

```sh
braid do "build a notes app: storage module, CLI, tests"
```

A planner agent reads the repo and splits the goal into tasks, each owning a set of files and naming the tasks it depends on. braid shows the plan as waves and asks before starting. Every task whose dependencies have landed starts at once, in parallel; when a task lands, the tasks waiting on it start from the updated code, so they build on what really exists. `braid plans` shows progress. Flags: `--yes` (no prompt), `--base feature/x`, `--max-agents N`, `--push` (push when every task landed), `--plan-file plan.json` (run a plan you edited; each plan is saved in `.git/braid/plans/`).

### Big features off main: `--base`

```sh
braid do --base feature/checkout "checkout flow: cart API, payment service, UI"
braid start --base feature/checkout "order emails"
```

Every agent has its own base branch. braid creates the branch from your current base if it doesn't exist, agents branch from it, conflicts are only predicted between agents on the same base, and work lands on `feature/checkout`, never `main`. When the feature is done, merge or PR it to `main` as one unit.

### Approve landings from your phone: WhatsApp, Telegram or email

```sh
braid settings approve.required yes
braid settings approve.channels cloudflare         # any of: cloudflare, whatsapp, telegram, email, command
braid approvals test                               # sends a test message on each channel
```

Now nothing lands until you say yes. Once an agent's work has passed review, conflict resolution and tests, braid stops just before moving the base branch and messages you:

- a summary of what changed and **how it affects you** (written by `approve.summary_command`, Claude by default, with a built-in fallback), which functions changed and where else they're used, the risk, and the test results;
- the diff itself when it's small (`approve.inline_diff_lines`, default 40), otherwise a link to a **review page** with all of that plus the full, colored diff and **Land it** / **Send back** buttons.

Reply `YES` (or `NO` and a reason), tap the button, or run `braid approve` / `braid reject -m "why"`. A yes lands exactly the merge commit you were shown and pushes it (`approve.push`). A no sends the work back to its agent with your reason, and the watcher relaunches it to fix it.

| channel | you need | set up |
|---|---|---|
| **Cloudflare** (recommended) | a Cloudflare account and a domain on it (free plan) | deploy [cloudflare/](cloudflare/README.md) once; it hosts the review pages, emails you and takes your reply, nothing exposed on your machine |
| WhatsApp | a [Twilio](https://www.twilio.com/console) account (free trial; join the WhatsApp sandbox from your phone) | `braid approvals secret TWILIO_ACCOUNT_SID`, `braid approvals secret TWILIO_AUTH_TOKEN`, `braid settings approve.whatsapp.to +447700900123` |
| Telegram | a bot from @BotFather (free) | `braid approvals secret BRAID_TELEGRAM_TOKEN`, message the bot, `braid approvals telegram-id` |
| email | an SMTP/IMAP login, e.g. a Gmail [app password](https://myaccount.google.com/apppasswords) | `braid settings approve.email.to you@x.com`, `braid settings approve.email.user you@gmail.com`, `braid approvals secret BRAID_SMTP_PASSWORD` |
| anything else | a command | `braid settings approve.command "curl -d {message} ntfy.sh/my-topic"` |

Set it up once for every repo with `--global` (stored in `~/.config/braid`, secrets mode 600); a repo's own settings still win:

```sh
braid settings --global approve.required yes
braid settings --global approve.channels cloudflare
braid settings --global approve.cloudflare.url https://braid-approvals.<you>.workers.dev
braid approvals secret --global BRAID_RELAY_KEY
```

Replies are read by polling (the Worker, Twilio's message log, Telegram's getUpdates, IMAP), so nothing on the internet needs to reach your machine to get the yes. With the Cloudflare channel the review page lives on your Worker. Otherwise it is served by the watcher on `approve.port` (8765). To open it from your phone, set `approve.tunnel cloudflared` (free `https://…trycloudflare.com` link, no account; install `cloudflared`) or point `approve.public_url` at your own Tailscale/ngrok address. Every link carries a secret token. Without either, emails attach the review page and messages say to run `braid approvals show <id>`.

WhatsApp note: Twilio only delivers free-form messages within 24 hours of your last message to it (sandbox included). For approvals at any time, create a WhatsApp template in Twilio with variables `{{1}}` title, `{{2}}` summary, `{{3}}` link, `{{4}}` reply code and set `approve.whatsapp.content_sid`, or use Telegram or email, which have no such window.

### From your own Claude session: `braid connect`

`braid connect` registers braid's MCP server with Claude Code (`--scope local|project|user`). Your own session then has lead-only tools: `delegate` (plan a goal and start agents, like `braid do`), `start_agents`, and `team_status`. So you can say "split this up and get some agents on it" in your normal chat. Agents themselves cannot start more agents.

### Everyday commands

| you want to | run |
|---|---|
| set up a repo (creates one in a plain folder) | `braid init [--base main] [--test "cmd"]` |
| start agents | `braid start "task" ["task" ...]` (`--base feature/x`, `--no-launch` to drive them yourself) |
| plan and run a goal | `braid do "goal"`, then `braid plans`, `braid plans show 1`, `braid plans cancel 1` |
| use braid from your Claude session | `braid connect` |
| see everything | `braid status [--live]` (also shows `git status` for where you are) |
| activity / messages | `braid feed -f`, `braid chat`, `braid chat --post "use the v2 API" --to login` |
| check conflicts now | `braid check` (exit 1 when a conflict is predicted, handy in scripts) |
| review an agent yourself | `braid review login` then `--approve` or `--changes -m "why"` |
| land work | `braid land [agent ...]` (all ready agents if none named) |
| push | `braid push [--branches]` or `braid ship` (land + push) |
| update an agent with latest main | `braid sync <agent>` / `braid sync --all` |
| a stuck agent | `braid resume <agent> "what to do"` |
| stop / abandon | `braid stop <agent>` / `braid stop --all`, `braid drop <agent> [--delete]` |
| changes waiting for you | `braid approvals`, `braid approvals show <id>`, `braid approve [id]`, `braid reject [id] -m "why"` |
| tidy up | `braid prune` (removes worktrees and branches of landed agents) |
| settings | `braid settings`, `braid settings <key> <value>` |
| anything git does | `braid <git command>`, e.g. `braid log --oneline`, `braid commit -am "x"` |

`braid status` and `braid push` behave exactly like git's when you pass git flags or aren't in a braid repo.

## How it works

```
 braid start "A" "B" "C"
        |
        v
  +-------------+   MCP tools   +--------------------------------------------+
  | agent A     |<------------->|  shared memory  (.git/braid/state.db)      |
  | agent B     |               |  agents, intents, leases, notes, risks,    |
  | agent C     |               |  reviews, decisions, activity feed         |
  +------+------+               +--------------------^-----------------------+
         | own branch + worktree each                |
         v                                           |
  +------------------------------------------+       |
  | one .git: shared objects and refs        |<------+  watcher (every few seconds)
  +------------------------------------------+       |   1. snapshot each worktree, even uncommitted
                                                     |   2. dry-run merge every pair + vs main
                                                     |   3. tell agents about new conflicts
                                                     |   4. land ready agents through the queue
                                                     |   5. relaunch agents that stopped with feedback
```

**1. Shared memory.** Agents get these tools over MCP: `peers`, `declare_intent`, `acquire_lease` / `release_lease`, `post_note` / `read_notes`, `risks`, `sync`, `ready_to_land`, `pending_reviews`, `show_diff`, `review`, `decisions`, `vote`. A hard lease makes the pre-commit hook refuse other agents' commits to that file; agents can't push at all (pre-push hook).

**2. Early conflict prediction.** Every few seconds braid snapshots each worktree into a commit using a throwaway index (the agent's files and index are never touched), then runs `git merge-tree --write-tree` between every pair of agents and against `main`. That is git's real merge engine running in memory. A new conflict is posted to both agents, so they sort it out mid-task.

**3. Code-aware merging.** `braid init` registers a git merge driver for Python and brace languages (JS/TS, Go, Rust, Java, Kotlin, C/C++, C#, Swift, PHP, Scala, Dart). It merges by function, class, method and import rather than by line, so two agents adding different functions, methods or imports to the same file merge cleanly. It works in every git merge in the repo, including the predictor's. Only an entity changed differently on both sides falls back to a line merge, and anything it can't parse falls back to plain git. `rerere` is on, so a resolution is replayed if the same conflict comes back.

**4. Review.** When an agent finishes it calls `ready_to_land`; other agents see it in `pending_reviews` and approve or request changes. A review is tied to the exact commit, so new commits need a new review. `review.required`: `auto` (default: needs a peer's approval while a peer is still running), `yes`, `no`, or set `review.command` for an automatic reviewer.

**5. Landing and auto-consensus.** The merge queue merges each ready agent into `main` in a private integration worktree:

1. Merge with the code-aware driver and rerere. Most overlaps end here.
2. Anything still conflicted goes to a **neutral resolver** (a separate agent; `resolve.command`). It is given both sides' tasks, declared intents and notes, and told to keep both intents.
3. The **tests** (`test.command`) must pass on the merged result.
4. The agents whose work is in the conflict are notified with a decision number and can `vote` accept or object during `consensus.window` seconds. An objection stops it.
5. Otherwise `main` moves forward atomically. If `main` is checked out, it is fast-forwarded in place.
6. If any step fails, the agent is marked **blocked** with the reason in its notes, and the watcher relaunches it to `sync` and fix it itself. The deterministic tie-break is *first to land wins; the later agent adapts*. After `agent.auto_resume` attempts it waits for you.

Every landing is a merge commit with `Braid-Agent:` and `Reviewed-by:` trailers, so `git log` shows who did what and who checked it.

**6. Push.** `braid push` / `braid ship` push `main` (and agent branches with `--branches`) to `remote` (default `origin`). Set `push.auto true` to push after every landing.

## Settings

| key | default | meaning |
|---|---|---|
| `base` | current branch at init | default branch agents start from and land on (`--base` overrides per agent) |
| `remote` | `origin` | where `push` goes |
| `test.command` | (none) | must pass before anything lands; agents are allowed to run it |
| `review.required` | `auto` | `auto`, `yes`, `no` |
| `review.command` | (none) | automatic reviewer; `{prompt}` is filled in, must print `VERDICT: approve` or `VERDICT: changes` |
| `resolve.command` | `claude -p {prompt} --permission-mode acceptEdits` | neutral conflict resolver |
| `consensus.window` | `0` | seconds parties may object to a resolution before it lands |
| `land.auto` | `true` | watcher lands agents as soon as they're ready |
| `push.auto` | `false` | push after every landing |
| `agent.command` | Claude Code, headless, with braid's MCP tools and git allowed | how agents are launched; `{prompt}`, `{mcp_config}`, `{name}` |
| `agent.auto_resume` | `2` | relaunches for an agent that stopped with feedback to handle |
| `watch.interval` | `5` | seconds between watcher passes |
| `plan.command` | Claude Code, headless, read-only tools | the planner for `braid do`; `{prompt}` is filled in |
| `plan.max_tasks` | `6` | most tasks a plan may have (`--max-agents` overrides) |
| `approve.required` | `no` | `yes`: every landing waits for your yes |
| `approve.channels` | (none) | `cloudflare`, `whatsapp`, `telegram`, `email`, `command`, comma separated |
| `approve.cloudflare.url` | (none) | your deployed approvals Worker |
| `approve.summary_command` | `claude -p {prompt}` | writes the summary and impact; empty for the built-in one |
| `approve.inline_diff_lines` | `40` | bigger diffs get a review link instead of being inlined |
| `approve.push` | `true` | push after an approved landing |
| `approve.tunnel` / `approve.public_url` | (none) | `cloudflared`, or your own URL, so the review page opens on your phone |
| `approve.whatsapp.*`, `approve.telegram.chat_id`, `approve.email.*`, `approve.command` | | channel details, see above; secrets go in `braid approvals secret` |

Use a different agent CLI: `braid settings agent.command "my-agent --mcp {mcp_config} --task {prompt}"`.

## Where things live

- `.git/braid/state.db`: shared memory (SQLite), shared by all worktrees.
- `.git/braid/secrets.json`: channel passwords and tokens (mode 600; environment variables of the same name win).
- `.git/braid/logs/<agent>.log`: each agent's output. `.git/braid/daemon.log`: the watcher.
- `<repo>.agents/<agent>/`: agent worktrees, next to your repo. `<repo>.agents/.integration/` is the landing worktree.
- `refs/braid/wip/<agent>`: latest snapshot of each agent's work, including uncommitted changes.
- `.git/info/attributes` and `.git/info/exclude`: the merge driver and build junk ignores (local only, your `.gitignore` is untouched).

## Tests

```sh
python -m unittest discover -s tests -v
```

59 tests, including end-to-end runs where `braid start` and `braid do` launch real processes (scripted fake agents) and the watcher reviews, resolves and lands them.

## Status and roadmap

Milestones done: worktree launcher and shared memory (M1), code-aware merge (M2), review, resolution and consensus (M3), merge queue, sync and push (M4), git-compatible CLI and packaging (M5), `braid do` with dependency waves, feature-branch bases and lead-session delegation (M6).

Next ideas: entity-level merge inside classes for brace languages, a web dashboard, `braid pr` to open one pull request per landing, running agents in containers, and predicting *semantic* conflicts by running tests on the predicted merge.

See [docs/design.md](docs/design.md) for the research and design behind this.

## License

MIT
# test
