"""Flux Servers web application.

Application factory. Nothing here runs at import time except imports, so the
module can be loaded by tests, CLI commands, and WSGI servers alike.
"""

from __future__ import annotations

import logging
import os
import sys

from flask import Flask, jsonify, render_template, request
from werkzeug.middleware.proxy_fix import ProxyFix

from fluxweb.config import Config, ConfigError
from fluxweb.errors import FluxError
from fluxweb.extensions import csrf, db, limiter, migrate

__version__ = "2.0.0"

# Templates and static files stay at the repository root so the existing
# template tree is untouched by the package split.
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

log = logging.getLogger(__name__)


def create_app(config: Config | None = None) -> Flask:
    app = Flask(
        __name__,
        template_folder=os.path.join(_ROOT, "templates"),
        static_folder=os.path.join(_ROOT, "static"),
    )

    if config is None:
        try:
            config = Config.from_env()
        except ConfigError as exc:
            # Fail loudly and immediately rather than booting insecurely.
            print(f"\n{exc}\n", file=sys.stderr)
            raise

    app.config.update(config.as_flask_config())
    app.extensions["flux_config"] = config

    _configure_logging(app, config)
    for warning in config.warnings:
        app.logger.warning(warning)

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    limiter.init_app(app)

    from fluxweb.cache import init_runtime_cache

    init_runtime_cache(app)

    # Import models so Alembic autogenerate and create_all see them.
    from fluxweb import models  # noqa: F401
    from fluxweb.web import BLUEPRINTS

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    _register_context(app, config)
    _register_error_handlers(app)
    _register_security_headers(app)
    _register_cli(app)

    return app


def _configure_logging(app: Flask, config: Config) -> None:
    level = logging.DEBUG if config.is_development else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(handler)
    root.setLevel(level)
    app.logger.setLevel(level)


def _register_context(app: Flask, config: Config) -> None:
    from fluxweb.models import Announcement
    from fluxweb.web.helpers import current_user, is_admin

    @app.context_processor
    def inject_globals() -> dict:
        announcement = None
        try:
            announcement = Announcement.query.filter_by(active=True).first()
        except Exception:  # noqa: BLE001 - a DB blip must not blank every page
            db.session.rollback()
            app.logger.exception("Could not load announcement")

        from fluxweb.web.auth import PROVIDER_LABELS

        # Only providers that are BOTH listed in config and known to us get a
        # button. A button for a provider that is off in Supabase would send
        # the customer to an error page.
        oauth_buttons = [
            {
                "id": name,
                "label": PROVIDER_LABELS[name][0],
                "icon": PROVIDER_LABELS[name][1],
                "background": PROVIDER_LABELS[name][2],
                "colour": PROVIDER_LABELS[name][3],
            }
            for name in config.oauth_providers
            if name in PROVIDER_LABELS
        ]

        user = current_user()
        return {
            "oauth_buttons": oauth_buttons,
            "current_user": user,
            "is_admin": is_admin(user),
            "site_announcement": announcement,
            "admin_email": config.admin_email,
            "EXPIRY_DAYS": config.expiry_days,
            "paypal_client_id": config.payments.paypal_client_id,
            "paypal_enabled": config.payments.paypal_enabled,
            "stripe_key": config.payments.stripe_publishable_key,
            "stripe_enabled": config.payments.stripe_enabled,
            "panel_url": config.panel_url or "",
        }

    @app.teardown_appcontext
    def remove_session(exception: BaseException | None = None) -> None:
        if exception is not None:
            db.session.rollback()
        db.session.remove()


