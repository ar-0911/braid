# braid approvals on Cloudflare

This Worker hosts braid's review pages, emails you each approval request, and records your yes or no, from a
link click or an email reply. braid on your computer uploads requests and asks the Worker for answers every few
seconds, so nothing on your computer is reachable from the internet and the links keep working while your laptop
sleeps. The landing itself still happens on your computer, as soon as the watcher sees your yes.

Free plan is enough: Workers, D1 and Email Routing.

## Deploy (once)

You need a domain on Cloudflare for the email part.

1. **Email Routing**: in the dashboard open your domain, then *Email > Email Routing*, enable it, and under
   *Destination addresses* add and verify the address you want approvals at (e.g. your Gmail).
2. **Configure**: in this folder, edit `wrangler.toml`: `OWNER_EMAIL` and `destination_address` = that address,
   `FROM_EMAIL` = an address on your domain, e.g. `braid@yourdomain.com`.
3. **Database and key**:
   ```sh
   cd cloudflare
   npx wrangler login
   npx wrangler d1 create braid-approvals      # paste the database_id it prints into wrangler.toml
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # your key; copy it
   npx wrangler secret put BRAID_KEY           # paste the key
   npx wrangler deploy                         # prints https://braid-approvals.<you>.workers.dev
   ```
4. **Replies by email**: *Email Routing > Routing rules > Create address*: custom address `braid` (the
   `FROM_EMAIL`), action *Send to a Worker*, worker `braid-approvals`.

## Point braid at it

In each repo:

```sh
braid settings approve.required yes
braid settings approve.channels cloudflare
braid settings approve.cloudflare.url https://braid-approvals.<you>.workers.dev
braid approvals secret BRAID_RELAY_KEY        # the same key as above
braid approvals test                          # should print: ok  cloudflare
```

Keep the watcher running (`braid start` starts it, or `braid daemon start`). One Worker can serve every repo.

## Security

- braid's calls carry the key (`Authorization: Bearer`); without it the API answers 401.
- Each review link carries its own random token; without it the page is a 404.
- Email replies count only from `OWNER_EMAIL`, and only with the request's code in the subject, which only the
  emails you received contain.
- The page lands only on a button press (a POST), so link previews and mail scanners can't approve anything.
