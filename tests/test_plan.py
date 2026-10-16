import json
import shlex
import sys
import time
import unittest
from pathlib import Path

from helpers import ENV, RepoCase, braid, sh
from braid import land, planner
from braid.mcp_server import Server

FAKES = Path(__file__).resolve().parent / "fakes"
PLAN = {"tasks": [
    {"id": "login", "title": "Add login", "description": "add login()", "files": ["m.py"], "depends_on": []},
    {"id": "export", "title": "Add export", "description": "add export()", "files": ["m.py"], "depends_on": []},
    {"id": "report", "title": "Add report", "description": "report() uses login and export", "files": ["r.py"],
     "depends_on": ["login", "export"]},
]}


class ParsePlan(unittest.TestCase):
    def test_fenced_json_with_chatter(self):
        tasks = planner.parse_plan("Here you go:\n```json\n" + json.dumps(PLAN) + "\n```\nGood luck")
        self.assertEqual([t["id"] for t in tasks], ["login", "export", "report"])
        self.assertEqual([[t["id"] for t in w] for w in planner.waves(tasks)], [["login", "export"], ["report"]])

    def test_order_follows_dependencies_and_drops_unknown(self):
        tasks = planner.parse_plan(json.dumps({"tasks": [
            {"id": "ui", "title": "UI", "depends_on": ["api", "ghost"]},
            {"id": "api", "title": "API", "depends_on": []}]}))
        self.assertEqual([t["id"] for t in tasks], ["api", "ui"])
        self.assertEqual(tasks[1]["depends_on"], ["api"])

    def test_cycle_is_an_error(self):
        with self.assertRaises(planner.PlanError):
            planner.parse_plan(json.dumps({"tasks": [{"id": "a", "title": "A", "depends_on": ["b"]},
                                                      {"id": "b", "title": "B", "depends_on": ["a"]}]}))

    def test_not_json_is_an_error(self):
        with self.assertRaises(planner.PlanError):
            planner.parse_plan("I could not plan this")


def fake_agent_env(**plans):
    return {**ENV, **{f"BRAID_FAKE_{k.upper()}": json.dumps(v) for k, v in plans.items()}}


class FeatureBranchBase(RepoCase):
    def test_agents_land_on_a_feature_branch_not_main(self):
        braid("start", "--no-launch", "--no-daemon", "--base", "feature/big", "--name", "part", "part one",
              cwd=self.repo)
        a = self.store.agent("part")
        self.assertEqual(a["base"], "feature/big")
        wt = Path(a["worktree"])
        self.edit(wt, "return 1", "return 10")
        self.commit(wt)
        Server(self.repo, "part").call("ready_to_land", {"summary": "s"})
        self.store.set_cfg("review.required", "no")
        r = land.land(self.store, "part")
        self.assertTrue(r.ok, r.message)
        self.assertIn("landed on feature/big", r.message)
        self.assertIn("return 10", self.show("feature/big"))
        self.assertNotIn("return 10", self.show("main"))
        # other agents on main are not compared with agents on the feature branch
        self.edit(self.wt1, "return 1", "return 100")
        self.assertIn("no conflicts", braid("check", cwd=self.repo).stdout)


class DoEndToEnd(RepoCase):
    agents = ()

    def test_plan_runs_in_waves_and_finishes(self):
        for k, v in {"review.required": "no", "watch.interval": "0.5",
                     "agent.command": f"{shlex.quote(sys.executable)} {shlex.quote(str(FAKES / 'agent.py'))}",
                     "plan.command": f"{shlex.quote(sys.executable)} {shlex.quote(str(FAKES / 'planner.py'))}"}.items():
            braid("settings", k, v, cwd=self.repo)
        env = fake_agent_env(
            login={"file": "m.py", "desc": "add login", "append": "\n\ndef login():\n    return 'in'\n"},
            export={"file": "m.py", "desc": "add export", "append": "\n\ndef export():\n    return 'csv'\n"},
            report={"file": "m.py", "desc": "add report", "append": "\n\ndef report():\n    return login() + export()\n"})
        env["BRAID_FAKE_PLAN"] = json.dumps(PLAN)
        r = sh(sys.executable, "-m", "braid", "do", "--yes", "--base", "feature/app", "build the app",
               cwd=self.repo, env=env)
        self.assertIn("wave 2", r.stdout)
        self.assertIn("started 2 agent(s): login, export", r.stdout)
        try:
            deadline = time.time() + 60
            while time.time() < deadline and self.store.plans()[0]["status"] != "done":
                time.sleep(0.5)
            feed = braid("feed", "-n", "100", cwd=self.repo).stdout
            self.assertEqual(self.store.plans()[0]["status"], "done", feed)
            text = self.show("feature/app")
            for fn in ("def login", "def export", "def report"):
                self.assertIn(fn, text)
            self.assertNotIn("def login", self.show("main"))
            # report only started after both of its dependencies were on feature/app
            started = [e for e in self.store.events(200) if e["kind"] == "plan" and "started report" in e["text"]]
            landed = [e for e in self.store.events(200) if e["kind"] == "land"]
            self.assertTrue(started and len(landed) == 3)
            self.assertGreater(started[0]["id"], max(e["id"] for e in landed if e["agent"] in ("login", "export")))
            self.assertIn("#1  done      3/3 landed  on feature/app", braid("plans", cwd=self.repo).stdout)
        finally:
            braid("stop", "--all", cwd=self.repo, check=False)


class LeadSession(RepoCase):
    agents = ()

    def test_delegate_from_your_own_claude_session(self):
        self.store.set_cfg("plan.command", f"{shlex.quote(sys.executable)} {shlex.quote(str(FAKES / 'planner.py'))}")
        self.store.set_cfg("agent.command", "true")
        import os
        os.environ["BRAID_FAKE_PLAN"] = json.dumps(PLAN)
        try:
            lead = Server(self.repo, "human")
            out = lead.call("delegate", {"goal": "build the app"})
        finally:
            del os.environ["BRAID_FAKE_PLAN"]
            from braid import cli
            cli.daemon_stop(self.store)
        self.assertEqual(out["waves"], [["login", "export"], ["report"]])
        self.assertEqual(sorted(out["started_now"]), ["export", "login"])
        status = lead.call("team_status", {})
        self.assertEqual(status["plans"][0]["tasks"][2]["status"], "waiting")
        with self.assertRaises(PermissionError):
            Server(self.repo, "login").call("start_agents", {"tasks": ["sneaky"]})


if __name__ == "__main__":
    unittest.main()
