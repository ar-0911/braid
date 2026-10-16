"""braid command line. Anything braid doesn't know is passed straight to git, so `braid` can replace `git`."""
import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import __version__, approvals_cli, gitutil, land, notify, planner, predict, structmerge
from .store import DEFAULTS, Store

HOOK_MARKER = "# installed by braid"
ATTR_BEGIN, ATTR_END = "# >>> braid code-aware merge >>>", "# <<< braid code-aware merge <<<"
PKG_PARENT = str(Path(__file__).resolve().parent.parent)
PY_ENV = f"PYTHONPATH={shlex.quote(PKG_PARENT)}"
PY = f"{PY_ENV} {shlex.quote(sys.executable)} -m braid"

AGENT_PROMPT = """You are agent "{name}", one of several AI agents working in parallel on this repository.
Your task: {task}

You are in your own git worktree on branch {branch}; your work lands on {base}. Other agents are working on
other branches right now.
Use the `braid` MCP tools to work as a team:

1. Start with `peers` and `read_notes` to see who is doing what.
2. Before each subtask, `declare_intent` with the files you expect to change. `acquire_lease` on files you own.
   If someone else already owns a file you need, post_note to them and agree who changes what.
3. Commit early and often on your branch with clear messages.
4. Call `risks` after meaningful edits. On a predicted conflict, read the other agent's intents and either avoid
   their files or agree an approach with post_note. Never silently overwrite their work.
5. When a note says another agent landed, call `sync` to bring their work into your branch, fix any conflicts,
   and commit.
6. Check `pending_reviews` regularly. Review other agents' work honestly with `show_diff` and `review`
   (approve, or changes with specific comments).
7. When your task is done, all work committed and tests passing ({tests}), call `ready_to_land` with a short
   summary.
   Then keep reviewing others until nothing is pending, and stop.
Never merge into or push the base branch yourself; braid does that once your work is reviewed.
"""

RESUME_PROMPT = """You are agent "{name}" resuming your task on branch {branch}: {task}
Your work was paused: {why}
Call `read_notes` and `decisions` to see review feedback, conflicts and requests addressed to you. Address them,
call `sync` if the base branch moved, commit, and call `ready_to_land` again when done.
{extra}"""


# ------------------------------------------------------------------ helpers

def repo_root():
    """Main worktree root, even when called from inside an agent worktree."""
    return gitutil.common_dir().parent


def open_store():
    root = repo_root()
    store = Store(root)
    if not store.initialized():
        cmd_init(argparse.Namespace(base=None, test=None, quiet=True))
    return store


def tty():
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def color(text, code):
    return f"\033[{code}m{text}\033[0m" if tty() else text


STATUS_COLOR = {"active": "36", "ready": "33", "landed": "32", "blocked": "31", "exited": "35", "paused": "90", "done": "90"}


STOPWORDS = set("a an the to of in on for with and or add make create implement build write fix update "
                "support new unit test tests py js ts go rs file files function functions please it its".split())


def slug(text, taken):
    import re
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS and len(w) > 1]
    s = "-".join(words[:2]) or re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:20] or "agent"
    name, i = s, 2
    while name in taken:
        name, i = f"{s}-{i}", i + 1
    return name


def ago(t):
    if not t:
        return "never"
    s = int(time.time() - t)
    return f"{s}s ago" if s < 120 else f"{s // 60}m ago" if s < 7200 else f"{s // 3600}h ago"


# ------------------------------------------------------------------ init

def cmd_init(args):
    rc, _ = gitutil.git("rev-parse", "--git-dir", check=False)
    if rc != 0:
        gitutil.git("init", "-q", "-b", args.base or "main")
    if not gitutil.rev("HEAD"):
        gitutil.git("commit", "-q", "--allow-empty", "-m", "Initial commit")
    root = repo_root()
    store = Store(root)
    base = args.base or gitutil.current_branch(root) or "main"
    store.set_cfg("base", base)
    if getattr(args, "test", None):
        store.set_cfg("test.command", args.test)
    common = gitutil.common_dir(root)

    # code-aware merge driver, for every merge in this repo (including braid's dry runs)
    gitutil.git("config", "merge.braid.name", "braid code-aware merge", cwd=root)
    gitutil.git("config", "merge.braid.driver", f"{PY} merge-driver %O %A %B %P", cwd=root)
    attrs = common / "info" / "attributes"
    attrs.parent.mkdir(exist_ok=True)
    text = attrs.read_text() if attrs.exists() else ""
    if ATTR_BEGIN in text:
        text = text[:text.index(ATTR_BEGIN)] + text[text.index(ATTR_END) + len(ATTR_END):].lstrip("\n")
    block = "\n".join([ATTR_BEGIN] + [f"*{ext} merge=braid" for ext in sorted(structmerge.SUPPORTED_EXT)]
                      + [ATTR_END])
    attrs.write_text((text.rstrip("\n") + "\n" if text.strip() else "") + block + "\n")

    # keep build junk out of agents' commits (local to this clone; your .gitignore is untouched)
    exclude = common / "info" / "exclude"
    ex = exclude.read_text() if exclude.exists() else ""
    if ATTR_BEGIN not in ex:
        junk = ["__pycache__/", "*.pyc", ".pytest_cache/", "node_modules/", ".DS_Store", "*.egg-info/"]
        exclude.write_text(ex.rstrip("\n") + ("\n" if ex.strip() else "") + "\n".join([ATTR_BEGIN] + junk + [ATTR_END]) + "\n")

    # remember conflict resolutions so they replay automatically
    gitutil.git("config", "rerere.enabled", "true", cwd=root)
    gitutil.git("config", "rerere.autoupdate", "true", cwd=root)

    for name in ("pre-commit", "pre-push"):
        hook = common / "hooks" / name
        if hook.exists() and HOOK_MARKER not in hook.read_text():
            print(f"warning: {hook} already exists; braid's {name} check was not installed", file=sys.stderr)
            continue
        hook.parent.mkdir(exist_ok=True)
        hook.write_text(f"#!/bin/sh\n{HOOK_MARKER}\n{PY_ENV} exec {shlex.quote(sys.executable)} -m braid hook {name}\n")
        hook.chmod(0o755)
    if not getattr(args, "quiet", False):
        print(f"braid is set up in {root}")
        print(f"  base branch: {base}   tests: {store.cfg('test.command') or '(none; set with braid settings test.command ...)'}")
        print('  next: braid start "first task" "second task"')