def _register_error_handlers(app: Flask) -> None:
    def _wants_json() -> bool:
        return request.path.startswith(("/api/", "/webhooks/")) or request.is_json

    @app.errorhandler(FluxError)
    def handle_flux_error(exc: FluxError):
        app.logger.warning("Domain error on %s: %s", request.path, exc)
        if _wants_json():
            return jsonify({"status": "error", "message": exc.user_message}), 400
        return (
            render_template(
                "errors/error.html", code=400, title="Something went wrong", message=exc.user_message
            ),
            400,
        )

    @app.errorhandler(404)
    def not_found(_error):
        if _wants_json():
            return jsonify({"status": "error", "message": "Not found"}), 404
        return (
            render_template(
                "errors/error.html",
                code=404,
                title="Page Not Found",
                message="The page you're looking for doesn't exist or has been moved.",
            ),
            404,
        )

    @app.errorhandler(413)
    def too_large(_error):
        message = "That upload is too large."
        if _wants_json():
            return jsonify({"status": "error", "message": message}), 413
        return render_template("errors/error.html", code=413, title="File Too Large", message=message), 413

    @app.errorhandler(429)
    def rate_limited(_error):
        message = "Too many requests. Please slow down and try again shortly."
        if _wants_json():
            return jsonify({"status": "error", "message": message}), 429
        return render_template("errors/error.html", code=429, title="Slow Down", message=message), 429

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        app.logger.exception("Unhandled error on %s", request.path)
        if _wants_json():
            return jsonify({"status": "error", "message": "Internal server error"}), 500
        return (
            render_template(
                "errors/error.html",
                code=500,
                title="Internal Server Error",
                message="Something went wrong on our end. Please try again later.",
            ),
            500,
        )

    # Catch-all only in production. In development and tests, let unexpected
    # exceptions propagate so the traceback is visible instead of being
    # flattened into a generic 500.
    config: Config = app.extensions["flux_config"]
    if config.is_production:
        app.register_error_handler(Exception, internal_error)


def _register_security_headers(app: Flask) -> None:
    config: Config = app.extensions["flux_config"]

    @app.after_request
    def security_headers(response):
        response.headers.pop("Server", None)
        response.headers.pop("X-Powered-By", None)

        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=(), payment=(self)"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"

        if not config.is_development:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        if request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif response.mimetype == "text/html":
            response.headers["Cache-Control"] = "no-store, max-age=0"

        # Still permissive because the templates carry inline styles and
        # scripts; tightening to nonces is tracked as audit M-29.
        response.headers["Content-Security-Policy"] = "; ".join(
            [
                "default-src 'self'",
                "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://js.stripe.com "
                "https://www.paypal.com https://www.paypalobjects.com https://unpkg.com "
                "https://cdnjs.cloudflare.com",
                "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://unpkg.com",
                "img-src 'self' data: https:",
                "font-src 'self' data: https://cdnjs.cloudflare.com",
                "connect-src 'self' https://api.stripe.com https://www.paypal.com wss: ws:",
                "frame-src https://js.stripe.com https://www.paypal.com",
                "frame-ancestors 'self'",
                "base-uri 'self'",
                "form-action 'self'",
                "object-src 'none'",
            ]
        )
        return response


def _redact_url(url: str) -> str:
    """Render a database URL with the password removed, for safe printing."""
    from urllib.parse import urlparse, urlunparse

    if not url:
        return "(unset)"
    try:
        parsed = urlparse(url)
    except ValueError:
        return "(unparseable)"
    if not parsed.password:
        return url
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    netloc = f"{parsed.username}:***@{host}" if parsed.username else host
    return urlunparse(parsed._replace(netloc=netloc))


