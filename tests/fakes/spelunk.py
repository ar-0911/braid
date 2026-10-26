"""Fake Spelunk: answers overview, impact --json and facts the way the real CLI does, from canned data.

facts parses Python with ast so the semantic-conflict tests see real symbols and call sites."""
import ast
import json
import os
import sys

args = sys.argv[1:]
log = os.environ.get("BRAID_FAKE_SPELUNK_LOG")
if log:
    with open(log, "a") as f:
        f.write(json.dumps({"args": args, "cwd": os.getcwd()}) + "\n")
cmd = args[0] if args else ""
if cmd == "--version":
    print("0.3.0")
elif cmd == "overview":
    print("# proj\nModules (directory, files, lines → depends on):\n  core   2   40\n  api    1   10  → core")
elif cmd == "impact":
    print(json.dumps({"base": args[1], "head": args[args.index("--head") + 1], "files": [],
                      "dependents": [{"path": "api.py", "depth": 1, "via": "m.py"}],
                      "modules": [{"path": "", "changed": 1, "affected": 1}],
                      "routes": [{"method": "GET", "path": "/items", "file": "api.py", "line": 3,
                                  "reason": "calls a()"}],
                      "tests": [{"path": "test_m.py", "reason": "imports m.py"}], "untested": ["other.py"],
                      "env": [], "risks": [{"kind": "swallowed-error", "severity": "high", "title": "error ignored",
                                            "detail": "", "locations": [{"path": "m.py", "line": 4}]}]}))
elif cmd == "facts":
    out = []
    for f in json.load(sys.stdin)["files"]:
        if not f["path"].endswith(".py"):
            continue
        tree = ast.parse(f["text"])
        lines = f["text"].splitlines()
        symbols = [{"name": n.name, "kind": "function", "line": n.lineno, "endLine": n.end_lineno,
                    "exported": True, "signature": lines[n.lineno - 1].strip()}
                   for n in tree.body if isinstance(n, ast.FunctionDef)]
        calls = [[n.func.id, n.lineno] for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
        out.append({"path": f["path"], "language": "python", "symbols": symbols, "callSites": calls})
    print(json.dumps({"files": out}))
elif cmd == "mcp":
    pass
else:
    sys.exit(2)
