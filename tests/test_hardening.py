"""Fixes for the known failure cases: semantic conflicts, generated files, ignored warnings, big repos,
wrong resolutions, flaky tests, shared files in plans, and lease queues."""
import json
import os
import shlex
import sys
import unittest
from pathlib import Path

from helpers import RepoCase, braid, sh
from braid import cli, land, planner, predict
from braid.mcp_server import Server

FAKES = Path(__file__).resolve().parent / "fakes"
PY = shlex.quote(sys.executable)


def risk(store, severity):
    return [r for r in store.risks() if r["severity"] == severity]


USE = "from notes import load_notes\n\nx = load_notes()\n"


class Semantic(RepoCase):
    def setUp(self):
        super().setUp()
        (self.repo / "notes.py").write_text("def load_notes():\n    return []\n")
        sh("git", "add", ".", cwd=self.repo)
        sh("git", "commit", "-qm", "notes", cwd=self.repo)
        for wt in (self.wt1, self.wt2):
            sh("git", "merge", "-q", "main", cwd=wt)

    def test_rename_on_one_side_and_new_use_on_the_other(self):
        self.edit(self.wt1, "def load_notes", "def read_notes", path="notes.py")
        self.edit(self.wt2, "x = 1\n", USE, path="other.py")
        predict.check(self.store)
        sem = risk(self.store, "semantic")
        self.assertEqual(len(sem), 1, self.store.risks())
        self.assertIn("other.py uses load_notes()", sem[0]["files"])
        texts = [n["text"] for n in self.store.notes(for_agent="task-one") if n["topic"] == "conflict"]
        self.assertTrue(any("removed or renamed" in t for t in texts))

    def test_moved_function_is_not_reported(self):
        (self.wt1 / "notes.py").write_text("from helpers import *\n")
        (self.wt1 / "helpers.py").write_text("def load_notes():\n    return []\n")
        self.edit(self.wt2, "x = 1\n", USE, path="other.py")
        predict.check(self.store)
        self.assertEqual(risk(self.store, "semantic"), [])

    def test_against_a_base_that_already_renamed_it(self):
        self.edit(self.wt1, "def load_notes", "def read_notes", path="notes.py")
        self.commit(self.wt1)
        Server(self.repo, "task-one").call("ready_to_land", {"summary": "rename"})
        self.store.set_cfg("review.required", "no")
        self.assertTrue(land.land(self.store, "task-one").ok)
        self.edit(self.wt2, "x = 1\n", USE, path="other.py")
        self.commit(self.wt2)
        predict.check(self.store)  # the watcher warns task-two
        r = Server(self.repo, "task-two").call("ready_to_land", {"summary": "uses a"})
        self.assertFalse(r["ok"])
        self.assertIn("unread warnings", r["error"])
        r = Server(self.repo, "task-two").call("ready_to_land", {"summary": "uses a"})
        self.assertFalse(r["ok"])  # still broken against main: must sync and fix first
        self.assertIn("semantic", r["error"])

    def test_tests_on_predicted_merge(self):
        self.store.set_cfg("test.command", f"{PY} -c \"import m; assert m.a() + m.b() != 110\"")
        self.edit(self.wt1, "return 1", "return 10")
        self.edit(self.wt2, "return 2", "return 100")
        self.assertEqual(predict.test_merges(self.store), [])  # uncommitted work isn't tested
        self.commit(self.wt1)
        self.commit(self.wt2)
        predict.check(self.store)
        self.assertEqual(risk(self.store, "overlap")[0]["a"], "task-one")  # merges cleanly
        self.assertEqual(predict.test_merges(self.store, budget=3), [("task-one", "task-two", False)])
        predict.check(self.store)
        self.assertEqual(risk(self.store, "semantic")[0]["files"], ["tests fail when merged"])
        self.assertTrue(any("fail on the combination" in n["text"] for n in self.store.notes(for_agent="task-two")))
        self.assertEqual(predict.test_merges(self.store), [])  # cached: not run again

    def test_side_that_fails_alone_is_not_a_merge_problem(self):
        self.store.set_cfg("test.command", f"{PY} -c \"import m; assert m.a() != 10\"")
        self.edit(self.wt1, "return 1", "return 10")
        self.edit(self.wt2, "return 2", "return 100")
        self.commit(self.wt1)
        self.commit(self.wt2)
        self.assertEqual(predict.test_merges(self.store, budget=3), [])
        predict.check(self.store)
        self.assertEqual(risk(self.store, "semantic"), [])


class GeneratedFiles(RepoCase):
    def setUp(self):
        super().setUp()
        # gen.txt is "built" from the list of functions in m.py
        (self.repo / "gen.py").write_text(
            "import re\nopen('gen.txt', 'w').write('\\n'.join(re.findall(r'def (\\w+)', open('m.py').read())) + '\\n')\n")
        sh(sys.executable, "gen.py", cwd=self.repo)
        sh("git", "add", ".", cwd=self.repo)
        sh("git", "commit", "-qm", "gen", cwd=self.repo)
        for wt in (self.wt1, self.wt2):
            sh("git", "merge", "-q", "main", cwd=wt)
        self.store.set_cfg("regen", f"gen.txt={PY} gen.py")
        self.store.set_cfg("review.required", "no")

    def add_fn(self, wt, fn):
        with open(wt / "m.py", "a") as f:
            f.write(f"\n\ndef {fn}():\n    return 0\n")
        sh(sys.executable, "gen.py", cwd=wt)
        self.commit(wt, fn)

    def test_conflicting_generated_file_is_rebuilt(self):
        self.add_fn(self.wt1, "login")
        self.add_fn(self.wt2, "export")
        predict.check(self.store)
        self.assertEqual(risk(self.store, "conflict"), [])  # gen.txt will be rebuilt, not a conflict
        for srv in ("task-one", "task-two"):
            Server(self.repo, srv).call("ready_to_land", {"summary": "x"})
        self.assertTrue(land.land(self.store, "task-one").ok)
        r = land.land(self.store, "task-two")
        self.assertTrue(r.ok, r.message)
        self.assertEqual(self.show("main", "gen.txt"), "a\nb\nlogin\nexport\n")
        self.assertTrue(any(e["kind"] == "regen" for e in self.store.events(50)))