def _register_cli(app: Flask) -> None:
    """CLI commands. Schema work happens here, never on the request path."""
    import click
    import sqlite3
    from pathlib import Path

    from fluxweb.models import User

    @app.cli.command("init-db")
    def init_db() -> None:
        """Create tables directly. Development convenience only."""
        db.create_all()
        click.echo("Tables created. Use 'flask db upgrade' for production schema changes.")

    @app.cli.command("check-db")
    def check_db() -> None:
        """Verify the database connection, TLS, and Supabase lockdown."""
        from sqlalchemy import text

        # Derived from the ORM metadata rather than hardcoded, so a new model
        # is covered by this check automatically.
        app_tables = sorted(db.metadata.tables.keys()) + ["alembic_version"]

        config: Config = app.extensions["flux_config"]
        click.echo(f"URL (runtime)  : {_redact_url(config.database_url)}")
        click.echo(f"URL (migrations): {_redact_url(config.migration_url)}")

        if not config.is_postgres:
            click.echo("Backend        : SQLite (development). Nothing further to check.")
            return

        with db.engine.connect() as conn:
            version = conn.execute(text("SHOW server_version")).scalar()
            database = conn.execute(text("SELECT current_database()")).scalar()
            user_name = conn.execute(text("SELECT current_user")).scalar()
            click.echo(f"Server         : PostgreSQL {version}")
            click.echo(f"Database/user  : {database} / {user_name}")

            ssl_used = conn.execute(text("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")).scalar()
            click.echo(f"TLS            : {'yes' if ssl_used else 'NO — traffic is in the clear'}")

            missing_tables = [
                name
                for name in app_tables
                if conn.execute(text("SELECT to_regclass(:t)"), {"t": f"public.{name}"}).scalar() is None
            ]
            if missing_tables:
                click.echo(
                    f"Schema         : MISSING {len(missing_tables)} table(s): {', '.join(missing_tables)}"
                )
                click.echo("                 Run: flask db upgrade")
                return
            click.echo(f"Schema         : all {len(app_tables)} tables present")

            unprotected = (
                conn.execute(
                    text(
                        "SELECT relname FROM pg_class "
                        "WHERE relnamespace = 'public'::regnamespace "
                        "AND relkind = 'r' AND relrowsecurity = false "
                        "AND relname = ANY(:names) ORDER BY relname"
                    ),
                    {"names": list(app_tables)},
                )
                .scalars()
                .all()
            )

            exposed = (
                conn.execute(
                    text(
                        "SELECT DISTINCT table_name FROM information_schema.role_table_grants "
                        "WHERE table_schema = 'public' AND grantee IN ('anon','authenticated') "
                        "AND table_name = ANY(:names) ORDER BY table_name"
                    ),
                    {"names": list(app_tables)},
                )
                .scalars()
                .all()
            )

            if unprotected:
                click.secho(
                    f"RLS            : OFF on {len(unprotected)} table(s): {', '.join(unprotected)}",
                    fg="red",
                )
            else:
                click.secho("RLS            : enabled on all application tables", fg="green")

            if exposed:
                click.secho(
                    f"REST exposure  : anon/authenticated still hold grants on: {', '.join(exposed)}",
                    fg="red",
                )
                click.echo("                 Run: flask db upgrade   (migration b1a7c4e92f10)")
            else:
                click.secho("REST exposure  : no grants to anon/authenticated", fg="green")

    @app.cli.command("create-admin")
    @click.option("--email", required=True)
    @click.option("--password", required=True)
    @click.option("--username", default="Admin")
    def create_admin(email: str, password: str, username: str) -> None:
        """Create or promote an administrator."""
        from fluxweb.services import accounts

        email = email.strip().lower()
        accounts.validate_password(password)

        config: Config = app.extensions["flux_config"]
        user = User.query.filter_by(email=email).first()

        if config.uses_supabase_auth:
            # The credential must exist in Supabase, or this admin cannot sign
            # in. Created pre-confirmed so there is no chicken-and-egg on a
            # fresh deploy.
            from fluxweb.integrations.supabase_auth import AuthError, get_supabase_auth

            client = get_supabase_auth()
            existing = client.admin_find_user_by_email(email)
            if existing is None:
                try:
                    supabase_user = client.admin_create_user(
                        email=email, password=password, email_confirm=True
                    )
                except AuthError as exc:
                    raise click.ClickException(str(exc)) from exc
                click.echo("Created the Supabase identity.")
            else:
                supabase_user = client.admin_update_user(existing.id, password=password, email_confirm=True)
                click.echo("Updated the existing Supabase identity.")

            if user is None:
                user = User(username=username, email=email)
                db.session.add(user)
            user.supabase_user_id = supabase_user.id
            user.password_hash = None  # credential lives in Supabase now
        else:
            if user is None:
                user = User(username=username, email=email)
                db.session.add(user)
            user.set_password(password)

        user.is_admin = True
        user.mark_email_verified()
        db.session.commit()
        click.echo(f"Admin ready: {email} (auth backend: {config.auth_backend})")

    @app.cli.command("migrate-users-to-supabase")
    @click.option("--dry-run", is_flag=True, help="Report what would happen, change nothing.")
    @click.option(
        "--send-reset/--no-send-reset",
        default=True,
        help="Email each migrated user a password reset link.",
    )
    def migrate_users_to_supabase(dry_run: bool, send_reset: bool) -> None:
        """Move existing local accounts onto Supabase Auth.

        Werkzeug's pbkdf2 hashes cannot be imported into GoTrue, so each
        account is created with a throwaway random password and the user is
        sent a reset link. The local hash is then cleared, which also retires
        the hashes that leaked into git history.
        """
        import secrets as _secrets

        from fluxweb.integrations.supabase_auth import AuthError, get_supabase_auth

        config: Config = app.extensions["flux_config"]
        if not config.uses_supabase_auth:
            raise click.ClickException(
                "AUTH_BACKEND is not 'supabase'. Configure SUPABASE_URL and " "SUPABASE_ANON_KEY first."
            )
        if not config.supabase_service_role_key:
            raise click.ClickException("SUPABASE_SERVICE_ROLE_KEY is required for this migration.")

        client = get_supabase_auth()
        pending = User.query.filter(User.supabase_user_id.is_(None)).order_by(User.id).all()
        if not pending:
            click.echo("Nothing to do: every account already has a Supabase identity.")
            return

        click.echo(f"{len(pending)} account(s) to migrate.{'  (dry run)' if dry_run else ''}")
        migrated = skipped = failed = 0

        for account in pending:
            try:
                existing = client.admin_find_user_by_email(account.email)
                if dry_run:
                    action = "link existing" if existing else "create"
                    click.echo(f"  would {action}: {account.email}")
                    migrated += 1
                    continue

                if existing is not None:
                    supabase_user = existing
                    click.echo(f"  linked existing identity: {account.email}")
                else:
                    supabase_user = client.admin_create_user(
                        email=account.email,
                        password=_secrets.token_urlsafe(32),
                        # Preserve whatever we already knew about the address.
                        email_confirm=account.email_verified,
                    )
                    click.echo(f"  created: {account.email}")

                account.supabase_user_id = supabase_user.id
                account.password_hash = None
                db.session.commit()

                if send_reset:
                    client.send_password_reset(
                        email=account.email,
                        redirect_to=(config.base_url or "").rstrip("/") + "/reset-password",
                    )
                migrated += 1
            except AuthError as exc:
                click.secho(f"  SKIPPED {account.email}: {exc}", fg="yellow")
                skipped += 1
            except Exception as exc:  # noqa: BLE001 - report and continue
                db.session.rollback()
                click.secho(f"  FAILED  {account.email}: {exc}", fg="red")
                failed += 1

        click.echo(f"\nMigrated {migrated}, skipped {skipped}, failed {failed}.")
        if not dry_run and send_reset and migrated:
            click.echo("Each migrated user has been emailed a password reset link.")
        if failed:
            raise click.ClickException("Some accounts did not migrate; re-run after investigating.")

    @app.cli.command("import-legacy-content")
    @click.option(
        "--source",
        "sources",
        multiple=True,
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        help="SQLite database(s) to import from. If omitted, common local instance DBs are tried.",
    )
    def import_legacy_content(sources: tuple[Path, ...]) -> None:
        """Import plans and public/admin content from legacy local SQLite DBs."""
        import json

        from fluxweb.models import (
            Announcement,
            Coupon,
            FAQ,
            GamePlan,
            GlobeLocation,
            MaintenanceUpdate,
            ReferralCode,
            ServiceStatus,
        )

        if not sources:
            candidates = [
                Path("instance/flux_tickets.db"),
                Path("instance/fluxweb-dev.db"),
                Path("instance/flux_servers.db"),
                Path("instance/tickets.db"),
            ]
            sources = tuple(path for path in candidates if path.exists())

        if not sources:
            raise click.ClickException("No source database found. Pass one or more --source paths.")

        def table_exists(conn: sqlite3.Connection, table: str) -> bool:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
                (table,),
            ).fetchone()
            return bool(row)

        def rows(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
            if not table_exists(conn, table):
                return []
            return list(conn.execute(f"SELECT * FROM {table}"))

        def int_list(value) -> list[int]:
            if value is None:
                return []
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                except ValueError:
                    parsed = [part.strip() for part in value.replace(",", "\n").splitlines()]
            else:
                parsed = value
            result: list[int] = []
            if isinstance(parsed, list):
                for item in parsed:
                    try:
                        node_id = int(item)
                    except (TypeError, ValueError):
                        continue
                    if node_id > 0 and node_id not in result:
                        result.append(node_id)
            return result

        imported_counts = {
            "plans": 0,
            "faqs": 0,
            "coupons": 0,
            "locations": 0,
            "status": 0,
            "maintenance": 0,
            "announcements": 0,
            "referrals": 0,
        }

        for source in sources:
            click.echo(f"Importing from {source} ...")
            conn = sqlite3.connect(source)
            conn.row_factory = sqlite3.Row
            try:
                for row in rows(conn, "game_plan"):
                    plan = GamePlan.query.filter_by(game=row["game"], name=row["name"]).first()
                    if plan is None:
                        plan = GamePlan(game=row["game"], name=row["name"])
                        db.session.add(plan)
                        imported_counts["plans"] += 1
                    plan.price = float(row["price"] or 0)
                    if "feature1" in row.keys():
                        plan.feature1 = row["feature1"]
                    if "feature2" in row.keys():
                        plan.feature2 = row["feature2"]
                    if "feature3" in row.keys():
                        plan.feature3 = row["feature3"]
                    if "feature4" in row.keys():
                        plan.feature4 = row["feature4"]
                    plan.features = row["features"] if "features" in row.keys() and row["features"] else "[]"
                    plan.is_featured = bool(row["is_featured"]) if "is_featured" in row.keys() else False
                    plan.memory = int(row["memory"] or 1024)
                    plan.cpu = int(row["cpu"] or 100)
                    plan.disk = int(row["disk"] or 5120)
                    plan.nest_id = str(row["nest_id"] or "General")
                    plan.egg_id = int(row["egg_id"] or 1)
                    plan.location_id = int(row["location_id"] or 1)
                    plan.backups = int(row["backups"] or 1) if "backups" in row.keys() else 1
                    plan.allocations = int(row["allocations"] or 1) if "allocations" in row.keys() else 1
                    plan.databases = int(row["databases"] or 1) if "databases" in row.keys() else 1
                    plan.sub_type = (
                        row["sub_type"] if "sub_type" in row.keys() and row["sub_type"] else "Monthly"
                    )
                    plan.serial_number = (
                        int(row["serial_number"] or 0) if "serial_number" in row.keys() else 0
                    )
                    plan.image_url = row["image_url"] if "image_url" in row.keys() else None
                    allowed = (
                        int_list(row["allowed_location_ids"]) if "allowed_location_ids" in row.keys() else []
                    )
                    plan.set_allowed_node_ids(allowed or [plan.location_id])

                for row in rows(conn, "faq"):
                    faq = FAQ.query.filter_by(question=row["question"]).first()
                    if faq is None:
                        faq = FAQ(question=row["question"], answer=row["answer"])
                        db.session.add(faq)
                        imported_counts["faqs"] += 1
                    faq.answer = row["answer"]
                    faq.category = (
                        row["category"] if "category" in row.keys() and row["category"] else "General"
                    )
                    faq.order = int(row["order"] or 0) if "order" in row.keys() else 0

                for row in rows(conn, "coupon"):
                    coupon = Coupon.query.filter_by(code=row["code"]).first()
                    if coupon is None:
                        coupon = Coupon(code=row["code"])
                        db.session.add(coupon)
                        imported_counts["coupons"] += 1
                    coupon.discount_percent = float(row["discount_percent"] or 0)
                    if "active" in row.keys():
                        coupon.active = bool(row["active"])
                    if "max_redemptions" in row.keys():
                        coupon.max_redemptions = (
                            int(row["max_redemptions"]) if row["max_redemptions"] is not None else None
                        )
                    if "times_redeemed" in row.keys():
                        coupon.times_redeemed = int(row["times_redeemed"] or 0)

                for row in rows(conn, "globe_location"):
                    location = GlobeLocation.query.filter_by(name=row["name"]).first()
                    if location is None:
                        location = GlobeLocation(
                            name=row["name"], lat=float(row["lat"]), lng=float(row["lng"])
                        )
                        db.session.add(location)
                        imported_counts["locations"] += 1
                    location.lat = float(row["lat"])
                    location.lng = float(row["lng"])

                for row in rows(conn, "service_status"):
                    service = ServiceStatus.query.filter_by(name=row["name"]).first()
                    if service is None:
                        service = ServiceStatus(name=row["name"])
                        db.session.add(service)
                        imported_counts["status"] += 1
                    service.status = row["status"] or "Operational"
                    if "flag_icon" in row.keys():
                        service.flag_icon = row["flag_icon"]

                for row in rows(conn, "maintenance_update"):
                    maintenance = MaintenanceUpdate.query.filter_by(
                        title=row["title"], content=row["content"]
                    ).first()
                    if maintenance is None:
                        maintenance = MaintenanceUpdate(title=row["title"], content=row["content"])
                        db.session.add(maintenance)
                        imported_counts["maintenance"] += 1
                    maintenance.status = (
                        row["status"] if "status" in row.keys() and row["status"] else "Scheduled"
                    )

                for row in rows(conn, "announcement"):
                    announcement = Announcement.query.filter_by(content=row["content"]).first()
                    if announcement is None:
                        announcement = Announcement(content=row["content"])
                        db.session.add(announcement)
                        imported_counts["announcements"] += 1
                    if "active" in row.keys():
                        announcement.active = bool(row["active"])

                for row in rows(conn, "referral_code"):
                    referral = ReferralCode.query.filter_by(code=row["code"]).first()
                    if referral is None:
                        referral = ReferralCode(code=row["code"], target_url=row["target_url"])
                        db.session.add(referral)
                        imported_counts["referrals"] += 1
                    referral.target_url = row["target_url"]
                    if "clicks" in row.keys():
                        referral.clicks = int(row["clicks"] or 0)
            finally:
                conn.close()

        db.session.commit()
        click.echo("Import complete.")
        for label, count in imported_counts.items():
            click.echo(f"  {label}: {count} created")

    @app.cli.command("sync-servers")
    def sync_servers() -> None:
        """Sync panel state, expire, suspend, and delete. Run from cron."""
        from fluxweb.integrations.fluid import get_fluid_client
        from fluxweb.services import servers as server_service

        config: Config = app.extensions["flux_config"]
        stats = server_service.sync_all_servers(get_fluid_client(), grace_days=config.deletion_grace_days)
        click.echo(f"Checked {stats['checked']} servers ({stats['failed']} panel failures).")

    @app.cli.command("retry-order")
    @click.argument("public_id")
    @click.option(
        "--force",
        is_flag=True,
        help="Also retry an order stuck in PROVISIONING (e.g. after a crash mid-run).",
    )
    def retry_order(public_id: str, force: bool) -> None:
        """Re-run provisioning for a paid order that failed."""
        from fluxweb.integrations.fluid import get_fluid_client
        from fluxweb.models import Order, OrderStatus
        from fluxweb.services import provisioning

        config: Config = app.extensions["flux_config"]
        order = Order.query.filter_by(public_id=public_id).first()

        # provision_order only claims orders in PAID/FAILED. A process that
        # died mid-run leaves PROVISIONING behind, which would otherwise block
        # every retry forever.
        if order is not None and force and order.status == OrderStatus.PROVISIONING:
            order.status = OrderStatus.PAID
            db.session.commit()
            click.echo("Reset a stuck PROVISIONING order back to PAID.")

        if order is None:
            raise click.ClickException(f"No order with public id {public_id}")

        result = provisioning.provision_order(order, get_fluid_client(), expiry_days=config.expiry_days)
        click.echo(f"Provisioned {result.success_count}; errors: {result.errors or 'none'}")
