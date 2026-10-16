"""braid do: turn one goal into a plan of parallel tasks with dependencies, and run it in waves.

A planner agent reads the repo and the goal and returns tasks, each owning a set of files and naming the
tasks it depends on. braid starts every task whose dependencies have landed, all in parallel; when a task
lands, the tasks waiting on it start from the updated base, so they build on real code, not guesses.
"""
import json
import re
import shlex
import subprocess

from . import gitutil

MAX_LISTING = 400

PLAN_PROMPT = """You are the planner for a team of AI coding agents that will work IN PARALLEL on this repository,
each on its own git branch. Split the goal below into tasks.

Goal: {goal}

Rules:
- Between 1 and {max_tasks} tasks. Fewer, larger tasks are better than many tiny ones. One task is fine for a small goal.
- Each task must be completable and testable on its own once its dependencies have landed.
- Give each task the files or directories it will create or change ("files"), and keep tasks' files apart, so
  agents rarely edit the same file. Shared foundations (data models, interfaces, config, schemas) go in an early
  task that the others depend on.
- "depends_on" lists ids of tasks that must land first. Only add a dependency when the task truly needs that code.
- The description is the agent's whole brief: what to build, where, how it fits with the other tasks, and how to
  test it. Mention names of functions, endpoints or modules other tasks will rely on, so they agree.
- No separate tasks only for reviewing or testing; every task includes its own tests.

The repository has {count} tracked files{listing_note}:
{listing}
{hotspots}{readme}
Read any files you need to understand the codebase. Then answer with ONLY a JSON object, no other text:
{{"tasks": [{{"id": "short-kebab-id", "title": "one line", "description": "the brief", "files": ["path/or/dir/"], "depends_on": []}}]}}
"""


class PlanError(Exception):
    pass


def hotspots(store, base, commits=300, top=8):
    """Files changed most often in recent history: likely to be touched by several tasks."""
    log = gitutil.out("log", "-n", str(commits), "--format=", "--name-only", base, cwd=store.repo)
    counts = {}
    for f in log.splitlines():
        if f:
            counts[f] = counts.get(f, 0) + 1
    return [f for f, n in sorted(counts.items(), key=lambda kv: -kv[1])[:top] if n >= 3]


def repo_context(store, base):
    files = gitutil.out("ls-tree", "-r", "--name-only", base, cwd=store.repo).splitlines()
    listing = "\n".join(files[:MAX_LISTING])
    note = f" (first {MAX_LISTING} shown)" if len(files) > MAX_LISTING else ""
    readme = ""
    for name in ("README.md", "README", "readme.md", "CLAUDE.md", "AGENTS.md"):
        if name in files:
            text = gitutil.out("show", f"{base}:{name}", cwd=store.repo)[:3000]
            readme += f"\n{name} (start):\n{text}\n"
    return len(files), listing, note, readme