class SecondOpinion(RepoCase):
    def test_checker_can_reject_a_resolution(self):
        self.store.set_cfg("review.required", "no")
        self.store.set_cfg("resolve.command", f"{PY} {shlex.quote(str(FAKES / 'resolver.py'))} both")
        one, two = Server(self.repo, "task-one"), Server(self.repo, "task-two")
        for srv, wt, new in ((one, self.wt1, "return 10"), (two, self.wt2, "return 100")):
            self.edit(wt, "return 1", new)
            self.commit(wt)
            srv.call("ready_to_land", {"summary": "x"})
        self.assertTrue(land.land(self.store, "task-one").ok)
        os.environ["BRAID_FAKE_VERDICT"] = "changes"
        try:
            r = land.land(self.store, "task-two")
        finally:
            del os.environ["BRAID_FAKE_VERDICT"]
        self.assertFalse(r.ok)
        self.assertIn("second check rejected", r.message)
        self.assertEqual(self.store.agent("task-two")["status"], "blocked")
        self.assertNotIn("return 100", self.show("main"))


class FlakyTests(RepoCase):
    def setUp(self):
        super().setUp()
        self.store.set_cfg("review.required", "no")
        self.edit(self.wt1, "return 1", "return 10")
        self.commit(self.wt1)
        Server(self.repo, "task-one").call("ready_to_land", {"summary": "x"})

    def test_pass_on_retry_lands_and_is_flagged(self):
        counter = Path(self.tmp.name) / "runs"
        self.store.set_cfg("test.command", f"{PY} -c \"import pathlib,sys; p=pathlib.Path('{counter}'); "
                                           f"n=int(p.read_text()) if p.exists() else 0; p.write_text(str(n+1)); "
                                           f"sys.exit(1 if n == 0 else 0)\"")
        r = land.land(self.store, "task-one")
        self.assertTrue(r.ok, r.message)
        self.assertTrue(any(e["kind"] == "flaky" for e in self.store.events(50)))

    def test_broken_base_does_not_blame_the_agent(self):
        self.store.set_cfg("test.command", f"{PY} -c \"import sys; sys.exit(1)\"")
        r = land.land(self.store, "task-one")
        self.assertFalse(r.ok)
        self.assertTrue(r.waiting)
        self.assertIn("fail on main itself", r.message)
        self.assertEqual(self.store.agent("task-one")["status"], "ready")  # not blocked
        self.assertTrue(land.base_tests_red(self.store, "main"))
        r = land.land(self.store, "task-one")  # same work, same base: no new test run
        self.assertIn("fix main first", r.message)


class SharedFilesInPlans(unittest.TestCase):
    def test_tasks_sharing_a_config_file_run_in_order_but_code_files_stay_parallel(self):
        plan = {"tasks": [
            {"id": "api", "title": "API", "files": ["api.py", "config.json"]},
            {"id": "ui", "title": "UI", "files": ["ui.py", "config.json"]},
            {"id": "cli", "title": "CLI", "files": ["api.py"]}]}
        tasks = planner.parse_plan(json.dumps(plan))
        waves = [[t["id"] for t in w] for w in planner.waves(tasks)]
        self.assertEqual(waves, [["api", "cli"], ["ui"]])


class LeaseQueue(RepoCase):
    def test_waiter_is_told_when_the_lease_frees(self):
        one, two = Server(self.repo, "task-one"), Server(self.repo, "task-two")
        self.assertTrue(one.call("acquire_lease", {"path": "m.py", "kind": "hard"})["ok"])
        r = two.call("acquire_lease", {"path": "m.py", "kind": "hard"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["queued"], 1)
        one.call("release_lease", {"path": "m.py"})
        notes = [n for n in self.store.notes(for_agent="task-two") if n["topic"] == "lease"]
        self.assertIn("m.py is free now", notes[-1]["text"])
        self.assertTrue(two.call("acquire_lease", {"path": "m.py", "kind": "hard"})["ok"])


class BigRepos(RepoCase):
    def test_unchanged_worktree_is_not_snapshotted_again(self):
        self.edit(self.wt1, "return 1", "return 10")
        predict.snapshot_all(self.store)
        at = self.store.snapshot("task-one")["at"]
        predict.snapshot_all(self.store)
        self.assertEqual(self.store.snapshot("task-one")["at"], at)
        self.edit(self.wt1, "return 10", "return 11")
        predict.snapshot_all(self.store)
        self.assertNotEqual(self.store.snapshot("task-one")["at"], at)

    def test_init_turns_on_the_untracked_cache(self):
        self.assertEqual(sh("git", "config", "core.untrackedCache", cwd=self.repo).stdout.strip(), "true")


if __name__ == "__main__":
    unittest.main()
