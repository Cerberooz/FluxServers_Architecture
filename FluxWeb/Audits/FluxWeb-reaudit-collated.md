# FluxWeb — Re-Audit (Security + Quality), Collated

**Date:** 2026-08-10
**Scope:** the whole repository after the remediation work — `fluxweb/` package, templates, config, tooling, dependencies.
**Baseline:** the two prior reports in this folder (`FluxWeb-security-audit.md`, `FluxWeb-architecture-review.md`), which used ids C-*, H-*, M-*, P-*, SC-*, L-*.

**What changed since the first audit:** Python is now installed, so this pass is *executed*, not just read. Tests run, the app boots, every page renders, and dependencies are scanned against a live vulnerability database. The first audit was static-only.

## Verdict

The eight critical payment/auth bypasses are closed and covered by tests that fail if they return. **Three blockers remain, none of them code**: purge the leaked customer database from git history, rotate the exposed live credentials, and supply the production secrets the app now refuses to boot without.

This pass also found **six new defects introduced by the remediation itself**, four of them capable of losing money or destroying customer data. All six are fixed and covered. That is the main argument for re-auditing rework rather than trusting it.

| Gate | Result |
|---|---|
| Tests | **152 passed**, 0 failed |
| Coverage | 58% overall; 94–100% on billing, lifecycle, user, config |
| Dependency CVEs | **0** (was 22 across 7 packages at the start of this pass) |
| Lint (ruff, incl. bandit `S` rules) | clean |
| Format (black) | clean |
| Route render smoke (26 routes × 3 privilege levels) | **0 server errors** |
| Live HTTP check | 16× 200, 3× 302, 1× 404, 0× 500 |
| URL compatibility | all 57 original paths intact |

---

## Section 1 — New defects found in the remediation

These did not exist in the original codebase. I wrote them.

### N-1. Retrying POST to the panel could double-provision — **Critical**, fixed
`fluxweb/integrations/pelican.py`

The new `PelicanClient` set `allowed_methods={"GET","POST","PATCH","DELETE"}` with `status_forcelist=(429,502,503,504)`. If the panel created a server and *then* the gateway returned 502, urllib3 would silently retry the POST and create a **second server for one payment**.

The order-level idempotency work does not catch this: the duplicate happens one layer below, inside the HTTP client, so the order still shows a single fulfilled line. Retries are now restricted to `{GET, HEAD}`; write failures surface as `PanelError` and are retried deliberately.

The PayPal client was checked and is safe — it never set `allowed_methods`, and urllib3's default excludes POST.

### N-2. A paid order that failed provisioning could never be retried — **Critical**, fixed
`fluxweb/models/billing.py`

`Order.is_paid` was derived from the status enum: `status in {PAID, PROVISIONING, COMPLETED}`. When provisioning failed, status became `FAILED` — which is not in that set — so `is_paid` returned False and `provision_order` refused to run. **A customer who paid and hit a panel error was permanently stuck: money taken, no server, retry impossible, including via the CLI.**

`is_paid` is now keyed on `paid_at`, which is set once and never cleared. Payment and fulfilment are separate concerns and are now modelled that way. Found by a test I wrote for a *different* bug (N-3).

### N-3. Concurrent webhook deliveries could both provision — **High**, fixed
`fluxweb/services/provisioning.py`

Idempotency relied on checking `item.is_fulfilled` in Python with no lock. Stripe can deliver the same event twice concurrently, and a customer can hit the PayPal capture endpoint while a webhook is in flight — both callers read "unfulfilled" before either writes, and both provision.

Replaced with an atomic compare-and-swap: exactly one caller can move an order from `PAID`/`FAILED` to `PROVISIONING`; everyone else returns immediately. `flask retry-order --force` releases an order stranded by a crash mid-run.

### N-4. Cron secret transmitted in the URL query string — **High**, fixed
`vercel.json`, `fluxweb/web/jobs.py`

