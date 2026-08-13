# FluxWeb — Pre-Launch Security & Bug Audit

**Scope:** entire repo at commit `cd7e851` (`app.py`, `checker.py`, `templates/`, `static/js/`, config, committed DB files, `.env` on disk).
**Verdict:** **Do not go live in the current state.** There are working payment-bypass paths, a forgeable session secret, and customer data already published in git history. Sections C-1 → C-8 must be fixed before accepting a single real payment.

Severity key:
- **CRITICAL** — direct financial loss, account takeover, or data breach; exploitable by an unauthenticated or ordinary user today.
- **HIGH** — serious exposure or guaranteed money-losing bug; exploit needs a small extra condition.
- **MEDIUM** — real bug or weakness that will bite in production.
- **LOW** — hygiene, correctness, maintainability.

---

## CRITICAL

### C-1. Guessable `SECRET_KEY` → full session forgery, including admin
`app.py:187`, `.env`

The key in `.env` is `flux-secret-123-asdjkhasjkhdj…` — a human-typed pattern, not random. Flask sessions are **client-side signed cookies**: anyone who guesses or brute-forces this key can mint a cookie with `user_id` = the admin's id and get the entire `/admin` surface (provision, delete servers, edit plans, read every user). They can also read/forge cart contents and coupon discounts.

The same key also derives the Fernet key used to encrypt every user's panel password (`app.py:24-27`), with a **hardcoded salt** (`b'flux-pelican-salt'`) — so key compromise also means plaintext panel passwords for all customers (see H-15).

**Fix:** `SECRET_KEY` = `secrets.token_urlsafe(64)`, stored only in the host's env vars (Vercel project settings), never in a file. Rotating it invalidates all sessions — do it before launch. Consider splitting the encryption key from the session key so rotating one doesn't destroy the other. Refuse to boot if `SECRET_KEY` is unset or matches the default (currently it only logs a warning, and only under `__main__` — `app.py:1946`, which never runs on Vercel).

### C-2. Live production secrets sitting in a working-tree file next to a 60-second auto-commit script
`.env`, `git-push.bat`

`.env` currently holds: a **live** Stripe secret key (`sk_live…`), a Pelican **admin** API key (full panel control), a Pelican client key, the production Postgres URL with credentials, the admin password, a Wise API token, and the PayPal client id. It is correctly gitignored and I confirmed it is **not** in git history (`git log --all -- .env` is empty) — but `git-push.bat` runs `git add . && git commit && git push` in a loop every 60 seconds. One `.gitignore` edit, one rename, one `git add -f`, and every credential is public and irrevocable.

**Fix:** delete `git-push.bat`. Move all secrets to the platform's env-var store. Treat the current values as at-risk and rotate them at launch anyway (Stripe, Pelican, Wise, DB password, admin password). Add a pre-commit secret scanner (`gitleaks`).

### C-3. Customer emails and password hashes are already published in git
`instance/flux_tickets.db`, `instance/tickets.db` (both tracked)

`instance/flux_tickets.db` is committed and contains a `user` table with **5 `pbkdf2:sha256` password hashes and 14 distinct email addresses** (real ones — gmail, proton, plus the admin account), plus a `ticket` table with `user_email` / `user_name`, and a `message` table of support conversations. This is a live data breach the moment the repo is public or shared.

**Fix:** purge from history (`git filter-repo --path instance/ --invert-paths`), force-push, add `instance/` and `*.db` to `.gitignore`, force a password reset for every affected account, and notify them if the repo was ever public (GDPR/UK-GDPR breach-notification clock may apply).

### C-4. PayPal: the amount is chosen by the browser and never checked by the server
`templates/cart.html:563-570` and `:643`, `app.py:1382-1442`

The order is created **client-side**:
```js
createOrder: (data, actions) => actions.order.create({
    purchase_units: [{ amount: { value: cartTotal } }]   // cartTotal is a JS variable
})
```
and `verify_paypal_order()` only checks `status == 'COMPLETED'`. It never checks the **amount**, the **currency**, or the **payee**. Any customer can open devtools, set `cartTotal = "0.01"`, pay one cent, and receive the full cart. This is not theoretical — it's a one-line console edit.

