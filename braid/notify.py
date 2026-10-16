"""Approval channels: send the request out, and read the yes or no that comes back.

- email: SMTP to send, IMAP to read replies (a Gmail app password works for both).
- whatsapp: Twilio's WhatsApp API to send, and its message log to read replies, so nothing has to reach your
  computer from the internet.
- telegram: a bot with Approve / Send back buttons; button presses are read with getUpdates.
- command: any shell command, for ntfy, Slack webhooks and so on. Send only.
- cloudflare: your own Cloudflare Worker (cloudflare/ in this repo) hosts the review page, emails you, and records
  your click or reply; braid uploads each request and polls the worker for the answer.

Secrets come from the environment or from `braid approvals secret NAME VALUE` (.git/braid/secrets.json, mode 600).
"""
import base64
import email
import email.utils
import html
import imaplib
import json
import os
import re
import secrets as _secrets
import shlex
import smtplib
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage

SECRETS = ("BRAID_RELAY_KEY", "BRAID_SMTP_PASSWORD", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "BRAID_TELEGRAM_TOKEN")
YES = {"yes", "y", "approve", "approved", "ok", "lgtm", "ship", "ship it", "land", "👍", "✅"}
NO = {"no", "n", "reject", "rejected", "back", "send back", "nope", "👎", "❌"}


class ChannelError(RuntimeError):
    pass


# ------------------------------------------------------------------ secrets

def _secrets_file(store):
    return store.dir / "secrets.json"


def secret(store, name):
    if os.environ.get(name):
        return os.environ[name]
    try:
        return json.loads(_secrets_file(store).read_text()).get(name, "")
    except (OSError, ValueError):
        return ""


def set_secret(store, name, value):
    f = _secrets_file(store)
    try:
        data = json.loads(f.read_text())
    except (OSError, ValueError):
        data = {}
    if value:
        data[name] = value
    else:
        data.pop(name, None)
    f.touch(mode=0o600, exist_ok=True)
    os.chmod(f, 0o600)
    f.write_text(json.dumps(data, indent=1))


def channels(store):
    return [c.strip().lower() for c in store.cfg("approve.channels").split(",") if c.strip()]


# ------------------------------------------------------------------ message text

def review_url(store, a):
    from . import review_page
    if "cloudflare" in channels(store) and store.cfg("approve.cloudflare.url"):
        return f"{store.cfg('approve.cloudflare.url').rstrip('/')}/a/{remote_key(store, a)}?t={a['token']}"
    base = review_page.public_url(store)
    return f"{base}/a/{a['id']}?t={a['token']}" if base else ""


def short_text(store, a, limit=1500, fence="```", hint=True):
    """The phone-sized message: summary, impact, tests, and the diff itself when it is small."""
    r = a["report"]
    t = r["tests"]
    if not t["ran"]:
        tests = "no test command configured"
    elif t["passed"]:
        tests = "passed" + (f" ({t['counts']['passed']} tests)" if t.get("counts") else "")
    else:
        tests = "FAILED"
    n = len(r["files"])
    lines = [f"braid #{a['id']}: {r['agent']} wants to land on {r['base']}",
             r["title"], "",
             r["summary"], "",
             f"Impact ({r['risk']} risk): {r['impact']}",
             f"Tests: {tests}" + (f". Reviewed by {', '.join(r['reviewers'])}" if r["reviewers"] else ""),
             f"{n} file{'s' * (n != 1)}, +{r['added']} -{r['removed']}"]
    url = review_url(store, a)
    tail = []
    if url:
        tail.append(f"Review: {url}")
    tail.append(f"Reply YES {a['code']} to land, or NO {a['code']} and a reason to send it back.")
    body = "\n".join(lines)
    small = r["diff_lines"] <= int(store.cfg("approve.inline_diff_lines") or 0)
    room = limit - len(body) - len("\n".join(tail)) - 20
    if small and len(a["diff"]) <= room:
        body += f"\n\n{fence}\n{a['diff'].rstrip()}\n{fence}"
    elif not url and hint:
        body += "\n\nThe diff is too big for a message: run `braid approvals show " + str(a["id"]) + "` to see it."
    text = body + "\n\n" + "\n".join(tail)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def subject(a):
    return f"[braid {a['code']}] Approve {a['agent']}: {a['report']['title']}"


