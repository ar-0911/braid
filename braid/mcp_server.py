"""MCP server (stdio, JSON-RPC 2.0) that connects each agent to braid's shared memory.

Started per agent by its MCP config with BRAID_AGENT=<name> and BRAID_REPO=<repo path>. No dependencies.
"""
import json
import os
import sys

from . import __version__, gitutil, land, predict
from .store import Store

PROTOCOL_VERSION = "2025-06-18"


def _obj(props=None, required=()):
    return {"type": "object", "properties": props or {}, "required": list(required)}


S = {"type": "string"}
TOOLS = [
    ("whoami", "Your agent name, branch, worktree, task and status.", _obj()),
    ("peers", "Every other agent in this repo: task, status, declared intents and leases.", _obj()),
    ("risks", "Fresh prediction of merge conflicts/overlaps between you and other agents or the base branch. "
              "Call before and after editing shared files.", _obj()),
    ("declare_intent", "Tell other agents which files/globs you plan to change and why. Do this before each "
                       "subtask. Returns any leases others hold on them.",
     _obj({"paths": {"type": "array", "items": S}, "description": S}, ["paths", "description"])),
    ("acquire_lease", "Claim a file, directory or glob. soft = signal ownership; hard = other agents' commits that "
                      "touch it are blocked. Fails if another agent holds a hard lease on it.",
     _obj({"path": S, "kind": {"type": "string", "enum": ["soft", "hard"]}, "ttl_seconds": {"type": "integer"}},
          ["path"])),
    ("release_lease", "Release one of your leases, or all of them if path is omitted.", _obj({"path": S})),
    ("post_note", "Share something other agents need to know (API change, decision, request). Set `to` to "
                  "address one agent; omit it for everyone.", _obj({"topic": S, "text": S, "to": S},
                                                                  ["topic", "text"])),
    ("read_notes", "Notes for you or everyone, including braid's conflict, landing and decision alerts. Pass the "
                   "highest id you've seen as since_id to get only new ones.",
     _obj({"since_id": {"type": "integer"}, "topic": S})),
    ("sync", "Merge the latest base branch into your branch (your uncommitted work is stashed and restored). "
             "If it reports conflicts, edit those files to keep both changes, then git add and git commit.", _obj()),
    ("ready_to_land", "Mark your work finished and ready to be merged into the base branch. Commit everything "
                      "first. Another agent will review it; braid then merges, runs tests and lands it.",
     _obj({"summary": S}, ["summary"])),
    ("pending_reviews", "Work from other agents that is waiting for a review. Review it with show_diff and review.",
     _obj()),
    ("show_diff", "The full diff an agent's branch would bring into the base branch.",
     _obj({"agent": S}, ["agent"])),
    ("review", "Record your review of another agent's work. verdict 'approve' lets it land; 'changes' blocks it "
               "until they push new commits. Be specific in the comment.",
     _obj({"agent": S, "verdict": {"type": "string", "enum": ["approve", "changes"]}, "comment": S},
          ["agent", "verdict", "comment"])),
    ("decisions", "Conflict resolutions that involve you, with their status.", _obj()),
    ("delegate", "LEAD SESSION ONLY. Hand a goal to braid: a planner splits it into parallel tasks with dependencies, "
                 "and braid starts one agent per task in waves, reviews, merges, tests and lands them on `base`. "
                 "Returns the plan. Follow progress with team_status.",
     _obj({"goal": S, "base": S, "max_agents": {"type": "integer"}}, ["goal"])),
    ("start_agents", "LEAD SESSION ONLY. Start one agent per task you have already split, all in parallel, landing "
                     "on `base` (default: the repo's base branch).",
     _obj({"tasks": {"type": "array", "items": S}, "base": S}, ["tasks"])),
    ("team_status", "Every agent's status, running plans with their progress, predicted conflicts and open decisions.",
     _obj()),
    ("vote", "Accept or object to an automatic conflict resolution that involves your work. An objection stops "
             "it from landing.",
     _obj({"decision_id": {"type": "integer"}, "vote": {"type": "string", "enum": ["accept", "object"]},
           "reason": S}, ["decision_id", "vote"])),
]