# ------------------------------------------------------------------ agents

def agent_paths(store, name):
    d = store.dir
    return d / "mcp" / f"{name}.json", d / "tasks" / f"{name}.md", d / "logs" / f"{name}.log"


def write_mcp_config(store, name):
    cfg, _, _ = agent_paths(store, name)
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"mcpServers": {"braid": {
        "command": sys.executable, "args": ["-m", "braid", "mcp"],
        "env": {"PYTHONPATH": PKG_PARENT, "BRAID_AGENT": name, "BRAID_REPO": str(store.repo)},
    }}}, indent=2))
    return cfg


def launch(store, agent, prompt):
    cfg, task_file, log = agent_paths(store, agent["name"])
    task_file.parent.mkdir(parents=True, exist_ok=True)
    task_file.write_text(prompt)
    log.parent.mkdir(parents=True, exist_ok=True)
    cmd = store.cfg("agent.command").format(prompt=shlex.quote(prompt), mcp_config=shlex.quote(str(cfg)),
                                            name=shlex.quote(agent["name"]))
    test = store.cfg("test.command")
    if test and cmd.lstrip().startswith("claude "):
        cmd += " --allowedTools " + shlex.quote(f"Bash({test}:*)")  # let the agent run the project's tests
    env = {**os.environ, "BRAID_AGENT": agent["name"], "BRAID_REPO": str(store.repo)}
    with log.open("a") as f:
        f.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} launching ---\n")
        f.flush()
        proc = subprocess.Popen(cmd, shell=True, cwd=agent["worktree"], stdout=f, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True, env=env)
    store.update_agent(agent["name"], pid=proc.pid, status="active")
    store.event("launch", f"agent process {proc.pid} started (log: {log})", agent["name"])
    return proc


def ensure_branch(store, branch):
    """Make sure a base branch exists; new ones start from the repo's default base."""
    if not gitutil.rev(branch, cwd=store.repo):
        gitutil.git("branch", branch, store.base_branch(), cwd=store.repo)
        store.event("branch", f"created {branch} from {store.base_branch()}")


def create_agent(store, task, name=None, base=None, brief=None, launch_it=True, taken=None):
    """Branch + worktree + registration + launch for one task. Returns the agent row."""
    base = base or store.base_branch()
    ensure_branch(store, base)
    taken = taken if taken is not None else {a["name"] for a in store.agents()}
    name = name if name and name not in taken else slug(name or task, taken)
    taken.add(name)
    wt = store.repo.parent / f"{store.repo.name}.agents" / name
    branch = f"agent/{name}"
    gitutil.git("worktree", "add", "-q", "-b", branch, str(wt), base, cwd=store.repo)
    store.add_agent(name, branch, wt, task, base=base)
    write_mcp_config(store, name)
    test = store.cfg("test.command")
    prompt = AGENT_PROMPT.format(name=name, task=brief or task, branch=branch, base=base,
                                 tests=f"run them with: {test}" if test else "if the project has any")
    agent = store.agent(name)
    if launch_it:
        launch(store, agent, prompt)
    else:
        _, task_file, _ = agent_paths(store, name)
        task_file.parent.mkdir(parents=True, exist_ok=True)
        task_file.write_text(prompt)
        store.update_agent(name, pid=None)
    return store.agent(name)


def cmd_start(args):
    store = open_store()
    if args.agent_cmd:
        store.set_cfg("agent.command", args.agent_cmd)
    taken = {a["name"] for a in store.agents()}
    for task in args.tasks:
        name = args.name if args.name and len(args.tasks) == 1 else None
        a = create_agent(store, task, name=name, base=args.base, launch_it=not args.no_launch, taken=taken)
        where = f"branch {a['branch']} -> lands on {a['base']}  worktree {a['worktree']}"
        if args.no_launch:
            cfg, task_file, _ = agent_paths(store, a["name"])
            print(f"{color(a['name'], '1')}  {where}")
            print(f"  start it yourself:  cd {shlex.quote(a['worktree'])} && claude --mcp-config {shlex.quote(str(cfg))}"
                  f" \"$(cat {shlex.quote(str(task_file))})\"")
        else:
            print(f"{color(a['name'], '1')}  {where}  (agent pid {a['pid']})")
    if not args.no_daemon:
        daemon_start(store, quiet=True)
    print("\nwatch it with:  braid status --live      activity feed:  braid feed -f")


