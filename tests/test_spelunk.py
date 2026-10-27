"""Optional Spelunk support: planner context, agents' MCP tools, semantic conflicts and approval impact.

A fake `spelunk` (tests/fakes/spelunk.py) stands in for the real one; with Spelunk off nothing changes."""
import json
import os
import shlex
import sys
from pathlib import Path

from helpers import ENV, RepoCase, braid, sh
from braid import approve, cli, planner, predict, review_page, semantic, spelunk
from braid.mcp_server import Server

FAKES = Path(__file__).resolve().parent / "fakes"
PY = shlex.quote(sys.executable)
FAKE = f"{PY} {shlex.quote(str(FAKES / 'spelunk.py'))}"


class SpelunkCase(RepoCase):
    def setUp(self):
        super().setUp()
        self.store.set_cfg("spelunk", "on")
        self.store.set_cfg("spelunk.command", FAKE)
        self.log = Path(self.tmp.name) / "spelunk.log"
        os.environ["BRAID_FAKE_SPELUNK_LOG"] = ENV["BRAID_FAKE_SPELUNK_LOG"] = str(self.log)

    def tearDown(self):
        os.environ.pop("BRAID_FAKE_SPELUNK_LOG", None)
        ENV.pop("BRAID_FAKE_SPELUNK_LOG", None)
        os.environ.pop("BRAID_FAKE_PROMPT_LOG", None)
        super().tearDown()

    def calls(self):
        return [json.loads(l) for l in self.log.read_text().splitlines()] if self.log.exists() else []


class Detection(SpelunkCase):
    def test_off_auto_and_on(self):
        self.assertTrue(spelunk.enabled(self.store))
        self.store.set_cfg("spelunk", "off")
        self.assertFalse(spelunk.enabled(self.store))
        self.assertIsNone(spelunk.impact(self.store, "main", "main"))
        self.store.set_cfg("spelunk", "auto")
        self.store.set_cfg("spelunk.command", "no-such-spelunk-binary")
        self.assertFalse(spelunk.enabled(self.store))  # auto: only when it's on PATH

    def test_a_failing_spelunk_falls_back(self):
        self.store.set_cfg("spelunk.command", f"{PY} -c 'import sys; sys.exit(3)'")
        self.assertEqual(spelunk.overview(self.store, "main"), "")
        self.assertIsNone(spelunk.impact(self.store, "main", "main"))


class Planner(SpelunkCase):
    def test_planner_prompt_carries_the_module_map(self):
        prompt_log = Path(self.tmp.name) / "prompt.txt"
        os.environ["BRAID_FAKE_PROMPT_LOG"] = str(prompt_log)
        os.environ["BRAID_FAKE_PLAN"] = json.dumps({"tasks": [{"id": "a", "title": "A", "files": ["m.py"]}]})
        self.store.set_cfg("plan.command", f"{PY} {shlex.quote(str(FAKES / 'planner.py'))} {{prompt}}")
        tasks = planner.ask_planner(self.store, "do it", "main", 3)
        self.assertEqual([t["id"] for t in tasks], ["a"])
        text = prompt_log.read_text()
        self.assertIn("Spelunk's map of the code", text)
        self.assertIn("api    1   10  → core", text)
        overview = [c for c in self.calls() if c["args"] == ["overview"]][0]
        self.assertTrue(overview["cwd"].endswith(".spelunk/proj"))  # indexed in its own checkout of main


class AgentTools(SpelunkCase):
    def test_new_agents_get_spelunk_mcp_tools_on_their_worktree(self):
        braid("start", "--no-launch", "--no-daemon", "Task Three", cwd=self.repo)
        a = self.store.agent("task-three")
        cfg = json.loads(cli.agent_paths(self.store, "task-three")[0].read_text())
        sp = cfg["mcpServers"]["spelunk"]
        self.assertEqual(sp["args"][-3:], ["mcp", "-C", str(a["worktree"])])
        self.assertIn("braid", cfg["mcpServers"])
        task = cli.agent_paths(self.store, "task-three")[1].read_text()
        self.assertIn("Spelunk's MCP tools", task)

    def test_off_means_braid_only(self):
        self.store.set_cfg("spelunk", "off")
        cfg = json.loads(cli.write_mcp_config(self.store, "task-one").read_text())
        self.assertEqual(list(cfg["mcpServers"]), ["braid"])


