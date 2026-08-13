# FluxWeb

Game server hosting platform — Flask, PostgreSQL, and FluidPanel, with
Stripe and PayPal checkout.

## Quick start

**Windows**

```powershell
.\run.ps1
```

**macOS / Linux / Git Bash**

```bash
./run.sh
```

The script checks for Python 3.11+, creates `.venv`, installs dependencies,
generates a `.env` with fresh secrets, applies migrations, and starts the
server at <http://127.0.0.1:27003>. Re-running it skips whatever is already
done.

You need Python 3.11 or newer. On Windows, the `python.exe` in `WindowsApps` is
a Microsoft Store stub, not an interpreter — the script ignores it and tells
you how to install the real thing:

```powershell
winget install Python.Python.3.12
```

Tick **"Add python.exe to PATH"**, then open a new terminal.

### Other commands

```powershell
.\run.ps1 -Test     # run the test suite
.\run.ps1 -Lint     # ruff + black --check
.\run.ps1 -Fresh    # rebuild the virtualenv
.\run.ps1 -Port 8000
```

```bash
./run.sh --test
./run.sh --lint
./run.sh --fresh
./run.sh --port=8000
```

## Layout

```
app.py                  WSGI entrypoint (Vercel points here)
fluxweb/
  config.py             Validated configuration; refuses to boot when unsafe
  extensions.py         db, migrate, csrf, limiter
  errors.py             Error taxonomy: user-safe vs upstream detail
  money.py              Integer-cent arithmetic
  models/               user, plan, server, billing, content
  security/             Encryption and single-use tokens
  integrations/         fluid.py, pelican.py, pterodactyl.py, mailer.py, payments/
  services/             Domain logic, callable without a request context
  web/                  Blueprints: public, auth, account, cart, checkout,
                        api, admin, checker, webhooks
templates/  static/     Unchanged from before the refactor
tests/                  Payment, auth, routing, and provisioning regressions
```

Services never import from `web/`. Views validate input, call a service, and
render — so the same logic runs from a route, a CLI command, or a test.

## Configuration

Copy `.env.example` to `.env`. Every variable is documented there.

The app **refuses to start** in production when a security-critical value is
missing, left at a known default, or internally inconsistent — for example a
weak `SECRET_KEY`, a live Stripe key paired with sandbox PayPal, or a missing
`STRIPE_WEBHOOK_SECRET`. This is deliberate: each of those was a live finding
in the security audit.

Two independent keys:

- `SECRET_KEY` signs session cookies. Anyone who knows it can forge any
  session, including admin.
- `ENCRYPTION_KEY` encrypts stored panel credentials.

They are separate so either can be rotated without destroying the other.

## Payments

Checkout is server-authoritative end to end:

1. The server prices the cart from the database and freezes an `Order`.
   The browser never supplies an amount.
2. The provider is given the order total.
3. Payment is confirmed server-side — a signature-verified Stripe webhook, or
   a server-side PayPal capture — and the captured amount, currency, and payee
   are checked against the frozen order.
4. Provisioning reads the frozen order and is idempotent: each line records
   when it was fulfilled, so a redelivered webhook cannot provision twice.

`Payment` has a unique constraint on `(provider, provider_ref)`, so a payment
reference can be redeemed exactly once.

### Stripe webhook

Required. Without it payments are never confirmed and nothing is provisioned.

```bash
stripe listen --forward-to localhost:27003/webhooks/stripe
```

Put the printed `whsec_...` in `STRIPE_WEBHOOK_SECRET`. In production, point a
webhook endpoint at `https://<your-domain>/webhooks/stripe` for
`checkout.session.completed`.

If your Stripe account has Managed Payments enabled, set
`STRIPE_PRODUCT_TAX_CODE` too. This app creates Checkout products inline, so
Managed Payments requires a product tax code on the request rather than a
pre-created Stripe Product in the dashboard. Managed Payments also requires a
Stripe API version of `2025-03-31.basil` or newer; the app defaults to that,
and `STRIPE_API_VERSION` can override it if needed.

## Database (PostgreSQL / Supabase)

Storage is PostgreSQL via **SQLAlchemy** (ORM) with **Alembic**, driven by
Flask-Migrate. Schema changes are versioned files in `migrations/versions/`
and are applied as a deploy step — never at runtime.

Local development falls back to SQLite when `DATABASE_URL` is unset, so you can
work without a database. Everything else uses Postgres.

### Supabase setup

Two connection strings, from **Project Settings → Database → Connection string**:

| Variable | Which string | Why |
|---|---|---|
| `DATABASE_URL` | Transaction pooler, port **6543** | Serverless opens many short-lived connections; the pooler absorbs them |
| `DIRECT_URL` | Session pooler port **5432**, or the direct connection | Migrations need a stable session; the transaction pooler gives a different backend per transaction |

The app refuses to start in production if `DATABASE_URL` is a transaction
pooler and `DIRECT_URL` is unset, because migrations would fail intermittently
and confusingly. `sslmode=require` is added automatically for any remote host —
psycopg2 defaults to `prefer`, which silently falls back to plaintext.

Then:

```bash
flask db upgrade     # create the schema
flask check-db       # verify connection, TLS, schema, and lockdown
```

### Supabase exposes `public` — this matters

Supabase publishes the `public` schema through PostgREST, and the `anon` key
that reaches it is *designed* to be embedded in front-end code. Tables created
in the dashboard get Row Level Security switched on for you. **Tables created
by a migration do not.**

Left alone, that would make `user` (emails and password hashes), `payment`, and
`customer_order` readable and writable by anyone with the anon key, with no
application code involved.

Migration `b1a7c4e92f10` closes this with two independent controls:

1. RLS enabled with no policies, so PostgREST resolves zero rows. The app is
   unaffected — it connects as the table owner, and owners bypass RLS.
2. Privileges revoked from `anon` and `authenticated` entirely.

`flask check-db` reports the state of both and tells you what to run if either
is missing. Check it after every schema change that adds a table.

### Migrating existing data

Standard `pg_dump` → `psql`, using the **direct** connection on both ends:

```bash
pg_dump --no-owner --no-privileges --data-only \
        "postgresql://user:pass@old-host:5432/flux_servers" > data.sql
flask db upgrade                       # build the schema on Supabase first
psql "$DIRECT_URL" < data.sql          # then load the data
flask check-db                         # confirm RLS is still on afterwards
```

Load data *after* `flask db upgrade` so the schema and Alembic version table
already exist.

## Authentication (Supabase Auth)

Supabase/GoTrue owns credentials, confirmation emails, password resets, and
provider-side rate limiting. The application keeps its own signed session
cookie after sign-in, so all pages stay server-rendered — no JavaScript in the
auth flow and no JWT in the browser.

The local `user` row survives as a **profile**: it keeps the integer primary
key that `server_record.user_id` and `customer_order.user_id` reference, plus
`is_admin` and the game-panel linkage. `supabase_user_id` links it to the
GoTrue identity. Supabase owns only the credential.

### Setup

From **Project Settings → API**:

```
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_ANON_KEY=<anon public key>
SUPABASE_SERVICE_ROLE_KEY=<service role key>
```

`SUPABASE_SERVICE_ROLE_KEY` bypasses Row Level Security and can act as any
user. It is used only by `create-admin` and the one-off user migration.
**Never expose it to a browser** — the app refuses to start if it is identical
to the anon key.

`AUTH_BACKEND` selects the backend. It defaults to `supabase` whenever
`SUPABASE_URL` and `SUPABASE_ANON_KEY` are both set, and `local` otherwise, so
development works with no Supabase project. **Production requires `supabase`**
and will not boot with the local backend.

### Required: two email template changes

Supabase's default email links return tokens in the URL **fragment**
(`#access_token=…`), which a server never receives — that flow assumes a
JavaScript client. This app is server-rendered, so both templates must use the
`token_hash` form instead.

Under **Authentication → Email Templates**, change the link in each:

**Confirm signup**
```
{{ .SiteURL }}/auth/confirm?token_hash={{ .TokenHash }}&type=email
```

**Reset password**
```
{{ .SiteURL }}/auth/confirm?token_hash={{ .TokenHash }}&type=recovery
```

Then set **Authentication → URL Configuration → Site URL** to your
`BASE_URL`, and add `<BASE_URL>/auth/confirm`, `<BASE_URL>/verify-email`, and
`<BASE_URL>/reset-password` to the redirect allow-list.

Without these changes, signup confirmation and password reset will bounce the
user to a page with no usable token.

### Sign in with Google, Discord, and others

```
SUPABASE_OAUTH_PROVIDERS=google,discord
```

Buttons appear on `/login` and `/register` for each listed provider. Supported:
`google`, `discord`, `github`, `gitlab`, `azure`, `apple`, `twitch`.

Listing one here is only half of it — enable it in **Authentication →
Providers** too, and add its client id/secret from the provider's own console.
A button for a provider that is off in Supabase leads to an error page, which
is why the list is explicit rather than guessed.

Set the callback in the provider's console to Supabase's own URL, **not** this
application's:

```
https://<project-ref>.supabase.co/auth/v1/callback
```