**Fix:** create the order **server-side** (`POST /v2/checkout/orders` from Flask with a server-computed amount), return only the order id to the browser, and on capture verify `purchase_units[0].amount.value == server_total`, `currency_code == 'USD'`, and `payee.merchant_id` matches yours.

### C-5. Payment references are replayable and not bound to a user
`app.py:1403-1442` (PayPal), `app.py:1479-1511` (Stripe)

`payment_ref` is stored on `ServerRecord` but there is **no uniqueness constraint and no check that it was already consumed**, and no check that the payment belongs to the logged-in user. So:
1. Pay legitimately once, note your `paypal_order_id` / Stripe `session_id`.
2. Refill the cart, POST `/checkout` with the same `paypal_order_id` (or GET `/stripe-success?session_id=…`) again.
3. Unlimited free servers, forever. The id can also be shared with other accounts.

**Fix:** a `Payment` table with a `UNIQUE` constraint on the provider reference, recorded inside the same transaction as provisioning, and a check that the payment's metadata identifies this `user_id`.

### C-6. Stripe: the charge amount is decoupled from what gets provisioned
`app.py:1447-1477` → `app.py:1479-1511`

`/create-stripe-checkout` computes `total` from the cart and creates the Stripe session. `/stripe-success` then re-reads **the current session cart** and provisions whatever is in it — it never compares against `checkout_session.amount_total`. Attack: check out with a $0.90 plan, and before returning to the success URL (the redirect is fully under the attacker's control), call `/add-to-cart` for the $10.80 plan. Pay $0.90, get both.

**Fix:** snapshot the cart server-side (e.g. a pending `Order` row) at session-creation time, pass the order id in Stripe `metadata`, and provision strictly from the snapshot after asserting `amount_total == order.total_cents`.

### C-7. No Stripe webhook — payment is confirmed only by the browser coming back
`app.py:1479`

Provisioning happens exclusively in the `success_url` handler. If the customer closes the tab, loses signal, or their session cookie expires (`/stripe-success` redirects to `/login` at `app.py:1495`, then the cart is orphaned), **Stripe has their money and they get nothing**, with no record anywhere that they paid. This will generate chargebacks from day one.

**Fix:** implement `checkout.session.completed` webhook with signature verification (`stripe.Webhook.construct_event`), exempt it from CSRF, make it the authoritative provisioning trigger, and make provisioning idempotent on the session id. The success page should only *display* status.

### C-8. Panel account takeover via unverified email registration
`app.py:1579-1608` (`get_or_create_pelican_user`), `app.py:1066-1100` (`change_password`), `app.py:1829-1848` (`register`)

There is **no email verification** on registration. `get_or_create_pelican_user` looks up the Pelican panel by email and adopts any existing panel user with that address:
```python
requests.get(f"{url}/api/application/users?filter[email]={user.email}")
… user.pelican_user_id = data['data'][0]['attributes']['id']
```
So: register on FluxWeb with a victim's email address → your account is silently bound to *their* Pelican panel user → hit `/account/change-password`, which PATCHes the panel password (`app.py:1092`) → you now own their panel account and every game server on it, including ones bought elsewhere.

**Fix:** require verified email before any panel linkage, and never adopt a pre-existing panel user by email alone (link only accounts this site created, tracked by id).

---

## HIGH

### H-9. Admin authentication is a single email string comparison
`app.py:169-170`, `391-406`, `1896-1903`

Admin = "your `User.email` equals `ADMIN_EMAIL`". The admin account is auto-created on first request from `ADMIN_PASSWORD`, which **defaults to `'changeme'`** if the env var is missing. No MFA, no IP allowlist, no separate admin login route (`templates/auth/admin_login.html` exists but is orphaned — nothing routes to it), no re-authentication for destructive actions, and no admin action audit log. Combined with C-1, one guessed cookie owns the business.

**Fix:** an explicit `is_admin` column, mandatory TOTP for admin, hard failure at boot if `ADMIN_PASSWORD` is default/unset, and an audit log of every admin mutation.

### H-10. No rate limiting anywhere in the application
Every route

`/login` (unlimited credential stuffing, no lockout), `/register` (account spam), `/apply-coupon` (coupon-code enumeration — codes are short and there's no attempt cap), `/checker` (unauthenticated file upload), `/r/<code>` (one DB write per request), and `/account` (each load fans out to N panel API calls). Any of these is a cheap DoS or brute-force vector.

**Fix:** `Flask-Limiter` with a Redis backend (in-memory won't work across serverless instances), strictest on auth and coupon endpoints; progressive account lockout on failed logins.

### H-11. Apple Pay / Google Pay / Card buttons charge the customer and then fail checkout
`templates/cart.html:626-648`

The alternate funding-source buttons capture the payment and then do:
```js
onApprove: (data, actions) => actions.order.capture().then(() => {
    document.getElementById('order-form').submit();   // no paypal_order_id appended!
})
```
The main PayPal button appends the hidden `paypal_order_id` input (`cart.html:610-616`); these do not. So `/checkout` sees `total > 0` and no order id, flashes *"Invalid PayPal order ID"*, and redirects to the cart — **money captured, nothing provisioned, no record**.

**Fix:** append the order id in both handlers (or better, per C-4, move order creation server-side and have one shared confirm endpoint).

### H-12. PayPal is misconfigured — every PayPal payment will currently be rejected
`app.py:55-57`, `1382-1401`, `.env`

`.env` has **no `PAYPAL_SECRET_KEY`** and **no `PAYPAL_ENV`**. Consequences: `verify_paypal_order()` returns `False` immediately for every order (`app.py:1383-1385`), so *all* PayPal checkouts are captured then rejected; and `PAYPAL_API_BASE` falls back to the **sandbox** endpoint while `PAYPAL_CLIENT_ID` is a live client id — so even with a secret added, verification would query the wrong environment. Meanwhile `STRIPE_SECRET_KEY` is a **live** `sk_live…` key: the two providers are in different modes.

**Fix:** set `PAYPAL_SECRET_KEY` and `PAYPAL_ENV=live`, and add a startup config check that fails loudly when a payment provider is half-configured or when providers disagree about live/test.

### H-13. No password reset and no email verification
`app.py:1829-1870`

There is no forgot-password flow at all — a customer who forgets their password is permanently locked out of servers they are paying for, with no self-service recovery, and support has no safe way to help (see also C-8 for the verification half). There is also no transactional email capability in the project whatsoever (no SMTP/provider dependency in `requirements.txt`), which also means no receipts, no expiry warnings, and no suspension notices.

### H-14. Money is handled as floating point, and the Stripe amount truncates
`app.py:318` (`price = db.Column(db.Float)`), `1417-1419`, `1452-1454`, `1468`

```python
'unit_amount': int(total * 100),
```
`int()` truncates rather than rounds: a total of `1.15` becomes `114.999…` → **114 cents**. Every discounted total is a coin-flip on undercharging. Float prices also accumulate error across multi-item carts and won't reconcile against provider records.

**Fix:** store prices as integer cents (or `Numeric(10,2)`), compute with `Decimal`, and `round()` at the boundary.

### H-15. Customer passwords are stored reversibly and shown in plaintext in the browser
`app.py:33-47`, `285`, `289-292`, `1077-1078`; `templates/account.html:31-49`

Panel passwords are Fernet-encrypted (reversible, key derived from `SECRET_KEY` with a static salt) and rendered directly on the account page. Worse, `change_password` sets:
```python
user.password_hash   = generate_password_hash(new_password)
user.pelican_password = encrypt_password(new_password)   # same password, recoverable
```
So the user's **site password** is stored in a recoverable form. Anyone with the DB + `SECRET_KEY` (or just C-1) gets plaintext passwords for every customer — which, given password reuse, extends far beyond your service.

Also, `decrypt_password` swallows failures and returns the **ciphertext itself** as if it were the password (`app.py:45-47`), so a key rotation silently starts showing users garbage strings labelled as their password.

**Fix:** never store a recoverable copy of the site password. For the panel, generate an independent random password shown **once** at creation, or use Pelican's own password-reset/SSO flow.

### H-16. No order, invoice, or payment records exist
`app.py` — no `Order`/`Payment`/`Invoice` model

The only trace of a transaction is a `payment_ref` string on `ServerRecord`, deleted along with the record (`app.py:1570`). There is no amount, currency, timestamp, provider, status, coupon applied, refund state, or line items. For a business taking card payments this means: no invoices for customers, no way to answer a chargeback, no revenue reconciliation, no refund path, and no audit trail. It's also a tax/accounting record-keeping problem.

**Fix:** persist a full order/payment ledger before provisioning; make it append-only.

### H-17. Unbounded request bodies; unauthenticated file upload
`app.py` (no `MAX_CONTENT_LENGTH`), `checker.py:8-20`, `app.py:507-528`, `590-604`

`MAX_CONTENT_LENGTH` is never set. `/checker` is **public**, reads the entire uploaded file into memory and `json.loads` it — a few concurrent 500 MB uploads exhaust the function. Admin plan-image upload base64-encodes the file into a DB column with no size cap (and base64 inflates by 33%, bloating every page that renders the plan), and validates by **file extension only**, never content type or magic bytes.

**Fix:** `app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024`, put `/checker` behind admin auth (it's an internal tool), validate images by decoding them (Pillow) and store them in object storage rather than the database.

### H-18. Dependencies are 1-2 years out of date with known CVEs
`requirements.txt`

`Flask 2.3.2` / `Werkzeug 2.3.6` (multipart-parsing DoS CVE-2023-46136, plus later-fixed `safe_join`/debugger issues), `requests 2.31.0` (CVE-2024-35195), `cryptography 41.0.3` (several fixed in 41.0.4+/42.x), `stripe 5.4.0` (very old API bindings). No WSGI server pinned, no `Flask-Limiter`, no `Flask-Migrate`.

**Fix:** upgrade to current majors, add `pip-audit`/Dependabot to CI.

---

## MEDIUM

### M-19. Open redirect on login and register
`app.py:1844-1846`, `1860-1862`
```python
return redirect('/' + next_url.lstrip('/'))
```
`lstrip('/')` blocks `//evil.com`, but **not** backslashes: `?url=\evil.com` yields `redirect('/\evil.com')`, which Chrome and Safari normalise to `//evil.com` — a protocol-relative redirect off-site. Prime phishing vector on a login page. **Fix:** allowlist known internal endpoints, or validate with `urlparse` that netloc is empty and the path starts with a single `/` followed by an alphanumeric.

### M-20. Renewals silently create a second server instead of renewing
`app.py:1179-1196` adds `{'type': 'renewal', 'server_id': …}` to the cart, but `provision_servers_from_cart` (`app.py:1284-1340`) only special-cases `'upgrade'`. Renewal items fall through to the generic branch: a **brand-new server is provisioned**, `expires_at` on the original is never extended, and the customer's server gets suspended and then auto-deleted after 7 days (`app.py:936-942`) despite having paid to renew. Data loss plus a double resource cost to you.

### M-21. Software override deploys the wrong container image
`app.py:1306-1311` sets `egg_override` (Python 232 / Node.js 314) and `final_egg_id` goes into the payload — but the egg detail fetch that populates `docker_image`, `startup`, and all environment variables uses `plan.egg_id`:
```python
resp = requests.get(f"{url}/api/application/eggs/{plan.egg_id}?include=variables", …)
```
A Discord-bot customer choosing Python gets egg 232 with the Node.js image, startup command, and env vars. Should be `final_egg_id`.

### M-22. Free spec upgrades
`app.py:1219-1249`. `add_upgrade_to_cart` accepts **any** `plan_id` — the "same game, higher price" filter exists only in the UI (`app.py:1212-1215`) — and prices the upgrade as `max(0, new.price - current.price)`. Pick any plan with better specs but a lower or equal price (trivially available across the minecraft/hytale/dedicated/discord_bot price tables) and get the hardware upgrade for **$0.00**. Enforce the same-game/higher-price constraint server-side.

### M-23. The cart lives in the session cookie
`app.py:1104-1120`. Every cart item (with its full display name — upgrade entries are long) is stored in the signed cookie, with no item cap. Past ~4 KB the browser silently discards the cookie: the customer is logged out and loses their cart mid-checkout, non-deterministically. Move the cart to a DB table keyed by user (also required for C-6).

### M-24. Several unhandled-exception 500s reachable from normal use
- `app.py:908`, `1069`, `1409`: `user = db.session.get(User, session['user_id'])` then `user.id` — if the row was deleted (or the DB was reset, as it has been), every request 500s until the cookie is cleared. Log the user out instead.
- `app.py:1834`, `1854`: `request.form.get('email').lower()` → `AttributeError` on a missing field.
- `app.py:1641`: `int(final_location_id)` with a user-supplied `location_id` from the checkout form → `ValueError`. That field is also never validated against the plan, so a user can pick any node.
- `app.py:1052`: `request.json.get('action')` raises on a non-JSON body; `action` is then forwarded to the panel unvalidated (should be an allowlist of `start|stop|restart|kill`).
- `app.py:1131`, `1162`, `1417`: `item['price']` → `KeyError` on any cart shape change; old cookies will hit this after a deploy.

### M-25. Coupons have no constraints
`app.py:825-834`, `1251-1268`. No expiry, no usage cap, no per-user limit, no minimum spend, no active flag, and **no validation that `discount_percent` ≤ 100**. A 100%+ coupon makes `total <= 0`, which routes checkout into the `FREE_CHECKOUT` branch (`app.py:1421-1432`) and provisions everything with no payment. The discount is also re-read from the session at checkout rather than re-validated against the DB.

### M-26. Allocation selection races and random port collisions
`app.py:1643-1686`. Two simultaneous purchases scan the node's free allocations and can select the **same** allocation id; one provision fails after payment. When none is free, a port is picked with `random.randint(25565, 26000)` with no collision check or retry, then the code re-scans and grabs "any" free allocation — potentially a different one than it just created.

### M-27. `/account` is a synchronous fan-out to the panel with commits in a loop
`app.py:904-993`. Per page load, per server: up to 4 sequential HTTP calls plus individual `db.session.commit()` calls, all wrapped in a bare `except: pass`. With a handful of servers this exceeds Vercel's function timeout; when the panel is slow the page hangs; and every failure is invisible. Move status sync to a background job / cron and render from the DB.

### M-28. Errors are swallowed and printed, not logged
Bare `except:` / `except Exception: pass` at `app.py:933`, `964`, `973`, `984-986`, `1750`, `1792`, and `print()` instead of `app.logger` at `72`, `117`, `137`, `503`, `552`, `942`, `1094`. In production you will have no idea why a provision failed. Add structured logging and an error tracker (Sentry).

### M-29. CSP is permissive enough to be decorative; one `|safe` sink
`app.py:267-274` allows `'unsafe-inline'`, `'unsafe-eval'`, and bare `https:` for `script-src` — any HTTPS host can serve script, and inline injection is unrestricted. `templates/index.html:737` renders `{{ faq.answer|safe }}` unescaped. That input is admin-only today, so it's not directly exploitable by users — but it means any admin-account compromise (H-9) upgrades straight to persistent XSS against every visitor. Tighten CSP with nonces and drop `|safe` (or sanitise with bleach).

### M-30. Sessions cannot be revoked
Client-side cookie sessions with a 7-day lifetime (`app.py:198`) mean there is no server-side "log out all devices", no way to kill a stolen session after a password change, and no session invalidation on privilege change. `change_password` (`app.py:1066`) doesn't even rotate the current session. Move to server-side sessions or add a per-user token version claim.

### M-31. Debug flag controls three security settings at once
`app.py:189`, `196`, `199`, `1949`. Setting `FLASK_DEBUG=true` in production simultaneously disables the `Secure` cookie flag, disables `WTF_CSRF_SSL_STRICT`, and enables the Werkzeug debugger (arbitrary code execution via the console). One misplaced env var is a total compromise. Decouple these, and hard-fail if debug is on outside development.

### M-32. `ProxyFix` trusts one hop unconditionally
`app.py:173`. Correct behind Vercel; if the app is ever run directly (it binds `0.0.0.0:27003` at `app.py:1950`) a client can spoof `X-Forwarded-For` and `X-Forwarded-Proto`, which matters once rate limiting is added.

---

## LOW

| # | Issue | Location |
|---|---|---|
| L-33 | `temp_test.py` is committed and is not valid Python (`r = c.get(/)`) — it would break any `pytest` collection or `compileall` in CI. Delete it. | `temp_test.py:3` |
| L-34 | `git-push.bat` auto-commits and pushes everything every 60 s — the direct cause of C-3, and a standing risk of publishing secrets. Delete it. | `git-push.bat` |
| L-35 | `.gitignore` contains only `__pycache__` and `.env` (and has no trailing newline). Missing `instance/`, `*.db`, `.venv/`, `*.pyc`, `.vercel`. | `.gitignore` |
| L-36 | `DATABASE_URL` falls back to `sqlite:///flux_servers.db` — on Vercel that's an ephemeral, per-instance filesystem, so a missing env var means silent data loss rather than a crash. Fail fast instead. | `app.py:177` |
| L-37 | `/r/<code>` redirects to an unvalidated admin-supplied `target_url` (open redirect on your domain) and performs a DB write per hit with no dedupe or bot filtering, so click counts are meaningless. | `app.py:1911-1918` |
| L-38 | User enumeration: registration replies "Email already registered." Use a neutral message plus an email-based flow. | `app.py:1836-1838` |
| L-39 | Registration enforces **no** password policy at all, while `/account/change-password` requires 8 characters — so the weakest passwords enter through the front door. Username isn't validated either, then gets mangled into a panel username (`.replace(' ','_').lower()`), which can collide or be rejected by Pelican. | `app.py:1833-1839`, `1612` |
| L-40 | Dead code/templates: `templates/auth/admin_login.html` has no route; `templates/errors/404.html` and `500.html` are unused (both handlers render `error.html`); `get_pelican_egg_variables` is never called; `check_db.py` is a debug script. | multiple |
| L-41 | `X-XSS-Protection` is deprecated and can itself introduce vulnerabilities — remove it. No `Permissions-Policy`. The `Server: Cloud-Shield` header is security theatre that adds nothing. | `app.py:241-256` |
| L-42 | `vercel.json` uses the legacy `builds`/`routes` schema with no Python runtime pin — builds will drift. | `vercel.json` |
| L-43 | Schema changes are applied via hand-rolled `ALTER TABLE` on first request (`apply_pending_schema_updates`) instead of migrations. It only knows three columns; any future model change silently diverges from the DB. Adopt Alembic/Flask-Migrate. | `app.py:214-237`, `1875-1909` |
| L-44 | No tests of any kind, and no CI. For a codebase handling payments, at minimum cover the checkout/provisioning paths. | — |
| L-45 | `/checker` and `/ram-calculator` are public utility pages that leak internal tooling; `/checker` in particular is an admin plan-import validator. | `checker.py:7` |

---

## Recommended order of work

**Before launch (non-negotiable):**
1. C-3 — purge git history, rotate credentials, reset affected passwords.
2. C-1, C-2 — regenerate `SECRET_KEY`, move all secrets to platform env vars, delete `git-push.bat`.
3. C-4, C-5, C-6, C-7 + H-11, H-12, H-14, H-16 — rebuild checkout as: server-computed order → server-created payment intent/order → webhook-driven, idempotent provisioning against a persisted order snapshot. This is one coherent piece of work, not eight patches.
4. C-8, H-13 — email verification + password reset.
5. H-9, H-10 — real admin auth with MFA; rate limiting.
6. H-15 — stop storing recoverable passwords.
7. H-17, H-18 — request size limits, dependency upgrades.

**First week after:** M-19 through M-26 (open redirect, renewal bug, egg mismatch, free upgrades, cart storage, crash paths, coupon rules, allocation races).

**Then:** the remaining MEDIUMs (observability, CSP, session revocation) and the LOW hygiene list.

One structural note: `app.py` is a single 1,950-line module mixing models, panel integration, payments, admin, and auth, with no test coverage. The payment rework in step 3 is a natural moment to split it into blueprints (`auth`, `billing`, `panel`, `admin`) with the payment logic isolated and unit-tested — trying to fix eight payment bugs in place, in a file this shape, is how the ninth gets introduced.