The scheduled-job endpoint accepted `?token=<CRON_SECRET>`, and `vercel.json` used exactly that. Secrets in URLs land in access logs, proxy logs, and `Referer` headers — the original audit's own privacy rule. Now header-only (`Authorization: Bearer`), which Vercel Cron sends automatically when `CRON_SECRET` is set on the project.

### N-5. One sweep could delete the entire fleet — **High**, fixed
`fluxweb/services/servers.py`

`sync_all_servers` deleted every server past its grace period with no bound. A cron outage, a clock problem, or a bad expiry import would destroy every customer server in a single pass, irreversibly. Deletions are now capped per run (default 25) with a loud error when the cap trips; the remainder is reconsidered next run.

Also hardened: a panel failure during delete no longer marks the record `DELETED`, which would have orphaned a still-running, still-billing server.

### N-6. `imghdr` import would have crashed the app on Python 3.13 — **Medium**, fixed
`fluxweb/web/admin.py`

`imghdr` was removed from the standard library in 3.13. Since it was imported at module scope, the app would fail to start entirely, not just fail image upload. Replaced with explicit magic-byte sniffing (PNG/JPEG/GIF/WebP).

**Also fixed earlier this session**, same category: `run.ps1` used `2>&1` on native commands, which under PowerShell 5.1 + `$ErrorActionPreference='Stop'` turns ordinary stderr output into a terminating error; and `run.ps1` ran `flask db migrate` on every start, which would have accumulated an empty Alembic revision per run.

---

## Section 2 — Original findings, verified status

### Critical (C-1 … C-8)

| Id | Finding | Status | Evidence |
|---|---|---|---|
| C-1 | Guessable `SECRET_KEY` | **Fixed** | Boot refuses weak/default keys; dev generates a random ephemeral key, never a fixed one. `ENCRYPTION_KEY` split out. 8 config tests. |
| C-2 | Live secrets beside a 60s auto-push loop | **Fixed in code** | `git-push.bat` deleted; gitleaks in pre-commit + CI. **Rotation still owed** — see Blockers. |
| C-3 | Customer PII + hashes committed | **Not fixed** | Blobs still reachable at `cd7e851`. Untracking does not remove history. **Blocker.** |
| C-4 | Browser-chosen PayPal amount | **Fixed** | Server-side order creation; amount, currency, and payee verified on capture. 4 tests incl. the $0.01 attack. |
| C-5 | Payment replay | **Fixed** | `UNIQUE(provider, provider_ref)` + per-line `fulfilled_at` + atomic claim (N-3). 4 tests. |
| C-6 | Cart swappable after payment | **Fixed** | Frozen `Order` snapshot; provisioning never reads the session cart. 2 tests. |
| C-7 | No Stripe webhook | **Fixed** | Signature-verified `/webhooks/stripe` is authoritative; success page is display-only. 2 signature-rejection tests. |
| C-8 | Panel takeover via unverified email | **Fixed** | `filter[email]` adoption removed; email verification gates provisioning. 3 tests, one asserting the lookup cannot reappear in source. |

### High

Fixed: **H-9** (real `is_admin` flag, no bare email compare), **H-10** (Flask-Limiter + account lockout), **H-11** (alternate PayPal buttons share the capture path), **H-12** (config refuses half-configured providers), **H-13** (password reset + verification, pluggable mailer), **H-14** (integer cents; `to_cents(1.15) == 115`), **H-15** (site password no longer mirrored to the panel), **H-16** (Order/OrderItem/Payment ledger), **H-17** (`MAX_CONTENT_LENGTH`, magic-byte validation, `/checker` behind admin auth), **H-18** (dependencies — see below).

**H-18 re-opened and re-fixed during this pass.** The replacement pins I chose were *themselves* vulnerable: `pip-audit` reported **22 CVEs across 7 packages** (Flask, Werkzeug, Jinja2, requests, urllib3, python-dotenv, cryptography). My knowledge cutoff predates those advisories, which is precisely why a scanner belongs in CI rather than a human picking versions. Now at zero, verified, with the full suite passing on the upgraded stack.

