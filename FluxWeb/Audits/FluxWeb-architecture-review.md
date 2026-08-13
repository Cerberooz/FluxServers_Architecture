# FluxWeb — Coding Convention & Architecture Review

**Scope:** structure, conventions, and design of the repo at `cd7e851`. Companion to the security/bug audit — individual vulnerabilities are *not* repeated here; this report is about **the structure that keeps producing them**.

**Shape of the codebase:**

| Metric | Value |
|---|---|
| `app.py` | 1,950 lines, 56 routes, 11 models, all in one module |
| Blueprints | 1 (`checker.py`, 55 lines — a public JSON validator) |
| Admin routes inside `app.py` | 21 |
| Raw `requests.*` calls to the panel | 30, across 15 duplicated config lookups |
| `db.session.commit()` calls | 36 (helper `db_session_commit()` exists, used **once**) |
| Logging | 45 × `app.logger` + 13 × `print()` |
| Exception handlers | 7 bare `except:` + 38 `except Exception`, most swallowing |
| Function-local imports | 10 (`json` ×4, `base64` ×2, `random`, `Response`, `HTTPBasicAuth`) |
| Templates | 28 files / 7,705 lines; 6 orphaned; 4 don't extend `base.html` |
| Inline `<style>` in templates | ~2,900 lines, against a 2,668-line `style.css` |
| DB indexes beyond PK/unique | **0** |
| Tests / CI / linting / type hints / migrations | none |

**Overall:** this is a working prototype with production credentials pointed at it. The functionality is genuinely there — panel provisioning, upgrades, coupons, two payment providers — but every layer is fused into one file with no seams, so nothing can be tested, cached, retried, or reasoned about in isolation. The single highest-leverage change is not any individual fix; it is **introducing layers** (§6).

---

## 1. Architecture as it stands

```
                 ┌──────────────────────────────────────────────┐
Browser ────────▶│ app.py (1,950 lines)                         │
  │              │  routes + models + payments + panel client   │──▶ Pelican Panel API
  │              │  + admin + auth + provisioning + templates   │──▶ PayPal / Stripe
  │              └──────────────────────────────────────────────┘
  │                        │                    │
  │                        ▼                    ▼
  │                    Postgres            signed cookie
  │                  (no indexes)      (cart, coupon, temp state)
  └── 14 MB of static assets, 2 unpinned CDNs, no SRI
```

Everything is a Flask view function that talks directly to SQLAlchemy, `requests`, and the payment SDKs. There is no service layer, no repository/DAO, no client abstraction, no domain model separate from the ORM model, no background worker, and no cache. The cookie is used as an application database.

### The five structural problems

1. **No layering.** Business rules (what a renewal costs, when a server expires, whether an upgrade is legal) live inside HTTP handlers, interleaved with `request.form.get()` and `render_template()`. They can't be unit-tested, reused between the PayPal path and the Stripe path, or called from a cron job — which is exactly why `/checkout` and `/stripe-success` have *different* bugs despite doing the same job (`app.py:1403` vs `app.py:1479`).
2. **The panel client is copy-paste.** `get_pelican_config()` is called 15 times and its result fed to 30 hand-written `requests` calls, each with its own ad-hoc timeout (3s, 5s, 10s, 15s), its own status-code interpretation, and its own `try/except` that usually swallows. There is no retry, no backoff, no circuit breaker, no shared `requests.Session` (so **every call pays a fresh TCP + TLS handshake**), and no typed response.
3. **The session cookie is the database.** Cart, coupon, `temp_server_name`, `temp_location_id`, and auth all live in one signed cookie. This is why cart integrity depends entirely on `SECRET_KEY`, why carts vanish past ~4 KB, and why the Stripe charge can't be reconciled against what ships.
4. **No background execution.** Expiry, suspension, and deletion of servers run **inside the `/account` page view** (`app.py:904-993`). A customer who never logs in is never suspended and never billed correctly — a direct revenue and capacity leak — while a customer who does log in pays a multi-second page load for the privilege.
5. **State-changing logic is duplicated per entry point.** Provisioning exists in `provision_servers_from_cart`, again in `admin_user_provision` (`app.py:1515`), and cart mutation exists in both `main.js` and `cart.html` with two independent `removeFromCart` implementations (`static/js/main.js:260` and `templates/cart.html:483`).

