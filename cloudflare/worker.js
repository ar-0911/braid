// braid approvals on Cloudflare: hosts review pages, emails you, and records your yes or no.
//
// braid (on your computer) uploads each approval request here and polls for the decision, so nothing on your
// computer is reachable from the internet. Bindings (see wrangler.toml): DB (D1), EMAIL (send_email, optional),
// secrets BRAID_KEY (shared with braid) and vars OWNER_EMAIL / FROM_EMAIL for email.
import { EmailMessage } from "cloudflare:email";

const SCHEMA = `CREATE TABLE IF NOT EXISTS approvals (
  key TEXT PRIMARY KEY, code TEXT NOT NULL, token TEXT NOT NULL, html TEXT NOT NULL, diff TEXT NOT NULL,
  status TEXT NOT NULL, comment TEXT NOT NULL DEFAULT '', decided_by TEXT NOT NULL DEFAULT '',
  decided_at INTEGER, created_at INTEGER NOT NULL)`;
const YES = new Set(["yes", "y", "approve", "approved", "ok", "lgtm", "ship", "ship it", "land", "👍", "✅"]);
const NO = new Set(["no", "n", "reject", "rejected", "back", "send back", "nope", "👎", "❌"]);
const HEADERS = { "Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex" };

let ready = false;
async function db(env) {
  if (!ready) {
    await env.DB.prepare(SCHEMA).run();
    ready = true;
  }
  return env.DB;
}

function same(a, b) {
  // constant-time string comparison
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

const json = (data, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { ...HEADERS, "Content-Type": "application/json" } });
const page = (body, status = 200) =>
  new Response(body, { status, headers: { ...HEADERS, "Content-Type": "text/html; charset=utf-8" } });
const notFound = () => page("<h1>Not found</h1>", 404);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

// ------------------------------------------------------------------ decisions

async function decide(env, row, approve, by, comment) {
  if (row.status !== "pending") return false;
  await (await db(env))
    .prepare("UPDATE approvals SET status=?, decided_by=?, comment=?, decided_at=? WHERE key=? AND status='pending'")
    .bind(approve ? "approved" : "rejected", by, (comment || "").slice(0, 1000), Date.now(), row.key)
    .run();
  return true;
}

function withBanner(row) {
  // braid uploads the page as it looked when pending; once decided here, swap the buttons for the outcome.
  if (row.status === "pending") return row.html;
  const words = {
    approved: "Approved. braid on your computer will land it within a few seconds of seeing this.",
    rejected: `Sent back${row.comment ? ": " + esc(row.comment) : ""}. braid will hand it back to the agent.`,
  };
  let html = row.html.replace(/<div class='bar'>[\s\S]*?<\/form><\/div>/, "");
  if (words[row.status]) {
    const refresh = row.status === "approved" ? "<meta http-equiv='refresh' content='5'>" : "";
    html = html.replace("</head>", refresh + "</head>")
      .replace("<main>", `<main><div class='card state'>${words[row.status]}</div>`);
  }
  return html;
}

// ------------------------------------------------------------------ email

function b64(text) {
  const bytes = new TextEncoder().encode(text);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin).replace(/.{76}/g, "$&\r\n");
}

function mime({ from, to, subject, text, html }) {
  const b = "braid-" + crypto.randomUUID();
  return [
    `From: braid <${from}>`, `To: ${to}`, `Reply-To: ${from}`,
    `Subject: =?UTF-8?B?${b64(subject).replace(/\r\n/g, "")}?=`,
    `Message-ID: <${crypto.randomUUID()}@${from.split("@")[1]}>`, `Date: ${new Date().toUTCString()}`,
    "MIME-Version: 1.0", `Content-Type: multipart/alternative; boundary="${b}"`, "",
    `--${b}`, "Content-Type: text/plain; charset=utf-8", "Content-Transfer-Encoding: base64", "", b64(text),
    `--${b}`, "Content-Type: text/html; charset=utf-8", "Content-Transfer-Encoding: base64", "", b64(html),
    `--${b}--`, "",
  ].join("\r\n");
}

async function sendEmail(env, mail) {
  if (!env.EMAIL || !env.OWNER_EMAIL || !env.FROM_EMAIL) return "email not configured on the worker";
  await env.EMAIL.send(new EmailMessage(env.FROM_EMAIL, env.OWNER_EMAIL, mime({
    from: env.FROM_EMAIL, to: env.OWNER_EMAIL, ...mail,
  })));
  return "sent";
}

function decodePart(headers, body) {
  if (/content-transfer-encoding:\s*base64/i.test(headers)) {
    const bin = atob(body.replace(/\s+/g, ""));
    return new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0)));
  }
  if (/content-transfer-encoding:\s*quoted-printable/i.test(headers)) {
    const bytes = [];
    const s = body.replace(/=\r?\n/g, "");
    for (let i = 0; i < s.length; i++) {
      if (s[i] === "=" && /^[0-9A-F]{2}$/i.test(s.slice(i + 1, i + 3))) {
        bytes.push(parseInt(s.slice(i + 1, i + 3), 16));
        i += 2;
      } else bytes.push(...new TextEncoder().encode(s[i]));
    }
    return new TextDecoder().decode(new Uint8Array(bytes));
  }
  return body;
}