### Medium / Low

Fixed: **M-19** (open redirect — see below), **M-20** (renewals extend instead of duplicating), **M-21** (one egg id for payload and metadata), **M-22** (upgrades must be same-game and dearer), **M-24** (crash paths: deleted-user sessions, missing form fields, non-JSON bodies), **M-25** (coupon expiry/limits/clamping), **M-26** (allocation retry), **M-27** (sync moved off the page load, throttled), **M-28** (structured logging; 0 bare `except:`), **M-30** (server-side revocation via `is_admin` + lockout), **M-31** (debug decoupled from cookie/CSRF settings), **L-33/34/35** (dead files removed, `.gitignore`), **L-36** (no SQLite fallback in production), **L-37** (referral URL scheme validated), **L-38** (registration no longer discloses existing addresses), **L-39** (one password policy), **L-41** (`X-XSS-Protection` dropped, `Permissions-Policy` added), **L-43** (Alembic), **L-44** (152 tests + CI).

**M-19 was found to be incompletely fixed during this pass.** The first implementation prefixed a slash *before* parsing, so `https://evil.com` became the harmless-but-wrong `/https://evil.com` rather than being rejected — and `javascript:alert(1)` passed through as a path. The value is now parsed before normalisation. Caught by the test suite, not by review.

**Still open, deliberately deferred** (all were "first month" tier):

| Id | Finding | Why deferred |
|---|---|---|
| P-4 | Plan images are base64 data-URIs in Postgres | Needs object storage (Vercel Blob/S3). Size now capped at 512 KB and content-validated. |
| P-6 | 28 `<img>` tags, **0** `loading="lazy"`; 14 MB of assets | Pure frontend; no correctness risk. Biggest remaining perceived-speed lever. |
| P-7 | ~2,900 lines of inline `<style>` across 20 templates | Cosmetic refactor, large diff, zero behaviour change. |
| M-3 | 6 orphaned templates still present | Harmless; deleting them is a judgement call about future use. |
| M-7 | `admin.html` and `checker.html` don't extend `base.html` | 530-line template rewrite; high regression risk for no security gain. |
| M-23 | Cart still in the session cookie | **Materially reduced**: the cookie now holds only ids, never prices, and is capped at 20 items. Prices always come from the database. Moving it to a table is the remaining step. |
| M-29 | CSP still allows `'unsafe-inline'`/`'unsafe-eval'`; one `\|safe` sink | CSP was tightened (host allowlists, `object-src 'none'`, `frame-ancestors`, `base-uri`, `form-action`) but nonces require touching every inline block. The `\|safe` sink is admin-authored FAQ content. |
| SC-6 | Panel sync can't scale independently of web | Blueprints make this possible now; actually splitting deployment is premature. |

---

## Section 3 — New quality observations

Not defects; things worth knowing.

### Q-1. Coverage is uneven, and the shape is deliberate — **informational**

58% overall hides the distribution:

| Area | Coverage |
|---|---|
| `models/user.py`, `extensions` | 100% |
| `models/billing.py` | 97% |
| `services/servers.py` | 94% (was **15%** before this pass) |
| `config.py` | 88% |
| `services/billing.py` | 78% |
| `services/provisioning.py` | 72% |
| `web/admin.py` | 24% |
| `integrations/*` | 28–58% |

