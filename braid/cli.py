"""agit command line."""
import argparse
import json
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

from . import gitutil, predict
from .store import Store

HOOK_MARKER = "# installed by agit"
PKG_PARENT = str(Path(__file__).resolve().parent.parent)

AGENT_PROMPT = """You are agent "{name}", one of several agents working in parallel on this repository.
Your task: {task}

You work in your own git worktree on branch {branch}. Other agents work on other branches at the same time.
Coordinate through the `agit` MCP tools:
1. Start with `peers` and `read_notes` to see what everyone else is doing.
2. Before each subtask, `declare_intent` with the files you expect to change, and `acquire_lease` on files you own.
3. Call `risks` after meaningful edits. If it reports a conflict, read the other agent's intent, then either
   change your approach to avoid their files or `post_note` to agree who changes what. Don't silently overwrite.
4. Use `post_note` to announce anything other agents depend on (API changes, renamed modules, new shared helpers).
5. Commit your work on your branch with clear messages. Do not merge into or push the base branch.
"""


def slug(text, taken):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:30].strip("-") or "agent"
    name, i = s, 2
    while name in taken:
        name, i = f"{s}-{i}", i + 1
    return name


def repo_root():
    """Main worktree root, even when called from inside an agent worktree."""
    return gitutil.common_dir().parent


def cmd_init(args):
    repo = repo_root()
    store = Store(repo)
    base = args.base or gitutil.out("symbolic-ref", "--short", "HEAD", cwd=repo)
    store.set_meta("base_branch", base)
    hook = gitutil.common_dir(repo) / "hooks" / "pre-commit"
    script = (f"#!/bin/sh\n{HOOK_MARKER}\n"
              f"PYTHONPATH={shlex.quote(PKG_PARENT)} exec {shlex.quote(sys.executable)} -m agit hook pre-commit\n")
    if hook.exists() and HOOK_MARKER not in hook.read_text():
        print(f"warning: {hook} already exists and isn't agit's; lease checks on commit are not installed")
    else:
        hook.parent.mkdir(exist_ok=True)
        hook.write_text(script)
        hook.chmod(0o755)
    print(f"agit initialised in {repo} (base branch: {base})")


def cmd_run(args):
    repo = repo_root()
    store = Store(repo)
    if store.get_meta("base_branch") is None:
        cmd_init(argparse.Namespace(base=None))
    base = store.base_branch()
    agit_dir = gitutil.common_dir(repo) / "agit"
    wt_root = repo.parent / f"{repo.name}.agents"
    taken = {a["name"] for a in store.agents(active_only=False)}
    created = []
    for task in args.tasks:
        name = slug(task, taken)
        taken.add(name)
        branch = f"agent/{name}"
        wt = wt_root / name
        gitutil.git("worktree", "add", "-b", branch, str(wt), base, cwd=repo)
        store.add_agent(name, branch, wt, task)

        mcp_cfg = agit_dir / "mcp" / f"{name}.json"
        mcp_cfg.parent.mkdir(parents=True, exist_ok=True)
        mcp_cfg.write_text(json.dumps({"mcpServers": {"agit": {
            "command": sys.executable, "args": ["-m", "agit", "mcp"],
            "env": {"PYTHONPATH": PKG_PARENT, "AGIT_AGENT": name, "AGIT_REPO": str(repo)},
        }}}, indent=2))
        prompt = AGENT_PROMPT.format(name=name, task=task, branch=branch)
        prompt_file = agit_dir / "tasks" / f"{name}.md"
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text(prompt)
        created.append((name, wt, mcp_cfg, prompt))
        print(f"created agent {name}: branch {branch}, worktree {wt}")

    for name, wt, mcp_cfg, prompt in created:
        cmd = ["claude", "-p", prompt, "--mcp-config", str(mcp_cfg),
               "--allowedTools", "mcp__agit", *shlex.split(args.claude_args)]
        if args.launch:
            log = agit_dir / "logs" / f"{name}.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            subprocess.Popen(cmd, cwd=wt, stdout=log.open("w"), stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True)
            print(f"launched {name} (log: {log})")
        else:
            print(f"\nto start {name}:\n  cd {shlex.quote(str(wt))} && "
                  f"claude --mcp-config {shlex.quote(str(mcp_cfg))} \"$(cat {shlex.quote(str(agit_dir / 'tasks' / (name + '.md')))})\"")
    if created:
        print("\nrun `agit watch` to keep conflict predictions fresh, `agit status` to see them.")