# ------------------------------------------------------------------ send

def send_request(store, a):
    """Send a pending approval on every configured channel. Returns the channels that worked."""
    sent = []
    for ch in sorted(channels(store), key=lambda c: c != "cloudflare"):  # upload the page before linking to it
        try:
            SENDERS[ch](store, a)
            sent.append(ch)
        except KeyError:
            store.event("notify", f"unknown approval channel {ch!r}", a["agent"])
        except Exception as e:  # a broken channel must not stop the others or the landing
            store.event("notify", f"{ch} failed for approval #{a['id']}: {e}", a["agent"])
    if sent:
        store.event("notify", f"approval #{a['id']} sent by {', '.join(sent)}", a["agent"])
    return sent


def send_text(store, text, only=("whatsapp", "telegram", "command")):
    """A short follow-up (landed, failed) on the chat-style channels."""
    for ch in channels(store):
        if ch in only:
            try:
                TEXT_SENDERS[ch](store, text)
            except Exception as e:
                store.event("notify", f"{ch} failed: {e}")


def _http(url, data=None, auth=None, timeout=20, json_body=None, bearer=None, method=None):
    headers = {"User-Agent": "braid"}
    if auth:
        headers["Authorization"] = "Basic " + base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if json_body is not None:
        body = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raise ChannelError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}") from None


# ---- email

def _smtp_conf(store):
    host, _, port = store.cfg("approve.email.smtp").partition(":")
    user = store.cfg("approve.email.user")
    to = store.cfg("approve.email.to")
    if not (host and to):
        raise ChannelError("set approve.email.to and approve.email.smtp")
    return host, int(port or 587), user, secret(store, "BRAID_SMTP_PASSWORD"), to


def send_email(store, a):
    from . import review_page
    host, port, user, password, to = _smtp_conf(store)
    msg = EmailMessage()
    msg["Subject"] = subject(a)
    msg["From"] = store.cfg("approve.email.from") or user or to
    msg["To"] = to
    msg["Message-ID"] = email.utils.make_msgid("braid")
    msg.set_content(short_text(store, a, limit=100000))
    msg.add_alternative(review_page.render(store, a, mode="email", url=review_url(store, a)), subtype="html")
    if not review_url(store, a):  # no page to link to: attach it so the full review opens in a browser
        msg.add_attachment(review_page.render(store, a, mode="static").encode(), maintype="text",
                           subtype="html", filename=f"braid-review-{a['id']}.html")
    _smtp_send(host, port, user, password, msg)


def _smtp_send(host, port, user, password, msg):
    ctx = ssl.create_default_context()
    if port == 465:
        s = smtplib.SMTP_SSL(host, port, context=ctx, timeout=30)
    else:
        s = smtplib.SMTP(host, port, timeout=30)
        s.starttls(context=ctx)
    with s:
        if user:
            s.login(user, password)
        s.send_message(msg)


# ---- whatsapp (Twilio)

def _twilio(store):
    sid, token = secret(store, "TWILIO_ACCOUNT_SID"), secret(store, "TWILIO_AUTH_TOKEN")
    if not (sid and token):
        raise ChannelError("add TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN (braid approvals secret ...)")
    to, frm = store.cfg("approve.whatsapp.to"), store.cfg("approve.whatsapp.from")
    if not (to and frm):
        raise ChannelError("set approve.whatsapp.to (your number) and approve.whatsapp.from")
    return sid, token, _wa(to), _wa(frm)


def _wa(number):
    number = re.sub(r"[^\d+]", "", number.replace("whatsapp:", ""))
    return "whatsapp:" + (number if number.startswith("+") else "+" + number)


def _twilio_send(store, data):
    sid, token, to, frm = _twilio(store)
    return _http(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                 {"From": frm, "To": to, **data}, auth=(sid, token))