class Server:
    def __init__(self, repo, agent):
        self.store = Store(repo)
        self.agent = agent

    def me(self):
        a = self.store.agent(self.agent)
        if not a:
            raise RuntimeError(f"agent {self.agent!r} is not registered; start agents with `braid start`")
        return a

    def call(self, name, args):
        s, me = self.store, self.agent
        if name == "whoami":
            return s.agent(me) or {"name": me, "role": "lead session: you can delegate, start_agents and "
                                                         "watch team_status"}
        if name == "peers":
            leases = s.leases()
            return [{"name": a["name"], "task": a["task"], "status": a["status"], "branch": a["branch"],
                     "intents": [{"paths": i["paths"], "description": i["description"]} for i in s.intents(a["name"])],
                     "leases": [{"path": l["path"], "kind": l["kind"]} for l in leases if l["agent"] == a["name"]]}
                    for a in s.live_agents() if a["name"] != me]
        if name == "risks":
            predict.check(s)
            return s.risks(me) or "no conflicts or overlaps predicted"
        if name == "declare_intent":
            s.declare_intent(me, args["paths"], args["description"])
            clashes = [l for p in args["paths"] for l in s.overlapping_leases(p) if l["agent"] != me]
            return {"ok": True, "leased_by_others": clashes}
        if name == "acquire_lease":
            ok, others = s.acquire_lease(me, args["path"], args.get("kind", "soft"), args.get("ttl_seconds", 3600))
            if ok:
                return {"ok": True, "other_holders": others}
            place = s.wait_for_lease(me, args["path"])
            return {"ok": False, "other_holders": others, "queued": place,
                    "next": "you're in the queue for it; braid sends you a note when it's free. Work on other "
                            "parts meanwhile, or post_note the holder to coordinate."}
        if name == "release_lease":
            s.release_lease(me, args.get("path"))
            return {"ok": True}
        if name == "post_note":
            s.post_note(me, args["topic"], args["text"], args.get("to"))
            return {"ok": True}
        if name == "read_notes":
            notes = s.notes(args.get("since_id", 0), args.get("topic"), for_agent=me)
            if notes and not args.get("topic"):
                s.mark_notes_read(me, notes[-1]["id"])
            return notes
        if name == "sync":
            ok, msg, files = land.sync(s, me)
            return {"ok": ok, "message": msg, "conflicted_files": files}
        if name == "ready_to_land":
            a = self.me()
            if not gitutil.is_clean(a["worktree"]):
                return {"ok": False, "error": "you have uncommitted changes; commit them first"}
            unread = s.unread_notes(me)
            if unread:  # make sure warnings were seen before claiming to be done
                s.mark_notes_read(me, unread[-1]["id"])
                return {"ok": False, "error": "you have unread warnings about your work. Read them, deal with "
                                              "them, then call ready_to_land again.",
                        "notes": [{"id": n["id"], "topic": n["topic"], "text": n["text"]} for n in unread]}
            predict.check(s)
            behind = [r for r in s.risks(me) if r["a"] == me and r["b"].startswith("@")
                      and r["severity"] == "semantic"]  # text conflicts are left to the resolver
            if behind:
                return {"ok": False, "error": f"your work doesn't fit {behind[0]['b'][1:]} as it is now "
                                              f"({behind[0]['severity']}: {', '.join(behind[0]['files'])}). "
                                              "Call sync, fix it, commit, then call ready_to_land again."}
            s.update_agent(me, summary=args["summary"])
            s.set_status(me, "ready", args["summary"])
            s.post_note(me, "review", f"{me} is ready to land: {args['summary']}. Please review with show_diff.")
            return {"ok": True, "next": "braid will land your work once it is reviewed and tests pass. "
                                        "Meanwhile, review others' work with pending_reviews."}
        if name == "pending_reviews":
            out = []
            for a in s.agents(("ready",)):
                if a["name"] == me:
                    continue
                head = gitutil.rev(a["branch"], cwd=s.repo)
                if s.reviews(a["name"], head):
                    continue
                stat = gitutil.out("diff", "--stat", f"{s.agent_base(a)}...{a['branch']}", cwd=s.repo)
                out.append({"agent": a["name"], "task": a["task"], "summary": a["summary"], "diffstat": stat})
            return out or "nothing waiting for review"
        if name == "show_diff":
            a = s.agent(args["agent"])
            if not a:
                raise KeyError(f"no agent {args['agent']}")
            diff = gitutil.out("diff", f"{s.agent_base(a)}...{a['branch']}", cwd=s.repo)
            return diff[:80000] + ("\n[diff truncated]" if len(diff) > 80000 else "")
        if name == "review":
            target = args["agent"]
            if target == me:
                raise ValueError("you can't review your own work")
            a = s.agent(target)
            if not a:
                raise KeyError(f"no agent {target}")
            head = gitutil.rev(a["branch"], cwd=s.repo)
            s.add_review(target, me, head, args["verdict"], args["comment"])
            s.post_note(me, "review", f"Review of your work: {args['verdict']}. {args['comment']}", to=target)
            if args["verdict"] == "changes" and a["status"] == "ready":
                s.set_status(target, "active", f"changes requested by {me}")
            return {"ok": True}
        if name == "decisions":
            return s.decisions(agent=me) or "no decisions involve you"
        if name in ("delegate", "start_agents"):
            if s.agent(me):
                raise PermissionError("only the lead session can start agents; post_note to ask for help instead")
            from . import cli, planner
            base = args.get("base") or s.base_branch()
            cli.ensure_branch(s, base)
            if name == "start_agents":
                agents = [cli.create_agent(s, t, base=base) for t in args["tasks"]]
                cli.daemon_start(s, quiet=True)
                return {"started": [{"name": a["name"], "branch": a["branch"], "lands_on": base} for a in agents]}
            tasks = planner.ask_planner(s, args["goal"], base,
                                        args.get("max_agents") or int(s.cfg("plan.max_tasks")))
            pid = s.add_plan(args["goal"], base, tasks)
            started = cli.run_plan(s, pid)
            return {"plan": pid, "lands_on": base, "started_now": started,
                    "waves": [[t["id"] for t in w] for w in planner.waves(tasks)],
                    "tasks": [{k: t[k] for k in ("id", "title", "files", "depends_on")} for t in tasks]}
        if name == "team_status":
            plans = [{"id": p["id"], "goal": p["goal"], "base": p["base"],
                      "tasks": [{"id": t["id"], "status": t["status"], "agent": t["agent"]}
                                for t in s.plan_tasks(p["id"])]} for p in s.plans("running")]
            return {"agents": [{"name": a["name"], "status": a["status"], "task": a["task"][:200],
                                "lands_on": s.agent_base(a)} for a in s.agents()],
                    "plans": plans, "risks": s.risks(),
                    "open_decisions": [d for d in s.decisions() if d["status"] in ("proposed", "escalated")]}
        if name == "vote":
            d = s.decision(args["decision_id"])
            if not d:
                raise KeyError("no such decision")
            s.vote(d["id"], me, args["vote"], args.get("reason", ""))
            return {"ok": True, "decision_status": d["status"]}
        raise KeyError(f"unknown tool {name}")

    def handle(self, msg):
        method, mid = msg.get("method"), msg.get("id")
        if mid is None:
            return None  # notification
        if method == "initialize":
            return ok(mid, {
                "protocolVersion": msg.get("params", {}).get("protocolVersion", PROTOCOL_VERSION),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "braid", "version": __version__},
                "instructions": "braid connects agents working in parallel on one repo. Check peers and risks "
                                "before editing shared files, declare_intent before each subtask, read_notes often, "
                                "review others with pending_reviews, and finish with ready_to_land.",
            })
        if method == "ping":
            return ok(mid, {})
        if method == "tools/list":
            return ok(mid, {"tools": [{"name": n, "description": d, "inputSchema": sch} for n, d, sch in TOOLS]})
        if method == "tools/call":
            p = msg.get("params", {})
            try:
                result = self.call(p.get("name"), p.get("arguments") or {})
                text = result if isinstance(result, str) else json.dumps(result, indent=2, default=str)
                return ok(mid, {"content": [{"type": "text", "text": text}]})
            except Exception as e:  # tool errors go back to the model, not as protocol errors
                return ok(mid, {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True})
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}


def ok(mid, result):
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main():
    server = Server(os.environ.get("BRAID_REPO", os.getcwd()), os.environ.get("BRAID_AGENT", "human"))
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = server.handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