def plan_starter(store):
    def start(plan, task, brief):
        return create_agent(store, task["title"], name=task["id"], base=plan["base"], brief=brief)["name"]
    return start


def print_plan(store, pid):
    plan, tasks = store.plan(pid), store.plan_tasks(pid)
    print(f"{color(f'plan #{pid}', '1')}  {plan['goal']}")
    print(f"  lands on: {plan['base']}   status: {plan['status']}" + ("   push when done" if plan["push"] else ""))
    for n, wave in enumerate(planner.waves(tasks), 1):
        print(f"\n  wave {n}" + (" (starts now)" if n == 1 else " (starts when its dependencies land)"))
        for t in wave:
            st = f"[{t['status']}{' as ' + t['agent'] if t['agent'] else ''}]" if plan["status"] != "proposed" else ""
            print(f"    {color(t['id'], '1')} {st} {t['title']}")
            if t["files"]:
                print(f"        owns: {', '.join(t['files'])}")
            if t["depends_on"]:
                print(f"        after: {', '.join(t['depends_on'])}")


def run_plan(store, pid):
    store.set_plan_status(pid, "running")
    started = planner.advance(store, plan_starter(store))
    daemon_start(store, quiet=True)
    return started


def cmd_do(args):
    store = open_store()
    base = args.base or store.base_branch()
    ensure_branch(store, base)
    if args.plan_file:
        try:
            tasks = planner.parse_plan(Path(args.plan_file).read_text())
        except (OSError, planner.PlanError) as e:
            sys.exit(f"braid: {e}")
        goal = args.goal or f"plan from {args.plan_file}"
    else:
        if not args.goal:
            sys.exit("braid do needs a goal, e.g. braid do \"build a todo app with a REST API and a web UI\"")
        print(color("planning...", "90"), flush=True)
        try:
            tasks = planner.ask_planner(store, args.goal, base, args.max_agents or int(store.cfg("plan.max_tasks")))
        except planner.PlanError as e:
            sys.exit(f"braid: {e}")
        goal = args.goal
    pid = store.add_plan(goal, base, tasks, push=args.push)
    plan_file = store.dir / "plans" / f"{pid}.json"
    plan_file.parent.mkdir(parents=True, exist_ok=True)
    plan_file.write_text(json.dumps({"goal": goal, "base": base, "tasks": tasks}, indent=2))
    print_plan(store, pid)
    print(f"\n  plan saved to {plan_file}")
    go = args.yes
    if not go and sys.stdin.isatty():
        go = input("\nstart it? [Y/n] ").strip().lower() in ("", "y", "yes")
    if not go:
        print(f"\nnot started. to change it, edit the file and run:  braid do --plan-file {plan_file} --base {base}"
              f"\nto start it as is:  braid plans start {pid}")
        return
    started = run_plan(store, pid)
    print(f"\nstarted {len(started)} agent(s): {', '.join(started)}. later waves start as their dependencies land.")
    print("watch it with:  braid status --live      activity feed:  braid feed -f")


def cmd_plans(args):
    store = open_store()
    if args.action == "start":
        if not store.plan(args.id):
            sys.exit(f"no plan #{args.id}")
        started = run_plan(store, args.id)
        print(f"started {', '.join(started) or 'nothing new'}")
    elif args.action == "cancel":
        store.set_plan_status(args.id, "cancelled")
        print(f"plan #{args.id} cancelled; its running agents keep going (braid stop <agent> to stop them)")
    elif args.action == "show" or args.id:
        print_plan(store, args.id or store.plans()[-1]["id"])
    else:
        plans = store.plans()
        if not plans:
            print("no plans yet. make one with:  braid do \"what you want built\"")
        for p in plans:
            tasks = store.plan_tasks(p["id"])
            done = sum(t["status"] == "landed" for t in tasks)
            print(f"#{p['id']}  {p['status']:<9} {done}/{len(tasks)} landed  on {p['base']}  {p['goal'][:70]}")


def resume_agent(store, a, why=None, message=None):
    why = why or {"blocked": "landing it was blocked", "exited": "your process stopped before your work landed",
                  "active": "the user restarted you"}.get(a["status"], "the user restarted you")
    write_mcp_config(store, a["name"])
    prompt = RESUME_PROMPT.format(name=a["name"], branch=a["branch"], task=a["task"], why=why,
                                  extra=f"Message from the user: {message}" if message else "")
    if message:
        store.post_note("human", "request", message, to=a["name"])
    launch(store, a, prompt)
    store.event("resume", why, a["name"])


def cmd_resume(args):
    store = open_store()
    a = store.agent(args.agent)
    if not a:
        sys.exit(f"no agent named {args.agent}")
    resume_agent(store, a, args.why, args.message)
    daemon_start(store, quiet=True)
    print(f"resumed {a['name']}")


def needs_attention(store, a):
    """Why a stopped agent should be relaunched, or None."""
    if a["status"] == "blocked":
        return "landing it was blocked: " + (store.events_for(a["name"], "status") or "see read_notes")
    reviews = store.reviews(a["name"], gitutil.rev(a["branch"], cwd=store.repo))
    if reviews and reviews[-1]["verdict"] == "changes":
        return f"{reviews[-1]['reviewer']} requested changes: {reviews[-1]['comment']}"
    if a["status"] == "exited":
        return "your process stopped before you called ready_to_land"
    return None