def send_whatsapp(store, a):
    content = store.cfg("approve.whatsapp.content_sid")
    if content:  # business-initiated messages outside the 24h window need an approved template
        r = a["report"]
        _twilio_send(store, {"ContentSid": content, "ContentVariables": json.dumps({
            "1": f"#{a['id']} {r['agent']}: {r['title']}"[:200], "2": r["summary"][:600],
            "3": review_url(store, a) or "(run braid approvals show)", "4": a["code"]})})
    else:
        _twilio_send(store, {"Body": short_text(store, a, limit=1550)})


def text_whatsapp(store, text):
    _twilio_send(store, {"Body": text[:1550]})


# ---- telegram

def _telegram(store, method, **params):
    token = secret(store, "BRAID_TELEGRAM_TOKEN")
    if not token:
        raise ChannelError("add BRAID_TELEGRAM_TOKEN (braid approvals secret BRAID_TELEGRAM_TOKEN)")
    data = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in params.items()}
    r = _http(f"https://api.telegram.org/bot{token}/{method}", data, timeout=30)
    if not r.get("ok"):
        raise ChannelError(str(r)[:300])
    return r["result"]


def send_telegram(store, a):
    chat = store.cfg("approve.telegram.chat_id")
    if not chat:
        raise ChannelError("set approve.telegram.chat_id (message your bot, then run braid approvals telegram-id)")
    text = html.escape(short_text(store, a, limit=3800, fence="§§§"))
    text = re.sub(r"§§§\n(.*?)\n§§§", lambda m: f"<pre>{m.group(1)}</pre>", text, flags=re.S)
    buttons = [[{"text": "✅ Land it", "callback_data": f"braid:yes:{a['code']}"},
                {"text": "↩️ Send back", "callback_data": f"braid:no:{a['code']}"}]]
    url = review_url(store, a)
    if url.startswith("https://"):
        buttons.append([{"text": "Open review", "url": url}])
    _telegram(store, "sendMessage", chat_id=chat, text=text, parse_mode="HTML",
              reply_markup={"inline_keyboard": buttons}, disable_web_page_preview="true")


def text_telegram(store, text):
    _telegram(store, "sendMessage", chat_id=store.cfg("approve.telegram.chat_id"), text=text[:4000])


# ---- cloudflare (your own worker, see cloudflare/)

def _relay(store):
    url, key = store.cfg("approve.cloudflare.url").rstrip("/"), secret(store, "BRAID_RELAY_KEY")
    if not (url and key):
        raise ChannelError("set approve.cloudflare.url and braid approvals secret BRAID_RELAY_KEY")
    return url, key


def remote_key(store, a):
    """The approval's name on the worker: unique per repo, so one worker can serve several repos."""
    rid = store.get_meta("approve.repo_id")
    if not rid:
        rid = _secrets.token_hex(4)
        store.set_meta("approve.repo_id", rid)
    return f"{rid}-{a['id']}"


def send_cloudflare(store, a):
    from . import review_page
    url, key = _relay(store)
    link = review_url(store, a)
    r = _http(f"{url}/api/approvals", bearer=key, timeout=60, json_body={
        "key": remote_key(store, a), "code": a["code"], "token": a["token"], "diff": a["diff"][:1_000_000],
        "html": review_page.render(store, a, mode="web", page_id=remote_key(store, a)),
        "email": {"subject": subject(a), "text": short_text(store, a, limit=100000),
                  "html": review_page.render(store, a, mode="email", url=link)}})
    if not str(r.get("email", "")).startswith(("sent", "not requested")):
        store.event("notify", f"worker email for approval #{a['id']}: {r.get('email')}", a["agent"])


def update_remote(store, a):
    """Tell the worker how it ended, so the review page shows it."""
    from . import review_page
    if "cloudflare" not in channels(store):
        return
    try:
        url, key = _relay(store)
        _http(f"{url}/api/approvals/{remote_key(store, a)}", bearer=key, method="PUT", timeout=60,
              json_body={"status": a["status"],
                                    "html": review_page.render(store, a, mode="web", page_id=remote_key(store, a))})
    except Exception as e:
        store.event("notify", f"updating the review page for #{a['id']} failed: {e}", a["agent"])