Money and destruction paths are well covered; admin CRUD and outbound HTTP are not. `services/servers.py` at 15% was the worst risk/coverage ratio in the codebase — it deletes customer servers — and is now 94% with 15 tests covering both directions (must delete when due, must *not* delete when the panel fails, when inside grace, or when there's no expiry).

The remaining gaps are mostly thin wrappers over `requests`. Raising them needs an HTTP mocking layer (`responses`/`respx`) — worthwhile, not urgent.

### Q-2. N+1 queries in cart pricing — **Low**
`fluxweb/services/cart.py`, `fluxweb/services/billing.py`

`describe_for_template`, `quote`, and `build_order` each issue one `GamePlan.query.get()` per cart line. Bounded at 20 by `MAX_ITEMS`, so worst case ~40 queries on a cart page — not dangerous, but it is exactly the pattern the architecture review criticised. One `IN` query would collapse it.

### Q-3. Legacy `Query.get()` used 27 times — **Low**

`Model.query.get(id)` is the SQLAlchemy 1.x API. It emits a deprecation warning under 2.0 and is removed in 2.1. Mechanical migration to `db.session.get(Model, id)`.

### Q-4. Rate limits are in-process by default — **Medium in production**

Flask-Limiter falls back to `memory://` without `REDIS_URL`. On Vercel each instance keeps its own counters, so "10 login attempts per 15 minutes" becomes 10 × the number of warm instances. Config warns at boot. Set `REDIS_URL` before launch.

### Q-5. The Werkzeug dev server re-adds a `Server` header — **Informational**

`after_request` pops it, but the WSGI server appends its own afterwards, so `Server: Werkzeug/3.1.6` is visible locally. Irrelevant in production (gunicorn/Vercel), and header-hiding was security theatre in the first place.

---

## Blockers before launch

Ordered. The first three are yours; none can be done from the codebase.

1. **Purge the leaked database from git history.** `instance/flux_tickets.db` at commit `cd7e851` contains **14 real customer emails, 5 `pbkdf2` password hashes, and support-ticket contents**. Untracking does not remove it.
   ```bash
   git filter-repo --path instance/ --invert-paths --force
   ```
   Then force-push, reset passwords for affected accounts, and consider breach-notification duties if the repo was ever public.

2. **Rotate every exposed credential.** Confirmed live and real by `tools/check_keys.py`: Stripe `sk_live_51T…`/`pk_live_51T…` (matched pair, same account), the Pelican admin API key, the Postgres URL, and the Wise token. They sat in a working-tree file next to an auto-push loop for months. Rotate in each provider's dashboard; put the new values in Vercel's environment settings, never in a file.

3. **Supply the production secrets.** The app refuses to boot without them, by design: `SECRET_KEY`, `ENCRYPTION_KEY`, `BASE_URL`, `DATABASE_URL` (pooled), `CRON_SECRET`, `SMTP_HOST`, `STRIPE_WEBHOOK_SECRET`, and — if PayPal is enabled — `PAYPAL_SECRET_KEY` and `PAYPAL_MERCHANT_ID`. Currently `PAYPAL_CLIENT_ID` is set with no secret while `PAYPAL_ENV=sandbox`, which is finding H-12 exactly.

4. **Register the Stripe webhook** at `https://<domain>/webhooks/stripe` for `checkout.session.completed`, and confirm the scheduled job is reaching `/jobs/sync-servers`. Without the first, nothing is ever provisioned. Without the second, nothing ever expires.

5. **Run one end-to-end test purchase** with Stripe test keys before going live, and confirm: order row created, payment row with a unique reference, server provisioned exactly once, webhook replay provisions nothing further.

## Recommended next

- Set `REDIS_URL` (Q-4) — small change, restores real brute-force protection.
- HTTP mocking layer so `integrations/` can be tested (Q-1).
- Frontend performance: lazy loading, image compression, inline-CSS consolidation (P-6, P-7) — the largest remaining user-visible win.
- Cart to a database table (M-23), then CSP nonces (M-29).

## How to reproduce this audit

```bash
.\run.ps1 -Test                                   # 152 tests
.venv\Scripts\python.exe -m pytest --cov=fluxweb  # coverage
.venv\Scripts\python.exe -m pip_audit -r requirements.txt
.venv\Scripts\python.exe -m ruff check fluxweb tests tools app.py
.venv\Scripts\python.exe tools\check_keys.py --file .env.bak
```

CI runs lint, format, types, tests, `pip-audit`, and gitleaks on every push and PR.