def cmd_stop(args):
    store = open_store()
    names = [a["name"] for a in store.live_agents()] if args.all else args.agents
    for name in names:
        a = store.agent(name)
        if a and a.get("pid") and store.process_alive(a):
            try:
                os.killpg(a["pid"], signal.SIGTERM)
            except ProcessLookupError:
                pass
        if a and a["status"] in ("active", "exited", "blocked"):
            store.set_status(name, "paused", "stopped by user")
        print(f"stopped {name}")
    if args.all:
        daemon_stop(store)


def cmd_drop(args):
    store = open_store()
    a = store.agent(args.agent)
    if not a:
        sys.exit(f"no agent named {args.agent}")
    cmd_stop(argparse.Namespace(agents=[a["name"]], all=False))
    store.set_status(a["name"], "done", "dropped by user")
    store.release_lease(a["name"])
    if args.delete:
        remove_agent_checkout(store, a, force=True)
    print(f"dropped {a['name']}" + (" and deleted its worktree and branch" if args.delete else ""))


def remove_agent_checkout(store, a, force=False):
    if Path(a["worktree"]).exists():
        gitutil.git("worktree", "remove", *(["--force"] if force else []), a["worktree"], cwd=store.repo,
                    check=False)
    gitutil.git("branch", "-D" if force else "-d", a["branch"], cwd=store.repo, check=False)
    gitutil.git("update-ref", "-d", f"refs/braid/wip/{a['name']}", cwd=store.repo, check=False)


def cmd_clean(args):
    store = open_store()
    n = 0
    for a in store.agents(("landed", "done")):
        if Path(a["worktree"]).exists() or gitutil.rev(a["branch"], cwd=store.repo):
            remove_agent_checkout(store, a, force=a["status"] == "landed")
            n += 1
    gitutil.git("worktree", "prune", cwd=store.repo)
    print(f"removed {n} finished agent worktree(s)")


# ------------------------------------------------------------------ visibility

def render_status(store):
    lines = []
    base = store.base_branch()
    base_oid = gitutil.rev(base, cwd=store.repo)
    alive = "running" if daemon_pid(store) else "stopped"
    lines.append(f"{color('braid', '1')}  base {base} @ {base_oid[:10] if base_oid else '?'}   daemon {alive}")
    agents = store.agents()
    for p in store.plans("running"):
        tasks = store.plan_tasks(p["id"])
        done = sum(t["status"] == "landed" for t in tasks)
        waiting = [t["id"] for t in tasks if t["status"] == "waiting"]
        lines.append(f"\n{color('plan #' + str(p['id']), '1')} {done}/{len(tasks)} landed on {p['base']}: {p['goal'][:80]}"
                     + (f"\n  waiting on dependencies: {', '.join(waiting)}" if waiting else ""))
    if not agents:
        lines.append('\nno agents yet. start some with:  braid start "task one" "task two"  or  braid do "goal"')
        return "\n".join(lines)
    leases = store.leases()
    lines.append("")
    for a in agents:
        st = color(f"{a['status']:<8}", STATUS_COLOR.get(a["status"], "0"))
        run = ""
        if a.get("pid"):
            run = "running" if store.process_alive(a) else "stopped"
        ahead, ab = "", store.agent_base(a)
        if a["status"] not in ("landed", "done") and gitutil.rev(ab, cwd=store.repo) \
                and gitutil.rev(a["branch"], cwd=store.repo):
            ahead = gitutil.out("rev-list", "--count", f"{ab}..{a['branch']}", cwd=store.repo) + " commits"
        onto = f" -> {ab}" if ab != base else ""
        lines.append(f"  {color(a['name'], '1'):<30} {st} {ahead:<11} {run:<8} {a['task'][:90]}{onto}")
        mine = [l["path"] + ("!" if l["kind"] == "hard" else "") for l in leases if l["agent"] == a["name"]]
        if mine:
            lines.append(f"      owns: {', '.join(mine)}")
        if a["status"] == "ready":
            ok, why = land.review_gate(store, a)
            lines.append(f"      {'can land' if ok else why}")
        if a["status"] in ("exited", "blocked") and not (a.get("pid") and store.process_alive(a)):
            why = needs_attention(store, a) or a["status"]
            lines.append(color(f"      needs you: {why[:160]}", "31"))
            lines.append(f"      continue it with: braid resume {a['name']} \"what to do\"")
    live = {a["name"] for a in store.live_agents()}
    risks = [r for r in store.risks() if r["a"] in live and (r["b"] in live or r["b"].startswith("@"))]
    if risks:
        lines.append("\n" + color("predicted", "1"))
        for r in risks:
            sev = color("CONFLICT", "31") if r["severity"] == "conflict" else color("overlap ", "33")
            lines.append(f"  {sev} {r['a']} <-> {r['b']}: {', '.join(r['files'])}")
    open_d = [d for d in store.decisions() if d["status"] in ("proposed", "escalated")]
    if open_d:
        lines.append("\n" + color("decisions", "1"))
        for d in open_d:
            lines.append(f"  #{d['id']} {d['status']}: {d['agent']} vs {', '.join(d['parties'])} "
                         f"in {', '.join(d['files'])}: {d['detail']}")
    return "\n".join(lines)