---

## 2. Security-relevant architecture

*(patterns, not individual CVEs — see the security audit for those)*

### S-1. Trust boundaries are not expressed anywhere — **High**
There is no place in the code where "untrusted input" becomes "validated domain object". `request.form.get()` results are cast inline (`int(request.form.get('memory', 1024))`) and passed straight into ORM constructors and outbound API payloads. There is no schema validation layer (no Pydantic, no WTForms `Form` classes despite Flask-WTF being installed — it's used **only** for CSRF). Consequences: every route re-invents validation, and most skip it. Adopt request schemas at the edge; make handlers accept validated objects only.

### S-2. Authorisation is ad-hoc and repeated — **High**
Ownership checks are hand-written per route:
```python
server_rec = ServerRecord.query.filter_by(pelican_server_identifier=identifier, user_id=session['user_id']).first()
```
repeated at `app.py:1000`, `1027`, `1049`, with variants at `1183`, `1202`, `1226`. Admin is a single decorator comparing an email string (`app.py:391`). There is no role model, no policy object, no "get this resource *for this user* or 404" helper. Each new route is a fresh chance to forget the check — and `admin_suspend_server`/`admin_delete_server` (`app.py:1542`, `1561`) already take a *panel* id directly with no mapping through ownership at all. Centralise into `get_owned_server(user, identifier)` and a real permission model.

### S-3. Secrets are read at import time, scattered, and unvalidated — **High**
13 `os.getenv()` calls at module scope (`app.py:24-62`, `169-170`) with insecure fallbacks (`'flux_dev_key_change_me_in_production'`, `'changeme'`, `'sb'`). Nothing validates that the set is coherent — which is why PayPal is currently half-configured (live client id, sandbox API base, no secret) and Stripe is live at the same time. Replace with a single validated `Config` object that fails fast at boot when a required secret is missing, is a known-default, or when providers disagree about live/test mode.

### S-4. Error handling leaks upstream detail to end users — **Medium**
`errors.append(f"{plan.name}: {error}")` where `error` is `f"Panel Error ({resp.status_code}): {resp.text}"` (`app.py:1378`, `1795`), flashed straight to the browser (`app.py:1440`). Raw panel responses — internal hostnames, node names, stack detail — reach customers. There is no error taxonomy: user-facing messages, operator diagnostics, and upstream payloads are the same string. Define `DomainError` (safe to show) vs `IntegrationError` (logged, generic message shown).

### S-5. Two logging systems, neither structured — **Medium**
45 `app.logger` calls, 13 `print()` (`app.py:72`, `117`, `137`, `503`, `552`, `942`, `1094`…). `print()` output is lost or unsearchable on Vercel. Several log lines include secrets-adjacent data (full panel URLs, emails at `app.py:1595`, panel error bodies). No request ids, no correlation between a payment and its provisioning attempt. Standardise on structured logging (`structlog`/JSON) + Sentry, and add a redaction filter.

### S-6. Swallowed exceptions hide security failures — **Medium**
7 bare `except:` and 38 broad `except Exception`, the majority ending in `pass` or a `print`. `app.py:985-986` wraps the entire per-server sync in `except: pass`, so a panel returning 403 (auth revoked) is indistinguishable from success. Failures that should page someone are invisible. Catch specific exceptions; let unexpected ones reach the error handler and the tracker.

### S-7. Frontend supply chain is unpinned and unverified — **Medium**
`base.html` loads `cdnjs.cloudflare.com` (Font Awesome) and `unpkg.com` (AOS) with **no `integrity` attribute** anywhere in the repo, and `cart.html` — the page that handles card entry — inherits both plus the Stripe and PayPal SDKs. A compromised unpkg package executes script on your checkout page. Combined with a CSP that allows `'unsafe-inline'`, `'unsafe-eval'`, and bare `https:` (`app.py:267-274`), there is no second line of defence. Self-host or pin with SRI; this also affects which PCI SAQ tier you fall into.

### S-8. No audit trail — **Medium**
No record of admin actions, no payment ledger, no login history, no immutable log of provisioning. When something goes wrong with money or a deleted server, there is nothing to reconstruct it from. This is an architectural gap (missing append-only event log), not a missing feature.

---

## 3. Performance

### P-1. `/account` is a synchronous fan-out — **High**
`app.py:904-993` per page load, **per server**: `GET /servers/{id}` → `GET /servers/{id}?include=allocations` → `GET /nodes/{id}` (+ conditional suspend/delete calls), each opening a new TLS connection, with `db.session.commit()` **inside** the loop. Five servers ≈ 15+ sequential round-trips; at Vercel's 10s function limit this page times out for any real customer. Sync in a background job; render from the DB; refresh live stats via the existing AJAX endpoints.

### P-2. Admin dashboard loads the entire database — **High**
`app.py:410-442` issues 9 unbounded `.all()` queries — every user, every server, every plan, every FAQ, coupon, location — plus 2 blocking panel API calls, then renders all of it into one 530-line page. No pagination, no `LIMIT`, no lazy tabs. This is fine at 14 users and fatal at 5,000.

### P-3. Zero indexes on the columns actually queried — **High**
The only indexes are primary keys and three `unique=True` columns. Meanwhile the hot queries are:
- `ServerRecord.user_id` + `status` (`app.py:909`) — every account page
- `ServerRecord.pelican_server_identifier` + `user_id` (`app.py:1000`, `1027`, `1049`) — every stats poll, i.e. every few seconds per open browser tab
- `ServerRecord.pelican_server_id` (`app.py:1547`, `1568`)
- `GamePlan.game` + `serial_number` (five separate page routes)
- `Announcement.active` — **every rendered page**, via the context processor

All full scans. Add composite indexes: `(user_id, status)`, `(pelican_server_identifier, user_id)`, `(game, serial_number)`, `(active)`.

### P-4. Base64 images in the database — **High**
`GamePlan.image_url` is a `Text` column holding a full `data:` URI (`app.py:507-528`, `697-710`). Every plan listing (`/`, `/minecraft`, `/hytale`, `/dedicated`, `/discord-bots`, `/cart`, admin) pulls megabytes of base64 out of Postgres, ships it inline in the HTML — where it is **uncacheable, un-CDN-able, and 33% larger than the original** — and the HTML itself is served `no-store` (`app.py:263`). A 500 KB plan image is re-downloaded on every page view by every visitor. Move to object storage / Vercel Blob and store a URL.

### P-5. No caching anywhere — **Medium**
Plans, FAQs, locations, service status, and globe locations change maybe weekly and are re-queried on every request. The context processor adds an `Announcement` query to **every single rendered page** (`app.py:1802-1812`). `get_pelican_locations()` hits the panel live on every `/api/locations` call. Add a short-TTL cache (Redis, or `@lru_cache` with TTL for panel metadata) and cache-control on semi-static JSON.

### P-6. 14 MB of unoptimised static assets, no lazy loading — **Medium**
`earth-blue-marble.jpg` 1.4 MB, `light-text_.gif` 1.2 MB, `infrastructure.png` 843 KB, `seotag.png` 801 KB, `network_map.png` 782 KB, plus 250+ SVG flags. **Zero `loading="lazy"` attributes in the entire template tree**, no `srcset`, no `width`/`height` (so guaranteed layout shift), PNGs where WebP/AVIF belong, and an animated GIF where a video would be a tenth the size. Also `globe.gl.min.js` is vendored and loaded on the homepage. This is the single biggest lever on perceived speed and Core Web Vitals.

### P-7. ~2,900 lines of inline CSS bypass the CDN — **Medium**
21 of 28 templates carry their own `<style>` block (`cart.html` 683 lines, `index.html` 410, `dedicated.html` 307) while `style.css` — the one file that *is* cached for a year — sits at 2,668 lines. Because HTML is served `no-store`, that CSS is re-downloaded on every navigation and can never be cached. Consolidate into `style.css` + per-page files.

### P-8. No connection reuse to the panel — **Low/Medium**
30 module-level `requests.get/post/...` calls, no `requests.Session`, no `HTTPAdapter` pool. Each is a fresh handshake to the same host. A single shared session in a `PelicanClient` class removes most of the latency in P-1 for free.

---

## 4. Scalability

### SC-1. Serverless connection maths don't work — **High**
`pool_size: 2, max_overflow: 3` (`app.py:179-185`) is *per Lambda instance*. Vercel will happily run 100 concurrent instances; that's up to 500 Postgres connections against a default limit of ~100. The pool is also useless in a model where instances are frozen between invocations. Use a connection pooler (PgBouncer / Neon or Supabase pooled endpoint) and set `poolclass=NullPool`.

### SC-2. Schema creation on the request path — **High**
`db.create_all()` + hand-rolled `ALTER TABLE` run inside `@app.before_request` behind a module-global flag (`app.py:1873-1909`). Every cold start races to create tables and seed rows; concurrent cold starts race each other; the "migration" only knows three columns and will silently diverge from the models forever after. Move to Alembic, run in a deploy step, and let the app fail if the schema is behind.

### SC-3. No background job infrastructure — **High**
Expiry, suspension, auto-deletion, and panel status sync are all triggered by a user visiting `/account`. There is no scheduler, no queue, no worker. Consequences: unvisited accounts never expire (you keep hosting unpaid servers); provisioning failures after payment are never retried; nothing can be made idempotent or observable. Introduce a queue (or at minimum Vercel Cron hitting an authenticated internal endpoint) and move all of it there.

### SC-4. Provisioning has no concurrency control — **Medium**
Allocation selection (`app.py:1643-1686`) is read-then-use with no locking, and the fallback picks a random port in a 435-port range with no collision check. Two simultaneous purchases can select the same allocation. There is also no idempotency key on provisioning, so a double-submitted checkout provisions twice. Needs `SELECT … FOR UPDATE` or a panel-side atomic allocation, plus idempotency keys.

### SC-5. Cookie-based state caps the product — **Medium**
Cart size is bounded by the 4 KB cookie limit; sessions can't be revoked, listed, or migrated; and nothing about a user's state is queryable server-side (you cannot answer "how many people have an abandoned cart?"). Move cart and sessions server-side.

### SC-6. The monolith blocks horizontal specialisation — **Medium**
Because everything is one module with one dependency set, you cannot scale the panel-sync workload separately from web serving, cannot deploy an admin surface on a restricted network, and cannot put the webhook receiver on a different reliability tier from the marketing pages. Blueprints (§6) are the prerequisite for all three.

### SC-7. Static assets served through the app in local/non-Vercel deploys — **Low**
`vercel.json` routes `/static/*` to the static builder, but the Flask `after_request` also sets 1-year cache headers for `/static/` (`app.py:259-260`), implying Flask serves them in some environments. Flask's static handler should never serve 14 MB of assets in production.

---

## 5. Maintainability & coding conventions

### M-1. One 1,950-line module — **High**
Models, config, panel client, payments, admin, auth, and provisioning share a namespace. Route ordering is arbitrary (admin routes at line 408, core routes at 836, auth at 1827, admin again at 1911). Reading any flow requires jumping between four distant regions. The one blueprint that exists (`checker.py`) is for a trivial public JSON validator — the opposite of what should have been extracted.

### M-2. Inconsistent naming across three generations of the product — **High**
`pelican` / `pterodactyl` / `ptero` all appear as prefixes; env vars support both (`PELICAN_URL or PTERODACTYL_URL`); the committed DB has `ptero_server_id` while the model has `pelican_server_id`. Worse, the domain vocabulary is actively wrong:
- `GamePlan.location_id` holds a **node** id (`node_id = int(final_location_id)`, `app.py:1641`)
- `GamePlan.nest_id` is a `String` holding a **tag**, and `get_pelican_nests()` fabricates fake nest objects out of egg tags (`app.py:99-118`)

Anyone new — including you in six months — will read `location_id` and be wrong. Pick one vendor name, rename to what the fields actually are, and put the compatibility shim in one adapter.

### M-3. Dead code, dead abstractions, dead templates — **Medium**
- `db_session_commit()` defined as the resiliency helper and used **once** out of 37 commit sites (`app.py:66-73`)
- `get_pelican_egg_variables()` never called
- 6 orphaned templates: `admin/dashboard.html`, `auth/admin_login.html`, `errors/404.html`, `errors/500.html`, `pages/pricing.html`, `services/game-servers.html`
- `temp_test.py` — committed and **not valid Python** (`r = c.get(/)`); breaks `compileall`/pytest collection
- `check_db.py` — a debug script in the repo root
- `GamePlan.feature1..feature4` — superseded by `features` JSON, still in the schema, still written as `''` on every insert (`app.py:642-645`, `727-730`)
- `git-push.bat` — a 60-second auto-commit loop

### M-4. Configuration duplicated and interleaved with code — **Medium**
`SESSION_COOKIE_HTTPONLY`, `SESSION_COOKIE_SECURE`, and `SESSION_COOKIE_SAMESITE` are each set **twice**, verbatim (`app.py:188-190` and `195-197`), separated by an unrelated constant. `@app.teardown_appcontext` is registered at line 206 referencing `db`, which isn't defined until line 212. Config belongs in a `config.py` with `Development`/`Production` classes.

### M-5. Function-local imports as a convention — **Medium**
`import json` appears inside four different functions, `import base64` inside two (while `base64` is *already* imported at module top, line 5), plus `random`, `Response`, and `HTTPBasicAuth`. This hides the dependency surface and is a habit worth breaking outright — all imports at the top, enforced by a linter.

### M-6. No validation layer, no forms — **Medium**
Flask-WTF is a dependency but only `CSRFProtect` is used; not one `FlaskForm` exists. Every handler does `int(request.form.get('x', default))` inline — 20+ times in the admin routes alone — with no error handling, so a non-numeric field is a 500. Field defaults are also duplicated between `admin_add_plan` and `admin_edit_plan` and can drift.

### M-7. Templates duplicate structure instead of composing — **Medium**
`admin/admin.html` (530 lines) and `checker.html` don't extend `base.html`; they re-declare the whole HTML shell, so nav/CSP/meta changes must be made in multiple places. The four service pages (`minecraft`, `hytale`, `dedicated`, `discord_bots`) render near-identical plan-card markup with no shared macro. `cart.html` at 1,342 lines mixes markup, 683 lines of CSS, and three script blocks including the entire payment integration. Extract Jinja macros (`plan_card`, `price_row`) and move page JS to `static/js/`.

### M-8. No tests, no CI, no tooling — **High** (as a compounding factor)
No test directory, no `pytest`, no linter (`ruff`/`flake8`), no formatter (`black`), no type hints anywhere, no pre-commit hooks, no CI workflow, no dependency scanning, no `README`, no architecture notes. `requirements.txt` is a flat pinned list with no dev/prod split and no lockfile. For a codebase about to handle money, the absence of a single test over the checkout path is the highest-risk item in this section — every fix from the security audit will be applied blind.

### M-9. Naming collision between Flask `session` and payment sessions — **Low**
`stripe_success` juggles Flask's `session`, `checkout_session`, and `session_id` in 30 lines (`app.py:1479-1511`), and `session.pop('cart')` sits three lines from `checkout_session.payment_status`. Rename to `flask_session`/`stripe_session` or import as `from flask import session as user_session`.

### M-10. Magic numbers and hardcoded business rules — **Low/Medium**
Egg ids `232`/`314` hardcoded in provisioning (`app.py:1309-1311`, `693`), location `4` hardcoded as "US Oregon" for Discord bots (`app.py:1316`), `io: 500` and `swap: 0` repeated in two payloads, port range `25565-26000`, `EXPIRY_DAYS = 30`, the 7-day deletion grace period inline at `app.py:936`. These are product decisions buried in code — move to config/DB.

---

## 6. Target architecture

Not a rewrite — an extraction, done in the order below. Each step is independently shippable.

```
fluxweb/
  __init__.py          app factory: create_app(config) — no import-time side effects
  config.py            validated Config classes; fail fast on missing/default secrets
  extensions.py        db, csrf, limiter, cache, migrate
  models/              user.py, server.py, plan.py, order.py, content.py
  schemas/             request validation (Pydantic / WTForms) — the trust boundary
  services/            ← the layer that does not exist today
    provisioning.py    create/upgrade/renew/suspend — pure domain, unit-testable
    billing.py         cart totals, coupons, orders — one implementation, both providers
    accounts.py        registration, verification, password reset
  integrations/
    pelican.py         PelicanClient: one requests.Session, retries, backoff,
                       timeouts, typed responses, one place that knows the panel
    payments/          stripe.py, paypal.py behind a common PaymentProvider interface
  web/                 blueprints: public, auth, account, cart, admin, api, webhooks
  jobs/                sync_servers, expire_servers, retry_provisioning
  templates/  static/
migrations/            Alembic
tests/                 unit (services) + integration (checkout, provisioning)
```

**Migration order** — each step makes the next cheaper:

1. **`config.py` + app factory.** Kills import-time side effects, makes tests possible at all, and gives you the fail-fast secret validation from S-3. *~half a day.*
2. **`integrations/pelican.py`.** Collapse 30 scattered calls into one client with a shared session, uniform timeouts, retries, and typed errors. Immediately fixes P-8 and a chunk of P-1, and gives you one place to mock in tests. *~1 day.*
3. **`services/billing.py` + `Order`/`Payment` models + Alembic.** This is where the security audit's payment rework lands; do it *after* step 2 so both providers share one implementation. *~2-3 days.*
4. **Blueprints + `schemas/`.** Split the 56 routes; admin becomes independently deployable/restrictable. Validation at the edge closes S-1 and M-6. *~2 days.*
5. **`jobs/` + cron.** Move expiry/sync out of `/account`. Fixes P-1 and SC-3 together. *~1 day.*
6. **Indexes, caching, asset pipeline.** P-3 through P-7 — mostly mechanical once the layers exist.

Steps 1-3 are the ones worth doing before launch; 4-6 can follow.

---

## 7. Conventions to adopt

Concrete rules, enforceable by tooling rather than discipline:

**Tooling (set up first — half a day, pays for itself immediately)**
```
ruff          lint + import sorting  (bans function-local imports, bare except, unused code)
black         formatting
mypy          type hints on services/ and integrations/ at minimum
pytest        tests/ — start with checkout + provisioning
pip-audit     dependency CVEs
gitleaks      pre-commit secret scan  (would have caught the committed .db)
```
Wire all six into a GitHub Actions workflow on PR. Add a `.gitignore` covering `instance/`, `*.db`, `.venv/`, `*.pyc`.

**Code rules**
- All imports at module top. No `import json` inside a function.
- No bare `except:`. Catch specific exceptions; re-raise what you can't handle.
- One logging system: `app.logger` / `structlog`, never `print()`. Structured fields, no secrets, redaction filter.
- Views do three things: validate input → call a service → render. No `requests` calls, no business rules, no more than ~30 lines.
- Every write path goes through a service function that is callable without a request context (so a job can call it too).
- Money as integer cents or `Decimal`, never `float`.
- One commit per logical transaction, at the service boundary — not 36 scattered `db.session.commit()` calls.
- Every user-facing string that includes upstream data gets sanitised through the error taxonomy (S-4).
- Type-hint every service and integration function signature.

**Naming**
- Pick `pelican` and rename every `ptero*` occurrence, including DB columns, in one migration.
- Rename fields to what they hold: `location_id` → `node_id`, `nest_id` → `egg_tag`.
- Models singular (`User`, `ServerRecord` → `Server`); route functions `verb_noun`; templates mirror blueprint names.

**Templates**
- Every template extends `base.html`. No exceptions — fix `admin/admin.html` and `checker.html`.
- No `<style>` blocks; page CSS goes to `static/css/pages/*.css`.
- No `<script>` blocks longer than ~10 lines; page JS goes to `static/js/pages/*.js`.
- Repeated markup becomes a macro in `templates/macros/`.
- `loading="lazy"` + explicit `width`/`height` on every non-hero `<img>`; SRI on every external asset.
- Delete the 6 orphaned templates.

**Repo hygiene**
- Delete `temp_test.py`, `check_db.py`, `git-push.bat`.
- Add a `README.md`: how to run locally, required env vars (names only), deploy process.
- Split `requirements.txt` into `requirements.txt` / `requirements-dev.txt`, or move to `pyproject.toml` + a lockfile.
- Conventional commits — the current history is a single `Init:` commit, so this is a clean slate to start on.

---

## Priority summary

| Priority | Items | Why now |
|---|---|---|
| **Before launch** | M-8 (tests/CI), §6 steps 1-3, S-3, SC-1, SC-2, P-3 | Every security fix will be applied blind without tests; connection exhaustion and request-path migrations break on the first traffic spike; indexes are a 30-minute change with an outsized effect |
| **First month** | §6 steps 4-5, P-1, P-2, P-4, S-1, S-2, SC-3, SC-4 | These are what break between 10 and 1,000 customers |
| **Ongoing** | P-5 → P-8, M-1 → M-7, M-9, M-10, S-5 → S-8 | Compounding maintainability; cheapest to do alongside the extractions above |