def cmd_status(args):
    store = Store(repo_root())
    if args.refresh:
        predict.check(store)
    agents = store.agents(active_only=False)
    if not agents:
        print("no agents. start some with: agit run \"task one\" \"task two\"")
        return
    leases = store.leases()
    print("AGENTS")
    for a in agents:
        snap = store.snapshot(a["name"])
        age = f"{int(time.time() - snap['at'])}s ago" if snap else "never"
        print(f"  {a['name']:<24} {a['status']:<8} {a['branch']:<32} snapshot {age}")
        print(f"    task: {a['task']}")
        for l in leases:
            if l["agent"] == a["name"]:
                print(f"    lease ({l['kind']}): {l['path']}")
    risks = store.risks()
    print("\nRISKS" + ("" if risks else "\n  none"))
    for r in risks:
        print(f"  {r['severity'].upper():<9} {r['a']} <-> {r['b']}: {', '.join(r['files'])}")
    notes = store.notes()[-args.notes:] if args.notes else []
    if notes:
        print("\nRECENT NOTES")
        for n in notes:
            print(f"  #{n['id']} [{n['agent']}/{n['topic']}] {n['text']}")


def cmd_check(args):
    store = Store(repo_root())
    risks, new = predict.check(store)
    conflicts = [r for r in risks if r[2] == "conflict"]
    for a, b, sev, files in risks:
        print(f"{sev.upper():<9} {a} <-> {b}: {', '.join(sorted(files))}")
    if not risks:
        print("no conflicts predicted")
    sys.exit(1 if conflicts else 0)


def cmd_watch(args):
    store = Store(repo_root())
    print(f"watching every {args.interval}s (ctrl-c to stop)")
    try:
        while True:
            _, new = predict.check(store)
            for a, b, _, files in new:
                print(f"{time.strftime('%H:%M:%S')} new conflict: {a} <-> {b} in {', '.join(sorted(files))}",
                      flush=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass


def cmd_done(args):
    store = Store(repo_root())
    store.set_status(args.agent, "done")
    store.release_lease(args.agent)
    print(f"{args.agent} marked done; its leases were released")


def cmd_hook(args):
    if args.name != "pre-commit":
        return
    try:
        top = gitutil.toplevel()
        store = Store(repo_root())
    except Exception as e:
        print(f"agit: skipping lease check ({e})", file=sys.stderr)
        return
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
                print(f"agit: {path} is hard-leased by {l['agent']}; commit blocked", file=sys.stderr)
            else:
                print(f"agit: note, {path} is soft-leased by {l['agent']}", file=sys.stderr)
    if blocked:
        print("agit: coordinate with that agent (post_note) or drop these files from the commit", file=sys.stderr)
        sys.exit(1)


def cmd_mcp(args):
    from . import mcp_server
    mcp_server.main()


def main(argv=None):
    p = argparse.ArgumentParser(prog="agit", description="Run many coding agents on one repo, with shared memory "
                                "and early conflict prediction.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="set up agit in the current repo")
    s.add_argument("--base", help="branch agents start from and land on (default: current branch)")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("run", help="create one worktree + branch + agent per task")
    s.add_argument("tasks", nargs="+")
    s.add_argument("--launch", action="store_true", help="start a headless Claude Code agent in each worktree")
    s.add_argument("--claude-args", default="--permission-mode acceptEdits",
                   help="extra arguments passed to claude when launching")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("status", help="agents, leases, predicted conflicts")
    s.add_argument("--refresh", action="store_true", help="run a fresh conflict check first")
    s.add_argument("--notes", type=int, default=5, help="how many recent notes to show")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("check", help="one conflict-prediction pass; exits 1 if any conflict is predicted")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("watch", help="keep predicting conflicts in a loop")
    s.add_argument("--interval", type=float, default=5)
    s.set_defaults(fn=cmd_watch)

    s = sub.add_parser("done", help="mark an agent finished and release its leases")
    s.add_argument("agent")
    s.set_defaults(fn=cmd_done)

    s = sub.add_parser("hook", help=argparse.SUPPRESS)
    s.add_argument("name")
    s.set_defaults(fn=cmd_hook)

    s = sub.add_parser("mcp", help="run the MCP server (used by agents' MCP config)")
    s.set_defaults(fn=cmd_mcp)

    args = p.parse_args(argv)
    try:
        args.fn(args)
    except gitutil.GitError as e:
        print(f"agit: {e}", file=sys.stderr)
        sys.exit(2)