def cmd_status(args):
    store = open_store()
    if not args.live:
        here = gitutil.out("status", "--short", "--branch")
        print(here + "\n")
    if args.refresh:
        predict.check(store)
    if not args.live:
        print(render_status(store))
        return
    try:
        while True:
            out = render_status(store)
            sys.stdout.write("\033[H\033[2J" + out + f"\n\n{color('refreshing every 2s, ctrl-c to exit', '90')}\n")
            sys.stdout.flush()
            time.sleep(2)
    except KeyboardInterrupt:
        pass


def fmt_event(e):
    t = time.strftime("%H:%M:%S", time.localtime(e["at"]))
    who = color(e["agent"], "1") + " " if e["agent"] else ""
    return f"{color(t, '90')} {color(e['kind'], '36'):<8} {who}{e['text']}"


def cmd_log(args):
    store = open_store()
    seen = 0
    for e in store.events(args.n):
        print(fmt_event(e))
        seen = e["id"]
    if not args.follow:
        return
    try:
        while True:
            time.sleep(1)
            for e in store.db.execute("SELECT * FROM events WHERE id > ? ORDER BY id", (seen,)):
                print(fmt_event(dict(e)), flush=True)
                seen = e["id"]
    except KeyboardInterrupt:
        pass


def cmd_notes(args):
    store = open_store()
    if args.post:
        store.post_note("human", "request", args.post, to=args.to)
        print("posted")
        return
    for n in store.notes()[-args.n:]:
        to = f" -> {n['to_agent']}" if n["to_agent"] else ""
        print(f"#{n['id']} {color(n['agent'] + to, '1')} [{n['topic']}] {n['text']}")


def cmd_check(args):
    store = open_store()
    risks, _ = predict.check(store)
    for a, b, sev, files in risks:
        print(f"{sev.upper():<9} {a} <-> {b}: {', '.join(sorted(files))}")
    if not risks:
        print("no conflicts predicted")
    sys.exit(1 if any(r[2] == "conflict" for r in risks) else 0)


# ------------------------------------------------------------------ daemon

def daemon_pid(store):
    f = store.dir / "daemon.pid"
    try:
        pid = int(f.read_text())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def daemon_start(store, quiet=False):
    if daemon_pid(store):
        if not quiet:
            print(f"daemon already running (pid {daemon_pid(store)})")
        return
    log = store.dir / "daemon.log"
    with log.open("a") as f:
        proc = subprocess.Popen([sys.executable, "-m", "braid", "watch"], cwd=store.repo, stdout=f,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True,
                                env={**os.environ, "PYTHONPATH": PKG_PARENT})
    (store.dir / "daemon.pid").write_text(str(proc.pid))
    if not quiet:
        print(f"daemon started (pid {proc.pid}, log {log})")


def daemon_stop(store):
    pid = daemon_pid(store)
    if pid:
        os.kill(pid, signal.SIGTERM)
        print(f"daemon stopped (pid {pid})")
    (store.dir / "daemon.pid").unlink(missing_ok=True)


def cmd_daemon(args):
    store = open_store()
    if args.action == "start":
        daemon_start(store)
    elif args.action == "stop":
        daemon_stop(store)
    else:
        pid = daemon_pid(store)
        print(f"running (pid {pid})" if pid else "stopped")


def tick(store, auto_land=None):
    """One daemon pass: notice agents that stopped, predict conflicts, land ready work."""
    for a in store.agents(("active",)):
        if a.get("pid") and not store.process_alive(a):
            store.set_status(a["name"], "exited", "process ended before ready_to_land")
    limit = int(store.cfg("agent.auto_resume") or 0)
    for a in store.agents(("exited", "blocked")):
        if not a.get("pid") or store.process_alive(a):
            continue  # interactive agents are resumed by their human
        count = int(store.get_meta(f"resumes.{a['name']}", "0"))
        why = needs_attention(store, a)
        if why and count < limit:
            store.set_meta(f"resumes.{a['name']}", count + 1)
            resume_agent(store, a, why)
    if store.plans("running"):
        planner.advance(store, plan_starter(store))  # start tasks whose dependencies have landed
    _, new = predict.check(store)
    results = []
    if store.cfg_bool("land.auto") if auto_land is None else auto_land:
        landed_any = False
        for name, r in land.land_ready(store):
            key = f"landwait.{name}"
            if r.ok or store.get_meta(key) != r.message:
                store.set_meta(key, r.message)
                if not r.ok:
                    store.event("wait" if r.waiting else "land-failed", r.message, name)
            results.append((name, r))
            landed_any |= r.ok
        if landed_any:
            predict.check(store)  # base moved: refresh everyone's risks against it
            if store.plans("running"):
                planner.advance(store, plan_starter(store))
    replies = notify.poll(store)  # yes/no replies to approval requests; a yes lands right away
    results += [("approval", land.LandResult(True, msg)) for msg in replies]
    if replies and store.plans("running"):
        planner.advance(store, plan_starter(store))
    return new, results