def poll_cloudflare(store):
    from . import approve
    url, key = _relay(store)
    out = []
    for a in approve.all_approvals(store, "pending"):
        try:
            r = _http(f"{url}/api/approvals/{remote_key(store, a)}", bearer=key)
        except ChannelError as e:
            if "HTTP 404" in str(e):
                continue  # never uploaded (worker was down); braid approve still works
            raise
        if r.get("status") in ("approved", "rejected"):
            a, message = approve.decide(store, a["id"], r["status"] == "approved", r.get("decided_by") or "web",
                                        r.get("comment") or "")
            send_text(store, f"braid #{a['id']}: {message}")
            out.append(message)
    return out


# ---- command

def send_command(store, a):
    _command(store, short_text(store, a, limit=4000), url=review_url(store, a), code=a["code"],
             title=a["report"]["title"])


def text_command(store, text):
    _command(store, text, url="", code="", title=text.splitlines()[0])


def _command(store, message, **extra):
    template = store.cfg("approve.command")
    if not template:
        raise ChannelError("set approve.command")
    q = {k: shlex.quote(v) for k, v in extra.items()}
    proc = subprocess.run(template.format(message=shlex.quote(message), **q), shell=True, cwd=store.repo,
                          capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    if proc.returncode != 0:
        raise ChannelError(f"exit {proc.returncode}: {(proc.stderr or proc.stdout)[-300:]}")


SENDERS = {"cloudflare": send_cloudflare, "email": send_email, "whatsapp": send_whatsapp, "telegram": send_telegram, "command": send_command}
TEXT_SENDERS = {"whatsapp": text_whatsapp, "telegram": text_telegram, "command": text_command}


# ------------------------------------------------------------------ replies

def parse_reply(text):
    """'YES 7K2Q', 'no 7k2q tests are too slow', 'lgtm' -> (verdict, code or None, comment) or None."""
    first = ""
    for line in (text or "").splitlines():
        line = line.strip()
        if line and not line.startswith(">"):
            first = line
            break
    m = re.match(r"^([^\W\d_]+(?: it| back)?|👍|👎|✅|❌)[\s,.:!-]*(?:#?([A-Za-z2-9]{4})\b)?[\s,.:!-]*(.*)$", first,
                 re.S)
    if not m:
        return None
    word = m.group(1).lower()
    if word in YES:
        verdict = True
    elif word in NO:
        verdict = False
    else:
        return None
    return verdict, m.group(2), m.group(3).strip()


def _apply_reply(store, parsed, by, code_hint=None):
    """Turn a parsed reply into a decision. A bare yes applies when exactly one approval is pending."""
    from . import approve
    verdict, code, comment = parsed
    if code and not approve.get(store, code):  # "no tests are missing": that was a word, not a code
        comment, code = f"{code} {comment}".strip(), None
    code = (code or code_hint or "").upper()
    pending = approve.all_approvals(store, "pending")
    if code:
        target = next((a for a in pending if a["code"] == code), None)
    else:
        target = pending[0] if len(pending) == 1 else None
    if not target:
        return None
    a, message = approve.decide(store, target["id"], verdict, by, comment)
    send_text(store, f"braid #{a['id']}: {message}")
    return message


def poll(store, force=False):
    """Check every reply channel once (rate limited by approve.poll_interval). Returns decisions made."""
    from . import approve
    if not approve.required(store) or not approve.all_approvals(store, "pending"):
        return []
    now = time.time()
    if not force and now - float(store.get_meta("approve.polled", "0")) < float(store.cfg("approve.poll_interval")):
        return []
    store.set_meta("approve.polled", now)
    done = []
    for ch in channels(store):
        fn = POLLERS.get(ch)
        if not fn:
            continue
        try:
            done += fn(store)
        except Exception as e:
            key = f"approve.pollerr.{ch}"
            if store.get_meta(key) != str(e):  # log each distinct error once
                store.set_meta(key, str(e))
                store.event("notify", f"reading {ch} replies failed: {e}")
    return done


def _seen(store, channel, ident):
    key = f"approve.seen.{channel}"
    seen = json.loads(store.get_meta(key, "[]"))
    if ident in seen:
        return True
    store.set_meta(key, json.dumps((seen + [ident])[-500:]))
    return False


def _oldest_pending(store):
    from . import approve
    return min(a["created_at"] for a in approve.all_approvals(store, "pending"))


def poll_email(store):
    host, _, user, password, to = _smtp_conf(store)
    imap = store.cfg("approve.email.imap") or re.sub(r"^smtp", "imap", host) + ":993"
    ihost, _, iport = imap.partition(":")
    since = time.strftime("%d-%b-%Y", time.gmtime(_oldest_pending(store) - 86400))
    out = []
    with imaplib.IMAP4_SSL(ihost, int(iport or 993), ssl_context=ssl.create_default_context()) as m:
        m.login(user or to, password)
        m.select("INBOX", readonly=True)
        _, data = m.search(None, "SINCE", since, "FROM", f'"{to}"', "SUBJECT", '"[braid "')
        for num in data[0].split():
            _, parts = m.fetch(num, "(BODY.PEEK[])")
            msg = email.message_from_bytes(parts[0][1])
            ident = msg.get("Message-ID") or num.decode()
            sender = email.utils.parseaddr(msg.get("From", ""))[1].lower()
            if sender != to.lower() or _seen(store, "email", ident):
                continue
            hint = re.search(r"\[braid ([A-Z2-9]{4})\]", msg.get("Subject", ""))
            parsed = parse_reply(_plain_body(msg))
            if parsed and hint:  # email replies must carry the code (it's in the subject)
                r = _apply_reply(store, parsed, "email", hint.group(1))
                if r:
                    out.append(r)
    return out


def _plain_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
        return ""
    return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "replace")