def ask_planner(store, goal, base, max_tasks):
    count, listing, note, readme = repo_context(store, base)
    hot = hotspots(store, base)
    hot_s = ("\nHotspot files, changed most often, that several tasks may want to edit: " + ", ".join(hot)
             + ". Put changes to a hotspot in ONE task (often the early foundation task) instead of several.\n"
             if hot else "")
    prompt = PLAN_PROMPT.format(goal=goal, max_tasks=max_tasks, count=count, listing=listing or "(empty repo)",
                                listing_note=note, readme=readme, hotspots=hot_s)
    cmd = store.cfg("plan.command").format(prompt=shlex.quote(prompt))
    try:
        proc = subprocess.run(cmd, shell=True, cwd=store.repo, capture_output=True, text=True, timeout=1200,
                              stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise PlanError("the planner timed out")
    if proc.returncode != 0:
        raise PlanError(f"the planner failed: {(proc.stderr or proc.stdout).strip()[-500:]}")
    return parse_plan(proc.stdout, max_tasks, serialize=store.cfg_bool("plan.serialize"))


def parse_plan(text, max_tasks=50, serialize=True):
    """Pull the JSON plan out of the planner's answer and validate it. Returns tasks in a runnable order."""
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    try:
        data = json.loads(raw)
    except ValueError:
        raise PlanError(f"the planner's answer wasn't valid JSON: {text.strip()[:300]}")
    tasks = data.get("tasks") if isinstance(data, dict) else data
    if not isinstance(tasks, list) or not tasks:
        raise PlanError("the plan has no tasks")
    seen, clean = set(), []
    for i, t in enumerate(tasks):
        if not isinstance(t, dict) or not t.get("title"):
            raise PlanError(f"task {i + 1} has no title")
        tid = re.sub(r"[^a-z0-9]+", "-", str(t.get("id") or t["title"]).lower()).strip("-")[:28] or f"task-{i + 1}"
        while tid in seen:
            tid += "-2"
        seen.add(tid)
        clean.append({"id": tid, "title": str(t["title"]).strip(), "description": str(t.get("description", "")),
                      "files": [str(f) for f in t.get("files", []) if f],
                      "depends_on": [re.sub(r"[^a-z0-9]+", "-", str(d).lower()).strip("-") for d in
                                     t.get("depends_on", [])]})
    ids = {t["id"] for t in clean}
    for t in clean:
        t["depends_on"] = [d for d in t["depends_on"] if d in ids and d != t["id"]]
    if len(clean) > max_tasks:
        raise PlanError(f"the plan has {len(clean)} tasks, more than the limit of {max_tasks}")
    tasks = order(clean)
    return order(serialize_shared(tasks)) if serialize else tasks


def serialize_shared(tasks):
    """Tasks that own the same file and could run at the same time are chained, earlier one first.

    Only exact paths of files braid can't merge by function or class (config, JSON, YAML, docs...) count:
    two tasks adding different functions to the same code file still merge cleanly, in parallel."""
    from .structmerge import SUPPORTED_EXT
    def reaches(src, dst):
        stack, seen = [src], set()
        while stack:
            cur = stack.pop()
            if cur == dst:
                return True
            if cur not in seen:
                seen.add(cur)
                stack += by_id[cur]["depends_on"]
        return False

    by_id = {t["id"]: t for t in tasks}
    for i, early in enumerate(tasks):
        mine = {f for f in early["files"] if not f.endswith("/") and not any(c in f for c in "*?[")
                and "." + f.rsplit(".", 1)[-1] not in SUPPORTED_EXT}
        for late in tasks[i + 1:]:
            if mine & set(late["files"]) and not reaches(late["id"], early["id"]) \
                    and not reaches(early["id"], late["id"]):
                late["depends_on"].append(early["id"])
                late.setdefault("serialized_after", []).append(early["id"])
    return tasks


def order(tasks):
    """Topological order; raises PlanError on a dependency cycle."""
    by_id, done, out = {t["id"]: t for t in tasks}, set(), []
    while len(out) < len(tasks):
        ready = [t for t in tasks if t["id"] not in done and set(t["depends_on"]) <= done]
        if not ready:
            stuck = [t["id"] for t in tasks if t["id"] not in done]
            raise PlanError(f"the plan's dependencies form a cycle between: {', '.join(stuck)}")
        for t in ready:
            done.add(t["id"])
            out.append(by_id[t["id"]])
    return out


def waves(tasks):
    """Group tasks into the waves they will run in (each wave waits for the previous ones)."""
    level = {}
    for t in tasks:  # tasks are in topological order
        level[t["id"]] = 1 + max([level[d] for d in t["depends_on"]] or [0])
    return [[t for t in tasks if level[t["id"]] == n] for n in range(1, max(level.values()) + 1)]


def task_brief(plan, task, tasks):
    others = [f"- {t['id']}: {t['title']}" + (f" (owns {', '.join(t['files'])})" if t["files"] else "")
              + (f" [after {', '.join(t['depends_on'])}]" if t["depends_on"] else "")
              for t in tasks if t["id"] != task["id"]]
    brief = f"{task['title']}\n\n{task['description']}".strip()
    if task["files"]:
        brief += f"\n\nYou own: {', '.join(task['files'])}. Keep your changes there where you can."
    if task["depends_on"]:
        brief += (f"\n\nThese tasks already landed on {plan['base']} and are in your branch: "
                  f"{', '.join(task['depends_on'])}. Build on their code.")
    brief += f"\n\nThis is part of a larger goal: {plan['goal']}"
    if others:
        brief += "\nOther tasks in the plan, worked on by other agents:\n" + "\n".join(others)
    return brief


def advance(store, start_task):
    """Start every task whose dependencies have landed; mark plans done. start_task(plan, task, brief) -> agent name."""
    started = []
    for plan in store.plans("running"):
        tasks = store.plan_tasks(plan["id"])
        for t in tasks:  # sync task status from its agent
            if t["agent"]:
                a = store.agent(t["agent"])
                status = {"landed": "landed", "done": "landed"}.get(a["status"] if a else "", None)
                if status and t["status"] != status:
                    store.update_plan_task(plan["id"], t["id"], status=status)
                    t["status"] = status
        landed = {t["id"] for t in tasks if t["status"] == "landed"}
        for t in tasks:
            if t["status"] == "waiting" and set(t["depends_on"]) <= landed:
                name = start_task(plan, t, task_brief(plan, t, tasks))
                store.update_plan_task(plan["id"], t["id"], agent=name, status="running")
                store.event("plan", f"plan #{plan['id']}: started {t['id']} as {name}", name)
                started.append(name)
        if all(t["status"] == "landed" for t in tasks):
            store.set_plan_status(plan["id"], "done")
            store.event("plan", f"plan #{plan['id']} is done: every task landed on {plan['base']}")
            if plan["push"]:
                from .land import push_base
                push_base(store)
    return started
