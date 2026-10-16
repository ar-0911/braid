import json
import shlex
import sys
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from helpers import RepoCase, braid, sh
from braid import approve, notify, review_page
from braid.mcp_server import Server

FAKES = Path(__file__).resolve().parent / "fakes"


class ApprovalCase(RepoCase):
    def setUp(self):
        super().setUp()
        self.store.set_cfg("review.required", "no")
        self.store.set_cfg("approve.required", "yes")
        self.store.set_cfg("approve.summary_command", "")
        self.inbox = Path(self.tmp.name) / "inbox.txt"
        self.store.set_cfg("approve.channels", "command")
        self.store.set_cfg("approve.command", f"printf '%s\\n----\\n' {{message}} >> {shlex.quote(str(self.inbox))}")
        self.one, self.two = Server(self.repo, "task-one"), Server(self.repo, "task-two")

    def ready(self, srv, wt, old, new, path="m.py"):
        self.edit(wt, old, new, path)
        self.commit(wt, f"{srv.agent}: {new.strip()[:20]}")
        self.assertTrue(srv.call("ready_to_land", {"summary": "done"})["ok"])

    def main(self):
        return sh("git", "rev-parse", "main", cwd=self.repo).stdout.strip()


class Approvals(ApprovalCase):
    def test_landing_waits_for_a_yes_then_lands_exactly_what_was_shown(self):
        before = self.main()
        self.ready(self.one, self.wt1, "return 1", "return 10")
        r = braid("land", cwd=self.repo, check=False)
        self.assertIn("waiting for your approval (#1", r.stdout)
        self.assertEqual(self.main(), before)
        a = approve.get(self.store, 1)
        self.assertEqual(a["status"], "pending")
        msg = self.inbox.read_text()
        self.assertIn("task-one wants to land on main", msg)
        self.assertIn("+    return 10", msg)  # small diff goes in the message
        self.assertIn(f"YES {a['code']}", msg)
        self.assertIn("a", [e["name"] for e in a["report"]["entities"]])
        # the watcher keeps waiting without re-running anything
        self.assertIn("waiting for your approval", braid("land", cwd=self.repo, check=False).stdout)
        self.assertEqual(len(approve.all_approvals(self.store)), 1)
        r = braid("approve", a["code"], cwd=self.repo)
        self.assertIn("task-one landed on main", r.stdout)
        self.assertEqual(self.main(), a["proposal_oid"])
        self.assertEqual(approve.get(self.store, 1)["status"], "landed")
        self.assertIn("return 10", (self.repo / "m.py").read_text())

    def test_send_back_blocks_the_agent_with_the_reason(self):
        self.ready(self.one, self.wt1, "return 1", "return 10")
        braid("land", cwd=self.repo, check=False)
        braid("reject", "1", "-m", "keep it at one", cwd=self.repo)
        self.assertEqual(self.store.agent("task-one")["status"], "blocked")
        self.assertIn("keep it at one", self.store.notes(for_agent="task-one")[-1]["text"])
        self.assertEqual(approve.get(self.store, 1)["status"], "rejected")
        # new commits from the agent ask again
        self.edit(self.wt1, "return 10", "return 1  # kept")
        self.commit(self.wt1)
        self.assertTrue(self.one.call("ready_to_land", {"summary": "fixed"})["ok"])
        self.assertIn("#2", braid("land", cwd=self.repo, check=False).stdout)

    def test_yes_still_counts_after_base_moves_when_merge_is_clean(self):
        self.ready(self.one, self.wt1, "return 1", "return 10")
        self.ready(self.two, self.wt2, "x = 1", "x = 2", path="other.py")
        braid("land", cwd=self.repo, check=False)  # both pending
        a1, a2 = approve.all_approvals(self.store, "pending")
        braid("approve", str(a2["id"]), cwd=self.repo)
        r = braid("approve", str(a1["id"]), cwd=self.repo)  # base moved since #1 was proposed
        self.assertIn("task-one landed", r.stdout)
        self.assertEqual(len(approve.all_approvals(self.store)), 2)  # no third request
        self.assertIn("return 10", self.show("main"))
        self.assertIn("x = 2", self.show("main", "other.py"))

    def test_yes_waits_for_a_dirty_main_checkout_without_asking_again(self):
        self.ready(self.one, self.wt1, "return 1", "return 10")
        braid("land", cwd=self.repo, check=False)
        (self.repo / "other.py").write_text("x = 'local edit'\n")  # unsaved work where main is checked out
        r = braid("approve", "1", cwd=self.repo, check=False)
        self.assertIn("uncommitted changes", r.stdout)
        self.assertEqual(approve.get(self.store, 1)["status"], "approved")
        self.assertIn("waiting", braid("land", cwd=self.repo, check=False).stdout)
        self.assertEqual(len(approve.all_approvals(self.store)), 1)  # no second email
        sh("git", "checkout", "other.py", cwd=self.repo)
        self.assertIn("landed  task-one", braid("land", cwd=self.repo).stdout)
        self.assertEqual(approve.get(self.store, 1)["status"], "landed")

    def test_big_diff_links_to_review_page_instead(self):
        self.store.set_cfg("approve.inline_diff_lines", "2")
        self.store.set_cfg("approve.public_url", "https://braid.example/")
        self.ready(self.one, self.wt1, "return 1", "return 10")
        braid("land", cwd=self.repo, check=False)
        a = approve.get(self.store, 1)
        msg = self.inbox.read_text()
        self.assertNotIn("+    return 10", msg)
        self.assertIn(f"https://braid.example/a/1?t={a['token']}", msg)

    def test_model_summary_is_used_when_configured(self):
        self.store.set_cfg("approve.summary_command",
                           f"{shlex.quote(sys.executable)} {shlex.quote(str(FAKES / 'summarizer.py'))} {{prompt}}")
        self.ready(self.one, self.wt1, "return 1", "return 10")
        braid("land", cwd=self.repo, check=False)
        r = approve.get(self.store, 1)["report"]
        self.assertEqual((r["title"], r["risk"], r["summary_by"]), ("Make a() return ten", "medium", "model"))
        self.assertEqual(r["files"][0]["note"], "changes the return value of a()")
        self.assertIn("Make a() return ten", self.inbox.read_text())

    def test_bare_yes_reply_lands_the_only_pending_change(self):
        self.ready(self.one, self.wt1, "return 1", "return 10")
        braid("land", cwd=self.repo, check=False)
        self.assertIsNone(notify._apply_reply(self.store, notify.parse_reply("hmm"), "test")
                          if notify.parse_reply("hmm") else None)
        msg = notify._apply_reply(self.store, notify.parse_reply("Yes looks good"), "WhatsApp")
        self.assertIn("landed", msg)
        self.assertEqual(approve.get(self.store, 1)["decided_by"], "WhatsApp")

    def test_review_page_needs_the_token_and_its_button_lands(self):
        self.ready(self.one, self.wt1, "return 1", "return 10")
        braid("land", cwd=self.repo, check=False)
        a = approve.get(self.store, 1)
        srv = review_page.ReviewServer(self.store, port=0, tunnel="").start()
        try:
            base = f"http://127.0.0.1:{srv.port}"
            self.assertEqual(review_page.public_url(self.store), f"http://localhost:{srv.port}")
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(f"{base}/a/1?t=wrong")
            page = urllib.request.urlopen(f"{base}/a/1?t={a['token']}").read().decode()
            self.assertIn("Land it", page)
            self.assertIn("return 10", page)
            data = urllib.parse.urlencode({"t": a["token"], "action": "approve"}).encode()
            urllib.request.urlopen(urllib.request.Request(f"{base}/a/1/decide", data=data))
            deadline = time.time() + 20
            while approve.get(self.store, 1)["status"] != "landed" and time.time() < deadline:
                time.sleep(0.2)
            self.assertEqual(approve.get(self.store, 1)["status"], "landed")
            self.assertEqual(self.main(), a["proposal_oid"])
        finally:
            srv.close()