class SemanticWithSpelunk(SpelunkCase):
    def setUp(self):
        super().setUp()
        (self.repo / "notes.py").write_text("def save_note(text):\n    return text\n")
        sh("git", "add", ".", cwd=self.repo)
        sh("git", "commit", "-qm", "notes", cwd=self.repo)
        for wt in (self.wt1, self.wt2):
            sh("git", "merge", "-q", "main", cwd=wt)

    def risks(self):
        return [r for r in self.store.risks() if r["severity"] == "semantic"]

    def test_changed_parameters_against_a_new_call(self):
        self.edit(self.wt1, "def save_note(text):", "def save_note(text, author):", path="notes.py")
        self.edit(self.wt2, "x = 1\n", "from notes import save_note\n\nsave_note('hi')\n", path="other.py")
        predict.check(self.store)
        sem = self.risks()
        self.assertEqual(len(sem), 1, self.store.risks())
        self.assertIn("other.py calls save_note(), whose parameters changed", sem[0]["files"])

    def test_without_spelunk_a_signature_change_is_not_seen(self):
        self.store.set_cfg("spelunk", "off")
        self.edit(self.wt1, "def save_note(text):", "def save_note(text, author):", path="notes.py")
        self.edit(self.wt2, "x = 1\n", "from notes import save_note\n\nsave_note('hi')\n", path="other.py")
        predict.check(self.store)
        self.assertEqual(self.risks(), [])

    def test_an_optional_parameter_is_fine(self):
        self.edit(self.wt1, "def save_note(text):", "def save_note(text, author=None):", path="notes.py")
        self.edit(self.wt2, "x = 1\n", "from notes import save_note\n\nsave_note('hi')\n", path="other.py")
        predict.check(self.store)
        self.assertEqual(self.risks(), [])

    def test_removed_names_still_found(self):
        self.edit(self.wt1, "def save_note", "def store_note", path="notes.py")
        self.edit(self.wt2, "x = 1\n", "from notes import save_note\n\nsave_note('hi')\n", path="other.py")
        predict.check(self.store)
        self.assertIn("other.py uses save_note()", self.risks()[0]["files"])

    def test_arity(self):
        self.assertEqual(semantic.arity("def f(a, b=1, *, c):", "f"), None)  # keyword-only marker is variadic-ish
        self.assertEqual(semantic.arity("function f(a: string, b?: number) {", "f"), (1, 2))
        self.assertEqual(semantic.arity("func (s *Server) Handle(w http.ResponseWriter, r *http.Request) {",
                                        "Handle"), (2, 2))
        self.assertEqual(semantic.arity("fn save(&self, x: Vec<(u8, u8)>) -> bool {", "save"), (1, 1))
        self.assertIsNone(semantic.arity("def long(", "long"))


class ApprovalImpact(SpelunkCase):
    def setUp(self):
        super().setUp()
        self.store.set_cfg("review.required", "no")
        self.store.set_cfg("approve.required", "yes")
        self.store.set_cfg("approve.summary_command", "")
        self.inbox = Path(self.tmp.name) / "inbox.txt"
        self.store.set_cfg("approve.channels", "command")
        self.store.set_cfg("approve.command", f"printf '%s\\n----\\n' {{message}} >> {shlex.quote(str(self.inbox))}")

    def test_report_message_and_page_show_what_it_reaches(self):
        self.edit(self.wt1, "return 1", "return 10")
        self.commit(self.wt1)
        self.assertTrue(Server(self.repo, "task-one").call("ready_to_land", {"summary": "done"})["ok"])
        braid("land", cwd=self.repo, check=False)
        a = approve.get(self.store, 1)
        sp = a["report"]["spelunk"]
        self.assertEqual(sp["routes"][0]["path"], "/items")
        self.assertEqual(sp["tests"], ["test_m.py"])
        self.assertEqual(a["report"]["risk"], "high")  # a high-severity risk in the changed lines
        self.assertIn("Reaches 1 route (GET /items)", a["report"]["impact"])
        self.assertIn("No test reaches other.py", self.inbox.read_text())
        page = review_page.render(self.store, a)
        self.assertIn("What it reaches", page)
        self.assertIn("test_m.py", page)
        impact = [c for c in self.calls() if c["args"][0] == "impact"][0]
        self.assertEqual(impact["args"][1:], [a["base_oid"], "--head", a["proposal_oid"], "--json"])
        # the checkout Spelunk read was at exactly the commit being approved
        wt = Path(impact["cwd"])
        self.assertEqual(sh("git", "rev-parse", "HEAD", cwd=wt).stdout.strip(), a["proposal_oid"])


class StatusJson(SpelunkCase):
    def test_agents_json_lists_changed_files(self):
        self.edit(self.wt1, "return 1", "return 10")
        predict.check(self.store)
        data = json.loads(braid("agents", "--json", cwd=self.repo).stdout)
        self.assertEqual(data["schema"], 1)
        one = next(a for a in data["agents"] if a["name"] == "task-one")
        self.assertEqual(one["files"], ["m.py"])  # uncommitted work counts, from the snapshot
        self.assertEqual(one["base"], "main")
        self.assertIn("risks", data)
        status = json.loads(braid("status", "--json", cwd=self.repo).stdout)
        self.assertEqual(status["agents"], data["agents"])
