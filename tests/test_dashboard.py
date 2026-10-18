"""`braid dashboard`: the page's API reads the same state as the CLI and runs the real commands."""
import json
import threading
import time
import urllib.error
import urllib.request

from helpers import RepoCase


class Dashboard(RepoCase):
    def setUp(self):
        super().setUp()
        from braid import dashboard
        self.httpd, url = dashboard.serve(self.repo, port=0, token="k3y")
        self.base = url.split("/?")[0]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        super().tearDown()

    def call(self, path, body=None, token="k3y"):
        req = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(),
                                     headers={"X-Braid-Token": token} if token else {})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def run_job(self, *argv):
        code, body = self.call("/api/run", {"argv": list(argv)})
        self.assertEqual(code, 200, body)
        jid = json.loads(body)["job"]
        for _ in range(200):
            job = json.loads(self.call(f"/api/jobs/{jid}")[1])
            if job["rc"] is not None:
                return job
            time.sleep(0.1)
        self.fail("job never finished")

    def test_needs_the_key(self):
        self.assertEqual(self.call("/api/state", token=None)[0], 403)
        self.assertEqual(self.call("/api/state", token="wrong")[0], 403)
        code, page = self.call("/?t=k3y", token=None)
        self.assertEqual(code, 200)
        self.assertIn('content="k3y"', page)

    def test_state_matches_the_cli(self):
        s = json.loads(self.call("/api/state")[1])
        self.assertEqual(s["base"], "main")
        self.assertEqual({a["name"] for a in s["agents"]}, {"task-one", "task-two"})
        self.assertTrue(all(a["interactive"] for a in s["agents"]))  # --no-launch: you drive them
        self.assertIn("test.command", s["settings"])

    def test_every_command_has_a_form(self):
        names = {c["name"] for c in json.loads(self.call("/api/commands")[1])}
        for cmd in ("do", "start", "land", "review", "vote", "approve", "reject", "settings", "plans", "resume"):
            self.assertIn(cmd, names)
        for internal in ("hook", "merge-driver", "mcp", "dashboard"):
            self.assertNotIn(internal, names)
        do = next(c for c in json.loads(self.call("/api/commands")[1]) if c["name"] == "do")
        self.assertIn("--yes", [a["flag"] for a in do["args"]])

    def test_runs_the_real_command(self):
        job = self.run_job("chat", "--post", "use the v2 API", "--to", "task-one")
        self.assertEqual(job["rc"], 0, job["out"])
        self.assertTrue(any(n["text"] == "use the v2 API" and n["to_agent"] == "task-one"
                            for n in self.store.notes()))
        job = self.run_job("settings", "watch.interval", "9")
        self.assertEqual(job["rc"], 0, job["out"])
        self.assertEqual(json.loads(self.call("/api/state")[1])["settings"]["watch.interval"], "9")

    def test_posts_need_the_header_and_endless_commands_are_refused(self):
        self.assertEqual(self.call("/api/run", {"argv": ["check"]}, token=None)[0], 403)
        for argv in (["status", "--live"], ["feed", "-f"], ["watch"], ["hook", "pre-commit"]):
            code, body = self.call("/api/run", {"argv": argv})
            self.assertEqual(code, 400, argv)

    def test_agent_diff(self):
        self.edit(self.wt1, "return 1", "return 10")
        self.commit(self.wt1)
        code, body = self.call("/api/diff?kind=agent&ref=task-one")
        self.assertEqual(code, 200, body)
        self.assertIn("+    return 10", json.loads(body)["diff"])
        self.assertEqual(self.call("/api/diff?kind=agent&ref=nobody")[0], 404)


if __name__ == "__main__":
    import unittest
    unittest.main()