def poll_whatsapp(store):
    sid, token, me, bot = _twilio(store)
    after = _oldest_pending(store)
    q = urllib.parse.urlencode({"From": me, "To": bot, "PageSize": 20,
                                "DateSent>": time.strftime("%Y-%m-%d", time.gmtime(after - 86400))})
    data = _http(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json?{q}", auth=(sid, token))
    out = []
    for msg in reversed(data.get("messages", [])):  # oldest first
        sent = email.utils.parsedate_to_datetime(msg["date_sent"]).timestamp() if msg.get("date_sent") else 0
        if msg.get("from") != me or sent < after - 5 or _seen(store, "whatsapp", msg["sid"]):
            continue
        parsed = parse_reply(msg.get("body", ""))
        if parsed:
            r = _apply_reply(store, parsed, "WhatsApp")
            if r:
                out.append(r)
    return out


def poll_telegram(store):
    chat = str(store.cfg("approve.telegram.chat_id"))
    offset = int(store.get_meta("approve.telegram.offset", "0"))
    updates = _telegram(store, "getUpdates", offset=offset, timeout=0,
                        allowed_updates=["message", "callback_query"])
    out = []
    for u in updates:
        store.set_meta("approve.telegram.offset", u["update_id"] + 1)
        if "callback_query" in u:
            cq = u["callback_query"]
            if str(cq["from"]["id"]) != chat or not str(cq.get("data", "")).startswith("braid:"):
                continue
            _, verdict, code = cq["data"].split(":", 2)
            r = _apply_reply(store, (verdict == "yes", code, ""), "Telegram")
            _telegram(store, "answerCallbackQuery", callback_query_id=cq["id"], text=(r or "nothing pending")[:190])
            if r:
                out.append(r)
        elif "message" in u:
            msg = u["message"]
            if str(msg.get("chat", {}).get("id")) != chat:
                continue
            parsed = parse_reply(msg.get("text", ""))
            if parsed:
                r = _apply_reply(store, parsed, "Telegram")
                if r:
                    out.append(r)
    return out


def telegram_chat_ids(store):
    """Chats that messaged the bot recently, to find your chat_id."""
    return {str(u["message"]["chat"]["id"]): u["message"]["chat"].get("username") or
            u["message"]["chat"].get("first_name", "")
            for u in _telegram(store, "getUpdates") if "message" in u}


POLLERS = {"cloudflare": poll_cloudflare, "email": poll_email, "whatsapp": poll_whatsapp, "telegram": poll_telegram}
