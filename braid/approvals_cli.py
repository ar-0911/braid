"""`braid approvals`, `braid approve` and `braid reject`."""
import getpass
import sys
import time

from . import approve, notify, review_page


def _store():
    from .cli import open_store
    store = open_store()
    approve.ensure(store)
    return store


def _line(a):
    r = a["report"]
    tests = "tests ok" if r["tests"]["passed"] else "tests FAILED"
    return (f"#{a['id']:<4} {a['code']}  {a['status']:<9} {a['agent']:<16} {r['title'][:50]:<50} "
            f"+{r['added']}/-{r['removed']}  {tests}")


def cmd_approvals(args):
    if args.action == "secret" and args.global_:
        return _global_secret(args)
    store = _store()
    action = args.action or "list"
    if action == "list":
        rows = approve.all_approvals(store, None if args.all else "pending")
        if not rows:
            print("nothing waiting for approval" + ("" if approve.required(store) else
                  " (approvals are off: braid settings approve.required yes)"))
        for a in rows[-30:]:
            print(_line(a))
    elif action == "show":
        a = approve.get(store, args.arg or "")
        if not a:
            sys.exit(f"no approval {args.arg}")
        print(notify.short_text(store, a, limit=10 ** 9, hint=False))
        if a["report"]["diff_lines"] > int(store.cfg("approve.inline_diff_lines") or 0):
            print("\n" + a["diff"])
        url = notify.review_url(store, a)
        if url:
            print(f"\nreview page: {url}")
    elif action == "page":
        a = approve.get(store, args.arg or "")
        if not a:
            sys.exit(f"no approval {args.arg}")
        out = store.dir / f"review-{a['id']}.html"
        out.write_text(review_page.render(store, a, mode="static"))
        print(out)
    elif action == "serve":
        serve(store, args)
    elif action == "secret":
        if not args.arg or args.arg not in notify.SECRETS:
            sys.exit(f"secret name is one of: {', '.join(notify.SECRETS)}")
        value = args.value if args.value is not None else getpass.getpass(f"{args.arg}: ")
        f = notify.set_secret(store, args.arg, value.strip(), global_=args.global_)
        print(f"saved {args.arg} in {f} (only you can read it)"
              + ("; every repo uses it" if args.global_ else ""))
    elif action == "test":
        test_channels(store)
    elif action == "telegram-id":
        ids = notify.telegram_chat_ids(store)
        if not ids:
            print("no messages yet: send any message to your bot in Telegram, then run this again")
        for cid, who in ids.items():
            print(f"{cid}  {who}    ->  braid settings approve.telegram.chat_id {cid}")


def _global_secret(args):
    if not args.arg or args.arg not in notify.SECRETS:
        sys.exit(f"secret name is one of: {', '.join(notify.SECRETS)}")
    value = args.value if args.value is not None else getpass.getpass(f"{args.arg}: ")
    f = notify.set_secret(None, args.arg, value.strip(), global_=True)
    print(f"saved {args.arg} in {f} (only you can read it); every repo uses it")


def serve(store, args):
    srv = review_page.ReviewServer(store, port=args.port).start()
    print(f"review pages at {srv.url() or 'http://localhost:' + str(srv.port)}"
          + ("" if store.cfg("approve.public_url") or store.get_meta("approve.live_url") else
             "  (local only: set approve.public_url or approve.tunnel cloudflared to open them from your phone)"),
          flush=True)
    try:
        while True:
            for msg in notify.poll(store):
                print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()


def test_channels(store):
    chans = notify.channels(store)
    if not chans:
        sys.exit("no channels: braid settings approve.channels email,whatsapp,telegram")
    for ch in chans:
        try:
            if ch == "email":
                from email.message import EmailMessage
                host, port, user, password, to = notify._smtp_conf(store)
                msg = EmailMessage()
                msg["Subject"], msg["To"] = "braid: test message", to
                msg["From"] = store.cfg("approve.email.from") or user or to
                msg.set_content("braid can reach you here. Approval requests will look like a summary, "
                                "the diff or a review link, and a YES/NO to reply with.")
                notify._smtp_send(host, port, user, password, msg)
            elif ch == "cloudflare":
                url, key = notify._relay(store)
                try:
                    notify._http(f"{url}/api/approvals/braid-test", bearer=key)
                except notify.ChannelError as e:
                    if "HTTP 404" not in str(e):  # 404 = signed in fine, no such approval
                        raise
            else:
                notify.TEXT_SENDERS[ch](store, "braid can reach you here. Approval requests will arrive like this; "
                                               "reply YES to land, NO and a reason to send work back.")
            print(f"  ok  {ch}")
        except Exception as e:
            print(f"  !!  {ch}: {e}")
    if "cloudflare" in chans:
        print(f"review pages: {store.cfg('approve.cloudflare.url')}/a/...")
        return
    print("review page: " + (review_page.public_url(store) or "not reachable from your phone yet "
                             "(set approve.public_url or approve.tunnel cloudflared, and run the watcher)"))


def cmd_approve(args, verdict=True):
    store = _store()
    if not args.ref:
        pending = approve.all_approvals(store, "pending")
        if len(pending) != 1:
            for a in pending:
                print(_line(a))
            sys.exit("name one: braid approve <id or code>" if pending else "nothing waiting for approval")
        args.ref = str(pending[0]["id"])
    a, message = approve.decide(store, args.ref, verdict, "cli", getattr(args, "message", "") or "")
    print(message)
    if a is None or a["status"] == "failed":
        sys.exit(1)


def cmd_reject(args):
    cmd_approve(args, verdict=False)


def register(add):
    s = add("approvals", cmd_approvals, "changes waiting for your yes; serve the review page; set up channels")
    s.add_argument("action", nargs="?", choices=["list", "show", "page", "serve", "test", "secret", "telegram-id"])
    s.add_argument("arg", nargs="?", help="approval id or code (show, page) or secret name (secret)")
    s.add_argument("value", nargs="?", help="secret value (prompted for if left out)")
    s.add_argument("--all", action="store_true", help="include decided ones")
    s.add_argument("--port", type=int)
    s.add_argument("--global", dest="global_", action="store_true",
                   help="secret: save it for every repo (~/.config/braid)")

    s = add("approve", cmd_approve, "say yes to a change waiting for approval; it lands right away")
    s.add_argument("ref", nargs="?", help="approval id or reply code (default: the only pending one)")

    s = add("reject", cmd_reject, "send a change back to its agent instead of landing it")
    s.add_argument("ref", nargs="?")
    s.add_argument("-m", "--message", help="why, for the agent")