def cmd_watch(args):
    store = open_store()
    interval = args.interval or float(store.cfg("watch.interval"))
    print(f"braid watching every {interval}s", flush=True)
    server = None
    if store.cfg_bool("approve.required") and "cloudflare" not in notify.channels(store):  # serve review pages
        try:
            server = approvals_cli.review_page.ReviewServer(store).start()
            print(f"review pages at {server.url()}", flush=True)
        except OSError as e:
            print(f"review page server not started: {e}", flush=True)
    stop = []
    signal.signal(signal.SIGTERM, lambda *a: stop.append(1))
    try:
        while not stop:
            try:
                new, results = tick(store)
                for a, b, _, files in new:
                    print(f"{time.strftime('%H:%M:%S')} conflict predicted: {a} <-> {b} in {', '.join(files)}",
                          flush=True)
                for name, r in results:
                    if r.ok:
                        print(f"{time.strftime('%H:%M:%S')} {r.message}", flush=True)
            except Exception as e:  # keep watching through transient git/db errors
                print(f"{time.strftime('%H:%M:%S')} error: {e}", flush=True)
            for _ in range(int(interval * 10)):
                if stop:
                    break
                time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    if server:
        server.close()
    (store.dir / "daemon.pid").unlink(missing_ok=True) if daemon_pid(store) == os.getpid() else None


# ------------------------------------------------------------------ review / land / ship

def cmd_ready(args):
    store = open_store()
    a = store.agent(args.agent)
    if not a:
        sys.exit(f"no agent named {args.agent}")
    store.update_agent(a["name"], summary=args.summary or a["task"])
    store.set_status(a["name"], "ready", "marked by user")
    print(f"{a['name']} is ready to land")


def cmd_review(args):
    store = open_store()
    a = store.agent(args.agent)
    if not a:
        sys.exit(f"no agent named {args.agent}")
    if not (args.approve or args.changes):
        print(gitutil.out("diff", "--stat", f"{store.base_branch()}...{a['branch']}", cwd=store.repo))
        print(f"\nsee the diff: braid diff {store.base_branch()}...{a['branch']}")
        print(f"then: braid review {a['name']} --approve   or   braid review {a['name']} --changes -m \"why\"")
        return
    verdict = "approve" if args.approve else "changes"
    head = gitutil.rev(a["branch"], cwd=store.repo)
    store.add_review(a["name"], "human", head, verdict, args.message or "")
    store.post_note("human", "review", f"Review of your work: {verdict}. {args.message or ''}", to=a["name"])
    if verdict == "changes" and a["status"] == "ready":
        store.set_status(a["name"], "active", "changes requested by user")
    print(f"recorded {verdict} for {a['name']}")


def cmd_land(args):
    store = open_store()
    if args.agents:
        results = [(n, land.land(store, n, push=False)) for n in args.agents]
        if args.push and any(r.ok for _, r in results):
            print(land.push_base(store)[1])
    else:
        results = land.land_ready(store, push=args.push)
    if not results:
        print("nothing is ready to land. agents mark themselves ready, or: braid ready <agent>")
    failed = False
    for name, r in results:
        mark = color("landed", "32") if r.ok else color("waiting", "33") if r.waiting else color("blocked", "31")
        print(f"{mark}  {name}: {r.message}")
        failed |= not r.ok
    sys.exit(1 if failed else 0)


def cmd_ship(args):
    store = open_store()
    results = land.land_ready(store, push=False)
    for name, r in results:
        print(f"{'landed ' if r.ok else 'skipped'} {name}: {r.message}")
    ok, out = land.push_base(store, branches=args.branches)
    print(("pushed " if ok else "push failed: ") + (out or store.base_branch()))
    sys.exit(0 if ok else 1)


def cmd_push(args):
    store = open_store()
    ok, out = land.push_base(store, branches=args.branches)
    print(out or ("pushed" if ok else "push failed"))
    sys.exit(0 if ok else 1)


def cmd_sync(args):
    store = open_store()
    if args.all:
        names = [a["name"] for a in store.live_agents()]
    elif args.agent:
        names = [args.agent]
    else:
        here = store.agent_for_worktree(gitutil.toplevel())
        if not here:
            sys.exit("name an agent, use --all, or run this inside an agent's worktree")
        names = [here["name"]]
    rc = 0
    for name in names:
        ok, msg, _ = land.sync(store, name)
        print(f"{name}: {msg}")
        rc |= not ok
    sys.exit(rc)


def cmd_vote(args):
    store = open_store()
    store.vote(args.decision, "human", args.vote, args.reason or "")
    print(f"recorded {args.vote} on decision #{args.decision}")


# ------------------------------------------------------------------ config / doctor / internals

def cmd_config(args):
    store = open_store()
    if args.key is None:
        for k, v in store.all_cfg().items():
            print(f"{k} = {v}")
    elif args.value is None:
        print(store.cfg(args.key))
    else:
        if args.key not in DEFAULTS:
            sys.exit(f"unknown key {args.key}. keys: {', '.join(DEFAULTS)}")
        store.set_cfg(args.key, args.value)
        print(f"{args.key} = {args.value}")


