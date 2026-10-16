"""Fake agent: makes the edit described by BRAID_FAKE_<name>, commits, reviews peers, then becomes ready."""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.environ["PYTHONPATH"].split(os.pathsep)[0])
from braid.mcp_server import Server  # noqa: E402

name = os.environ["BRAID_AGENT"]
srv = Server(os.environ["BRAID_REPO"], name)
plan = json.loads(os.environ[f"BRAID_FAKE_{name.replace('-', '_').upper()}"])
srv.call("peers", {})
srv.call("declare_intent", {"paths": [plan["file"]], "description": plan["desc"]})
with open(plan["file"], "a") as f:
    f.write(plan["append"])
subprocess.run(["git", "commit", "-qam", plan["desc"]], check=True)
srv.call("risks", {})
print(json.dumps(srv.call("ready_to_land", {"summary": plan["desc"]})))
deadline = time.time() + 20
while time.time() < deadline:  # review whoever is waiting, like a good teammate
    pending = srv.call("pending_reviews", {})
    if isinstance(pending, list):
        for p in pending:
            srv.call("review", {"agent": p["agent"], "verdict": "approve", "comment": "looks good"})
        break
    time.sleep(0.2)