Supabase handles the provider handshake and then returns to
`<BASE_URL>/auth/callback`, which must be in the redirect allow-list under
**Authentication → URL Configuration**.

The flow uses **PKCE**, so the callback arrives as `?code=…` in the query
string and is exchanged for a session server-side. The default implicit flow
returns the session in the URL fragment, which a server never receives — the
same reason the email templates need changing.

An OAuth account has no password anywhere, so `User.can_change_password` is
False for it and the account page shows a note instead of the password form.
The game panel credential is unaffected and still rotates independently.

### Migrating existing accounts

Werkzeug's pbkdf2 hashes cannot be imported into GoTrue (bcrypt/argon2), so
existing users move across with a forced reset — which is wanted anyway, since
those hashes leaked into git history.

```bash
flask migrate-users-to-supabase --dry-run   # report only
flask migrate-users-to-supabase             # create identities + email resets
```

For each account it creates the Supabase identity with a throwaway random
password, clears the local hash, and emails a reset link. Already-migrated
accounts are skipped, so it is safe to re-run. Use `--no-send-reset` to stage
the identities silently and email later.

Create the administrator afterwards — this writes to both Supabase and the
local profile:

```bash
flask create-admin --email you@example.com --password '<strong password>'
```

## Game panel (FluidPanel)

FluidPanel is a Pterodactyl fork and keeps the same `/api/application` and
`/api/client` surface, so a single typed client (`fluxweb/integrations/fluid.py`,
`FluidPanelClient`) serves it.

Two separate credentials, and the difference matters:

| Setting | Scope | Used for |
|---|---|---|
| `FLUID_API_KEY` | **Panel-wide admin** | Creating, suspending, and deleting servers for every customer |

The application key can destroy every server on the panel, which is why the
browser never talks to the panel directly — `/admin/fluid-test` and everything
else call it server-to-server. A request to the panel will never appear in the
browser's network tab, by design.

`FLUID_*` is the preferred prefix; `PANEL_*`, `PTERODACTYL_*` and `PELICAN_*`
are still read in that order so existing deployments keep working.

Check connectivity from the admin dashboard, or:

```bash
curl -s "$BASE_URL/admin/fluid-test"   # as a signed-in admin
```

It reports which host it contacted and distinguishes "could not reach" from
"key rejected", so a failure points at the cause.

## Operations

```bash
flask create-admin --email you@example.com --password '...'
flask check-db                      # connection, TLS, schema, Supabase lockdown
flask sync-servers                  # panel sync, expiry, suspension — run on a schedule
flask retry-order <public_id>       # re-run a failed order; --force unsticks a crashed run
flask db migrate -m "description"   # generate a migration after model changes
flask db upgrade                    # apply migrations (deploy step, never at runtime)
flask db downgrade                  # roll back one revision
```

After adding a model, generate the migration and then **review the generated
file** before committing — autogenerate misses column renames (it emits a drop
plus an add, which loses data) and cannot infer data backfills.

`sync-servers` must run on a schedule (Vercel Cron, or any cron). Expiry and
suspension previously only happened when a customer opened their account page,
so anyone who stopped logging in was hosted indefinitely for free.

## Testing

```bash
./run.sh --test
```

The suite encodes the security invariants — amount verification, replay
protection, order snapshotting, upgrade pricing, open-redirect rejection,
webhook signature enforcement, and the full legacy URL list. A failure there
means a bypass has been reintroduced, not just that a test is stale.

It runs on in-memory SQLite by default. Production is PostgreSQL, and the
dialects differ (reserved words, constraint enforcement, `UPDATE … WHERE …
IN (…)` semantics), so the same suite can be pointed at a real database:

```bash
docker run -d --name fluxpg -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=fluxweb_test -p 55432:5432 postgres:16
TEST_DATABASE_URL=postgresql://postgres:pw@localhost:55432/fluxweb_test pytest
```

Seven tests only run there — reserved-word quoting, the atomic provisioning
claim, database-level payment uniqueness, and the RLS lockdown. CI runs the
suite both ways and also applies migrations up, down, and up again against a
real PostgreSQL service.

## Deployment

Vercel builds `app.py`. Set every variable from `.env.example` in the project's
environment settings — never in a file.

Use a **pooled** `DATABASE_URL` (PgBouncer, Neon, or Supabase pooler).
Serverless runs many short-lived instances, and a per-instance pool multiplies
into connection exhaustion; the app uses `NullPool` and expects the pooler to
own pooling.

Set `REDIS_URL` so rate limits are shared across instances. Without it they
live in per-instance memory and brute-force protection is weak.