def cmd_doctor(args):
    def check(label, ok, hint=""):
        print(f"  {color('ok ', '32') if ok else color('!! ', '31')} {label}" + ("" if ok else f"  ({hint})"))
        return ok
    rc, v = gitutil.git("--version", check=False)
    ver = tuple(int(x) for x in v.split()[2].split(".")[:2]) if rc == 0 else (0, 0)
    check(f"git {v.split()[2] if rc == 0 else 'missing'}", ver >= (2, 38), "braid needs git 2.38 or newer")
    check(f"python {sys.version.split()[0]}", sys.version_info >= (3, 10), "braid needs Python 3.10+")
    agent_bin = shlex.split(DEFAULTS["agent.command"])[0]
    try:
        store = open_store()
        agent_bin = shlex.split(store.cfg("agent.command"))[0]
        check("inside a braid repo", True)
        check("merge driver configured", gitutil.git("config", "merge.braid.driver", cwd=store.repo,
                                                     check=False)[0] == 0, "run braid init")
        check("tests configured", bool(store.cfg("test.command")), "braid settings test.command \"pytest -q\"")
        check(f"remote {store.cfg('remote')}", gitutil.git("remote", "get-url", store.cfg("remote"),
                                                           cwd=store.repo, check=False)[0] == 0,
              "braid remote add origin <url>, needed only for push")
        check("daemon running", bool(daemon_pid(store)), "braid daemon start")
    except gitutil.GitError:
        check("inside a git repo", False, "run braid init")
    from shutil import which
    check(f"agent CLI '{agent_bin}' on PATH", bool(which(agent_bin)), "install Claude Code or set agent.command")


def cmd_connect(args):
    """Give the Claude Code session you work in braid's tools, so you can say "split this up" and it delegates."""
    store = open_store()
    cmd = ["claude", "mcp", "add", "braid", "--scope", args.scope, "-e", f"PYTHONPATH={PKG_PARENT}",
           "-e", f"BRAID_REPO={store.repo}", "--", sys.executable, "-m", "braid", "mcp"]
    from shutil import which
    if which("claude") and not args.print_only:
        r = subprocess.run(cmd, cwd=store.repo, capture_output=True, text=True)
        print((r.stdout + r.stderr).strip() or "added")
        if r.returncode != 0:
            sys.exit(r.returncode)
    else:
        print(" ".join(shlex.quote(c) for c in cmd))
    print("\nnow, in Claude Code in this repo, ask for something big and say to delegate it with braid,\n"
          "e.g. \"use braid to build a REST API and a web UI for todos\". It calls delegate, then team_status.")


def cmd_merge_driver(args):
    sys.exit(structmerge.driver_main(args.base, args.ours, args.theirs, args.path))


def cmd_hook(args):
    if args.name == "pre-push":
        if os.environ.get("BRAID_AGENT"):
            print(f"braid: agents don't push. Call ready_to_land and braid will land and push your work.",
                  file=sys.stderr)
            sys.exit(1)
        return
    if args.name != "pre-commit":
        return
    try:
        top = gitutil.toplevel()
        store = Store(repo_root())
    except Exception as e:
        print(f"braid: skipping lease check ({e})", file=sys.stderr)
        return
    if top.resolve() == land.integration_dir(store).resolve():
        return  # braid's own landing commits
    if gitutil.git("rev-parse", "-q", "--verify", "MERGE_HEAD", check=False)[0] == 0:
        return  # finishing a merge brings in others' files by design
    me_row = store.agent_for_worktree(top)
    me = me_row["name"] if me_row else "human"
    staged = [p for p in gitutil.out("diff", "--cached", "--name-only").splitlines() if p]
    blocked = False
    for path in staged:
        for l in store.overlapping_leases(path):
            if l["agent"] == me:
                continue
            if l["kind"] == "hard":
                blocked = True
                print(f"braid: {path} is owned by {l['agent']} (hard lease); commit blocked", file=sys.stderr)
            else:
                print(f"braid: heads up, {path} is claimed by {l['agent']}", file=sys.stderr)
    if blocked:
        print("braid: agree with that agent first (post_note), or leave these files out of the commit",
              file=sys.stderr)
        sys.exit(1)


def cmd_mcp(args):
    from . import mcp_server
    mcp_server.main()


# ------------------------------------------------------------------ parser