export function plainText(raw) {
  // the text/plain part of a (possibly multipart) message, decoded
  const split = raw.indexOf("\r\n\r\n") >= 0 ? "\r\n\r\n" : "\n\n";
  const [head, ...rest] = raw.split(split);
  const body = rest.join(split);
  const boundary = /boundary="?([^";\r\n]+)"?/i.exec(head);
  if (!boundary) return decodePart(head, body);
  for (const part of body.split("--" + boundary[1])) {
    const i = part.indexOf(split);
    if (i < 0) continue;
    const ph = part.slice(0, i), pb = part.slice(i + split.length);
    if (/content-type:\s*multipart\//i.test(ph)) {
      const inner = plainText(part.replace(/^\s+/, ""));
      if (inner) return inner;
    } else if (/content-type:\s*text\/plain/i.test(ph) || !/content-type:/i.test(ph)) {
      return decodePart(ph, pb);
    }
  }
  return "";
}

export function parseReply(text) {
  const first = (text || "").split(/\r?\n/).map((l) => l.trim()).find((l) => l && !l.startsWith(">")) || "";
  const m = /^([^\W\d_]+(?: it| back)?|👍|👎|✅|❌)[\s,.:!-]*([\s\S]*)$/u.exec(first);
  if (!m) return null;
  const word = m[1].toLowerCase();
  if (YES.has(word)) return { approve: true, comment: m[2].trim() };
  if (NO.has(word)) return { approve: false, comment: m[2].replace(/^#?[A-Z2-9]{4}\b[\s,.:!-]*/i, "").trim() };
  return null;
}

// ------------------------------------------------------------------ http

async function api(request, env, url) {
  const auth = request.headers.get("Authorization") || "";
  if (!env.BRAID_KEY || !same(auth, `Bearer ${env.BRAID_KEY}`)) return json({ error: "unauthorized" }, 401);
  const d = await db(env);
  const m = /^\/api\/approvals(?:\/([\w-]+))?$/.exec(url.pathname);
  if (!m) return json({ error: "not found" }, 404);
  if (request.method === "POST" && !m[1]) {
    const a = await request.json();
    if (!a.key || !a.token || !a.code || !a.html) return json({ error: "key, token, code and html are required" }, 400);
    await d.prepare(`INSERT INTO approvals(key, code, token, html, diff, status, created_at)
                     VALUES (?, ?, ?, ?, ?, 'pending', ?)
                     ON CONFLICT(key) DO UPDATE SET code=excluded.code, token=excluded.token, html=excluded.html,
                     diff=excluded.diff, status='pending', comment='', decided_by='', decided_at=NULL`)
      .bind(a.key, a.code.toUpperCase(), a.token, a.html, a.diff || "", Date.now()).run();
    const link = `${url.origin}/a/${a.key}?t=${encodeURIComponent(a.token)}`;
    let email = "not requested";
    if (a.email) {
      const fill = (s) => String(s).replaceAll("{url}", link);
      try {
        email = await sendEmail(env, { subject: a.email.subject, text: fill(a.email.text), html: fill(a.email.html) });
      } catch (e) {
        email = `failed: ${e.message || e}`;
      }
    }
    return json({ url: link, email });
  }
  const row = m[1] && await d.prepare("SELECT * FROM approvals WHERE key=?").bind(m[1]).first();
  if (!row) return json({ error: "no such approval" }, 404);
  if (request.method === "GET") {
    return json({ status: row.status, comment: row.comment, decided_by: row.decided_by, decided_at: row.decided_at });
  }
  if (request.method === "PUT") {  // braid reports the outcome and the final page
    const a = await request.json();
    await d.prepare("UPDATE approvals SET status=?, html=COALESCE(?, html) WHERE key=?")
      .bind(a.status || row.status, a.html || null, row.key).run();
    return json({ ok: true });
  }
  return json({ error: "method not allowed" }, 405);
}

async function web(request, env, url) {
  const m = /^\/a\/([\w-]+)(\/decide|\/raw\.diff)?$/.exec(url.pathname);
  if (!m) return notFound();
  const row = await (await db(env)).prepare("SELECT * FROM approvals WHERE key=?").bind(m[1]).first();
  let token = url.searchParams.get("t") || "";
  let form = null;
  if (request.method === "POST" && m[2] === "/decide") {
    form = await request.formData();
    token = form.get("t") || "";
  }
  if (!row || !same(row.token, token)) return notFound();
  if (form) {
    const action = form.get("action");
    if (action === "approve" || action === "reject") await decide(env, row, action === "approve", "web", form.get("comment"));
    return new Response(null, { status: 303, headers: { ...HEADERS, Location: `/a/${row.key}?t=${encodeURIComponent(token)}` } });
  }
  if (m[2] === "/raw.diff") return new Response(row.diff, { headers: { ...HEADERS, "Content-Type": "text/plain; charset=utf-8" } });
  return page(withBanner(row));
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    try {
      if (url.pathname.startsWith("/api/")) return await api(request, env, url);
      if (url.pathname === "/") return new Response("braid approvals\n", { headers: HEADERS });
      return await web(request, env, url);
    } catch (e) {
      return json({ error: String(e.message || e) }, 500);
    }
  },

  // replies to approval emails arrive here through an Email Routing rule for FROM_EMAIL
  async email(message, env) {
    const sender = (message.from || "").toLowerCase();
    if (!env.OWNER_EMAIL || sender !== env.OWNER_EMAIL.toLowerCase()) {
      message.setReject("braid only accepts replies from its owner");
      return;
    }
    const code = /\[braid ([A-Z2-9]{4})\]/.exec(message.headers.get("subject") || "");
    const reply = parseReply(plainText(await new Response(message.raw).text()));
    if (!code || !reply) return;
    const row = await (await db(env))
      .prepare("SELECT * FROM approvals WHERE code=? AND status='pending' ORDER BY created_at DESC LIMIT 1")
      .bind(code[1]).first();
    if (row) await decide(env, row, reply.approve, "email", reply.comment);
  },
};