class Replies(unittest.TestCase):
    def test_parse(self):
        p = notify.parse_reply
        self.assertEqual(p("YES 7K2Q"), (True, "7K2Q", ""))
        self.assertEqual(p("no 7k2q: tests are too slow"), (False, "7k2q", "tests are too slow"))
        self.assertEqual(p("lgtm"), (True, None, ""))
        self.assertEqual(p("Ship it!"), (True, None, ""))
        self.assertEqual(p("👍"), (True, None, ""))
        self.assertEqual(p("\n> quoted\nyes\n\nOn Fri ... wrote:"), (True, None, ""))
        self.assertIsNone(p("what does this change?"))


if __name__ == "__main__":
    unittest.main()


class Channels(ApprovalCase):
    """WhatsApp (Twilio) and Telegram with their HTTP APIs faked out."""

    def setUp(self):
        super().setUp()
        self.calls, self.replies = [], {}
        self._http = notify._http

        def fake(url, data=None, auth=None, timeout=20, **kw):
            self.calls.append((url, data if data is not None else kw.get("json_body"), auth or kw.get("bearer")))
            for key, value in self.replies.items():
                if key in url:
                    return value() if callable(value) else value
            return {"ok": True, "result": []}
        notify._http = fake
        notify.set_secret(self.store, "TWILIO_ACCOUNT_SID", "AC1")
        notify.set_secret(self.store, "TWILIO_AUTH_TOKEN", "tok")
        notify.set_secret(self.store, "BRAID_TELEGRAM_TOKEN", "123:abc")
        self.store.set_cfg("approve.whatsapp.to", "+44 7700 900123")
        self.store.set_cfg("approve.telegram.chat_id", "42")

    def tearDown(self):
        notify._http = self._http
        super().tearDown()

    def pending(self):
        self.ready(self.one, self.wt1, "return 1", "return 10")
        braid("land", cwd=self.repo, check=False)  # separate process: real _http, no channels hit there
        self.store.set_cfg("approve.channels", "whatsapp,telegram")
        a = approve.get(self.store, 1)
        self.assertEqual(notify.send_request(self.store, a), ["whatsapp", "telegram"])
        return a

    def test_whatsapp_request_and_reply(self):
        a = self.pending()
        url, data, auth = self.calls[0]
        self.assertTrue(url.endswith("/Accounts/AC1/Messages.json"))
        self.assertEqual((data["To"], data["From"], auth), ("whatsapp:+447700900123", "whatsapp:+14155238886",
                                                           ("AC1", "tok")))
        self.assertIn("+    return 10", data["Body"])
        now = time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime(time.time() + 2))
        self.replies["Messages.json?"] = {"messages": [
            {"sid": "SM2", "from": "whatsapp:+447700900123", "body": f"yes {a['code']}", "date_sent": now},
            {"sid": "SM1", "from": "whatsapp:+15550000000", "body": "no", "date_sent": now}]}
        self.store.set_cfg("approve.channels", "whatsapp")
        done = notify.poll(self.store, force=True)
        self.assertEqual(len(done), 1, done)
        self.assertEqual(approve.get(self.store, 1)["status"], "landed")
        self.assertIn("landed", self.calls[-1][1]["Body"])  # confirmation sent back

    def test_telegram_buttons(self):
        a = self.pending()
        url, data, _ = self.calls[1]
        self.assertIn("/bot123:abc/sendMessage", url)
        self.assertIn(f"braid:yes:{a['code']}", data["reply_markup"])
        self.assertIn("<pre>", data["text"])
        self.replies["getUpdates"] = {"ok": True, "result": [
            {"update_id": 7, "callback_query": {"id": "q1", "from": {"id": 999}, "data": f"braid:yes:{a['code']}"}},
            {"update_id": 8, "callback_query": {"id": "q2", "from": {"id": 42}, "data": f"braid:no:{a['code']}"}}]}
        self.store.set_cfg("approve.channels", "telegram")
        notify.poll(self.store, force=True)
        a = approve.get(self.store, 1)
        self.assertEqual((a["status"], a["decided_by"]), ("rejected", "Telegram"))  # stranger's yes ignored
        self.assertEqual(self.store.get_meta("approve.telegram.offset"), "9")

    def test_cloudflare_worker_hosts_page_and_carries_the_yes(self):
        self.ready(self.one, self.wt1, "return 1", "return 10")
        braid("land", cwd=self.repo, check=False)
        self.store.set_cfg("approve.channels", "cloudflare,telegram")
        self.store.set_cfg("approve.cloudflare.url", "https://braid.example.workers.dev/")
        notify.set_secret(self.store, "BRAID_RELAY_KEY", "k")
        a = approve.get(self.store, 1)
        self.assertEqual(notify.send_request(self.store, a), ["cloudflare", "telegram"])
        url, body, key = self.calls[0]
        rk = notify.remote_key(self.store, a)
        self.assertEqual((url, key, body["key"]), ("https://braid.example.workers.dev/api/approvals", "k", rk))
        self.assertIn(f"/a/{rk}/decide", body["html"])
        link = f"https://braid.example.workers.dev/a/{rk}?t={a['token']}"
        self.assertIn(link, body["email"]["text"])
        self.assertIn(link, self.calls[1][1]["reply_markup"])  # other channels link to the worker's page
        self.store.set_cfg("approve.channels", "cloudflare")
        self.replies[f"/api/approvals/{rk}"] = {"status": "approved", "decided_by": "email", "comment": ""}
        self.assertEqual(len(notify.poll(self.store, force=True)), 1)
        self.assertEqual(approve.get(self.store, 1)["status"], "landed")
        put = [c for c in self.calls if c[1] and c[1].get("status") == "landed"]
        self.assertEqual(len(put), 1)  # the page was told how it ended


class GlobalSettings(RepoCase):
    agents = ()

    def tearDown(self):
        from braid.store import global_dir
        for name in ("settings.json", "secrets.json"):
            (global_dir() / name).unlink(missing_ok=True)
        super().tearDown()

    def test_global_settings_and_secrets_apply_to_every_repo(self):
        elsewhere = Path(self.tmp.name)  # not a repo: --global works anywhere
        braid("settings", "--global", "approve.required", "yes", cwd=elsewhere)
        braid("settings", "--global", "approve.channels", "cloudflare", cwd=elsewhere)
        braid("approvals", "secret", "--global", "BRAID_RELAY_KEY", "k1", cwd=elsewhere)
        self.assertTrue(approve.required(self.store))
        self.assertEqual(notify.secret(self.store, "BRAID_RELAY_KEY"), "k1")
        self.assertIn("approve.channels = cloudflare", braid("settings", cwd=self.repo).stdout)
        braid("settings", "approve.channels", "email", cwd=self.repo)  # a repo can still override
        self.assertEqual(self.store.cfg("approve.channels"), "email")
        braid("settings", "--global", "approve.required", "", cwd=elsewhere)
        self.assertFalse(approve.required(self.store))