def build_parser():
    p = argparse.ArgumentParser(
        prog="braid",
        description="Run many coding agents on one repo at once. They share memory, see each other's work, "
                    "get warned about conflicts early, review each other, and braid lands their work. "
                    "Any other command is passed to git, so braid can replace git day to day.")
    p.add_argument("--version", action="version", version=f"braid {__version__}")
    sub = p.add_subparsers(dest="cmd", metavar="command")

    def add(name, fn, help, **kw):
        s = sub.add_parser(name, help=help, **kw)
        s.set_defaults(fn=fn)
        return s

    s = add("init", cmd_init, "set up braid in this repo (creates one if needed)")
    s.add_argument("--base", help="branch agents start from and land on (default: current branch)")
    s.add_argument("--test", help="test command that must pass before anything lands")

    s = add("start", cmd_start, "start one agent per task, each on its own branch and worktree")
    s.add_argument("tasks", nargs="+")
    s.add_argument("--name", help="agent name (only with a single task)")
    s.add_argument("--base", help="branch these agents land on instead of the default (created if new)")
    s.add_argument("--no-launch", action="store_true", help="create the worktrees but start agents yourself")
    s.add_argument("--no-daemon", action="store_true", help="don't start the background watcher")
    s.add_argument("--agent-cmd", help="command template to launch agents; {prompt} and {mcp_config} filled in")

    s = add("do", cmd_do, "plan a goal into parallel tasks and run them in dependency waves")
    s.add_argument("goal", nargs="?")
    s.add_argument("--base", help="branch everything lands on (created from the default base if new)")
    s.add_argument("--yes", "-y", action="store_true", help="start without asking")
    s.add_argument("--push", action="store_true", help="push the base branch when every task has landed")
    s.add_argument("--max-agents", type=int, help="most tasks the planner may create")
    s.add_argument("--plan-file", help="run a plan you wrote or edited instead of asking the planner")

    s = add("plans", cmd_plans, "list plans, show one, start or cancel it")
    s.add_argument("action", nargs="?", choices=["show", "start", "cancel"])
    s.add_argument("id", nargs="?", type=int)

    s = add("status", cmd_status, "agents, ownership, predicted conflicts, decisions")
    s.add_argument("--live", action="store_true", help="keep refreshing")
    s.add_argument("--refresh", action="store_true", help="run a fresh conflict check first")

    s = add("feed", cmd_log, "activity feed: what every agent and braid did")
    s.add_argument("-n", type=int, default=30)
    s.add_argument("-f", "--follow", action="store_true")

    s = add("chat", cmd_notes, "shared notes between agents; post one with --post")
    s.add_argument("-n", type=int, default=20)
    s.add_argument("--post", metavar="TEXT", help="post a note as you")
    s.add_argument("--to", help="address the note to one agent")

    add("check", cmd_check, "run one conflict prediction now (exit 1 if conflicts)")

    s = add("watch", cmd_watch, "run the watcher in the foreground")
    s.add_argument("--interval", type=float)

    s = add("daemon", cmd_daemon, "control the background watcher")
    s.add_argument("action", choices=["start", "stop", "status"])

    s = add("sync", cmd_sync, "merge the latest base into an agent's branch")
    s.add_argument("agent", nargs="?")
    s.add_argument("--all", action="store_true")

    s = add("ready", cmd_ready, "mark an agent's work ready to land")
    s.add_argument("agent")
    s.add_argument("summary", nargs="?")

    s = add("review", cmd_review, "review an agent's work yourself")
    s.add_argument("agent")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--approve", action="store_true")
    g.add_argument("--changes", action="store_true")
    s.add_argument("-m", "--message")

    s = add("vote", cmd_vote, "accept or object to an automatic conflict resolution")
    s.add_argument("decision", type=int)
    s.add_argument("vote", choices=["accept", "object"])
    s.add_argument("reason", nargs="?")

    s = add("land", cmd_land, "merge ready agents into the base branch (review, resolve, test)")
    s.add_argument("agents", nargs="*")
    s.add_argument("--push", action="store_true", help="push the base branch afterwards")

    s = add("ship", cmd_ship, "land everything that's ready, then push")
    s.add_argument("--branches", action="store_true", help="also push agent branches")

    s = add("push", cmd_push, "push the base branch to the remote")
    s.add_argument("--branches", action="store_true", help="also push agent branches")

    s = add("resume", cmd_resume, "restart a stopped or blocked agent so it can address feedback")
    s.add_argument("agent")
    s.add_argument("message", nargs="?", help="extra instructions for it")
    s.add_argument("--why", help=argparse.SUPPRESS)

    s = add("stop", cmd_stop, "stop agent processes")
    s.add_argument("agents", nargs="*")
    s.add_argument("--all", action="store_true", help="stop every agent and the daemon")

    s = add("drop", cmd_drop, "abandon an agent's work")
    s.add_argument("agent")
    s.add_argument("--delete", action="store_true", help="also delete its worktree and branch")

    add("prune", cmd_clean, "remove worktrees and branches of landed agents")

    s = add("settings", cmd_config, "show or set braid settings")
    s.add_argument("key", nargs="?")
    s.add_argument("value", nargs="?")

    add("doctor", cmd_doctor, "check that everything braid needs is in place")

    s = add("connect", cmd_connect, "give your own Claude Code session braid's tools (delegate, team_status)")
    s.add_argument("--scope", default="local", choices=["local", "project", "user"])
    s.add_argument("--print-only", action="store_true", help="print the command instead of running it")

    approvals_cli.register(add)

    s = sub.add_parser("merge-driver")
    s.add_argument("base")
    s.add_argument("ours")
    s.add_argument("theirs")
    s.add_argument("path")
    s.set_defaults(fn=cmd_merge_driver)
    s = sub.add_parser("hook")
    s.add_argument("name")
    s.set_defaults(fn=cmd_hook)
    s = sub.add_parser("mcp")
    s.set_defaults(fn=cmd_mcp)
    return p, set(sub.choices)


GIT_SHARED = {"init", "status", "push"}  # names braid shares with git


def _braid_repo():
    try:
        return (gitutil.common_dir() / "braid" / "state.db").exists()
    except gitutil.GitError:
        return False


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    parser, commands = build_parser()
    if argv and argv[0] not in commands and argv[0] not in ("-h", "--help", "--version"):
        os.execvp("git", ["git", *argv])  # everything else is plain git
    if argv and argv[0] in GIT_SHARED:
        args, extra = parser.parse_known_args(argv)
        if extra or (argv[0] != "init" and not _braid_repo()):
            os.execvp("git", ["git", *argv])  # git's own flags, or not a braid repo: behave exactly like git
    else:
        args = parser.parse_args(argv)
    if not getattr(args, "fn", None):
        parser.print_help()
        return
    try:
        args.fn(args)
    except gitutil.GitError as e:
        print(f"braid: {e}", file=sys.stderr)
        sys.exit(2)
