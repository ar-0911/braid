"""MCP server (stdio, JSON-RPC 2.0) that gives each agent access to the shared memory.

Started per agent by its MCP config with AGIT_AGENT=<name> and AGIT_REPO=<repo path>.
No third-party dependencies.
"""
import json
import os
import sys

from . import predict
from .store import Store

PROTOCOL_VERSION = "2025-06-18"

TOOLS = [
    {
        "name": "whoami",
        "description": "Your agent name, branch, worktree and task.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "peers",
        "description": "Every other agent working in this repo right now: task, branch, declared intents, leases.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "risks",
        "description": "Predicted merge conflicts and file overlaps between you and other agents or the base branch. "
                       "Runs a fresh check first. Check this before and after editing shared files.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "declare_intent",
        "description": "Tell other agents which files or globs you plan to change and why. Do this before starting a subtask.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "paths": {"type": "array", "items": {"type": "string"}},
                "description": {"type": "string"},
            },
            "required": ["paths", "description"],
        },
    },
    {
        "name": "acquire_lease",
        "description": "Claim a file, directory or glob. 'soft' signals ownership; 'hard' makes other agents' commits "
                       "touching it fail. Fails if someone else holds a hard lease on it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "kind": {"type": "string", "enum": ["soft", "hard"], "default": "soft"},
                "ttl_seconds": {"type": "integer", "default": 3600},
            },
            "required": ["path"],
        },
    },
    {
        "name": "release_lease",
        "description": "Release one of your leases, or all of them if path is omitted.",
        "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}},
    },
    {
        "name": "post_note",
        "description": "Share a finding every agent should know, e.g. an API change, a decision, or a request to another agent.",
        "inputSchema": {
            "type": "object",
            "properties": {"topic": {"type": "string"}, "text": {"type": "string"}},
            "required": ["topic", "text"],
        },
    },
    {
        "name": "read_notes",
        "description": "Read notes from all agents (and conflict alerts from agit), optionally only newer than an id.",
        "inputSchema": {
            "type": "object",
            "properties": {"since_id": {"type": "integer", "default": 0}, "topic": {"type": "string"}},
        },
    },
]


class Server:
    def __init__(self, repo, agent):
        self.store = Store(repo)
        self.agent = agent

    def call(self, name, args):
        s, me = self.store, self.agent
        if name == "whoami":
            return s.agent(me) or {"name": me, "error": "not registered; run `agit run` to create agents"}
        if name == "peers":
            leases = s.leases()
            return [
                {**a, "intents": s.intents(a["name"]),
                 "leases": [l for l in leases if l["agent"] == a["name"]]}
                for a in s.agents() if a["name"] != me
            ]
        if name == "risks":
            predict.check(s)
            return s.risks(me)
        if name == "declare_intent":
            s.declare_intent(me, args["paths"], args["description"])
            clashes = [l for p in args["paths"] for l in s.overlapping_leases(p) if l["agent"] != me]
            return {"ok": True, "leased_by_others": clashes}
        if name == "acquire_lease":
            ok, others = s.acquire_lease(me, args["path"], args.get("kind", "soft"), args.get("ttl_seconds", 3600))
            return {"ok": ok, "other_holders": others}
        if name == "release_lease":
            s.release_lease(me, args.get("path"))
            return {"ok": True}
        if name == "post_note":
            s.post_note(me, args["topic"], args["text"])
            return {"ok": True}
        if name == "read_notes":
            return s.notes(args.get("since_id", 0), args.get("topic"))
        raise KeyError(f"unknown tool {name}")

    def handle(self, msg):
        method, mid = msg.get("method"), msg.get("id")
        if mid is None:
            return None  # notification
        if method == "initialize":
            client_version = msg.get("params", {}).get("protocolVersion", PROTOCOL_VERSION)
            return ok(mid, {
                "protocolVersion": client_version,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "agit", "version": "0.1.0"},
                "instructions": "Shared memory for agents working in parallel on one repo. "
                                "Call peers and risks before editing shared files; declare_intent before each subtask.",
            })
        if method == "ping":
            return ok(mid, {})
        if method == "tools/list":
            return ok(mid, {"tools": TOOLS})
        if method == "tools/call":
            p = msg.get("params", {})
            try:
                result = self.call(p.get("name"), p.get("arguments") or {})
                return ok(mid, {"content": [{"type": "text", "text": json.dumps(result, indent=2, default=str)}]})
            except Exception as e:  # tool errors are reported to the model, not as protocol errors
                return ok(mid, {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True})
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}


def ok(mid, result):
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main():
    repo = os.environ.get("AGIT_REPO", os.getcwd())
    agent = os.environ.get("AGIT_AGENT", "human")
    server = Server(repo, agent)
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
