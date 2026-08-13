"""Bring .env into line with .env.example without losing anything.

`.env.example` is the canonical list of settings and carries the explanatory
comments. `.env` holds your actual values. As the application gains settings
the two drift, and the failure mode is a confusing refusal to boot.

This rebuilds `.env` using the example's structure and comments, substituting
every value you already have. It never overwrites a value you have set, never
prints a secret, and backs up the previous file first.

    python tools/sync_env.py --check    # report drift, change nothing
    python tools/sync_env.py            # apply
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

#: Settings the application refuses to start without, per environment.
REQUIRED_IN_PRODUCTION = (
    "SECRET_KEY",
    "ENCRYPTION_KEY",
    "BASE_URL",
    "DATABASE_URL",
    "CRON_SECRET",
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "PELICAN_URL",
    "PELICAN_API_KEY",
)

#: Settings that are optional but change behaviour in important ways.
RECOMMENDED = {
    "DIRECT_URL": "required when DATABASE_URL is the transaction pooler (port 6543)",
    "STRIPE_WEBHOOK_SECRET": "without it, payments are never confirmed or provisioned",
    "REDIS_URL": "without it, rate limits are per-instance and easily bypassed",
    "PAYPAL_MERCHANT_ID": "needed to verify captures are payable to you",
}


def parse(path: Path) -> dict[str, str]:
    """Read KEY=VALUE pairs, ignoring comments and blank lines."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def build(example: Path, current: dict[str, str]) -> tuple[str, list[str], list[str]]:
    """Render the new .env. Returns (text, added_keys, carried_keys)."""
    added: list[str] = []
    carried: list[str] = []
    out: list[str] = []
    seen: set[str] = set()

    for raw in example.read_text(encoding="utf-8-sig").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append(raw)
            continue

        key, _, example_value = stripped.partition("=")
        key = key.strip()
        seen.add(key)

        if key in current:
            out.append(f"{key}={current[key]}")
            if current[key]:
                carried.append(key)
        else:
            # Keep whatever default the example suggested.
            out.append(f"{key}={example_value.strip()}")
            added.append(key)

    # Anything you have that the example does not know about is preserved
    # rather than silently dropped.
    extra = [k for k in current if k not in seen]
    if extra:
        out.append("")
        out.append("# --- settings not present in .env.example -------------------------------")
        for key in extra:
            out.append(f"{key}={current[key]}")

    return "\n".join(out).rstrip() + "\n", added, carried


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="report only, change nothing")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--example", default=".env.example")
    args = parser.parse_args()

    env_path, example_path = Path(args.env), Path(args.example)
    if not example_path.exists():
        print(f"No {example_path} found.", file=sys.stderr)
        return 1

    current = parse(env_path)
    text, added, carried = build(example_path, current)

    print(f"{example_path} defines {len(parse(example_path))} settings.")
    print(f"{env_path} currently has {len(current)} ({len(carried)} with values).\n")

    if added:
        print(f"Adding {len(added)} missing setting(s):")
        for key in added:
            note = RECOMMENDED.get(key)
            print(f"   + {key}" + (f"   ({note})" if note else ""))
    else:
        print("No missing settings.")

    merged = parse(env_path) if args.check else None
    effective = {**{k: "" for k in added}, **current} if merged is None else current

    blank_required = [k for k in REQUIRED_IN_PRODUCTION if not effective.get(k)]
    if blank_required:
        print(f"\nStill empty, and required before FLASK_ENV=production ({len(blank_required)}):")
        for key in blank_required:
            print(f"   ! {key}")

    blank_recommended = [k for k in RECOMMENDED if not effective.get(k)]
    if blank_recommended:
        print("\nEmpty and strongly recommended:")
        for key in blank_recommended:
            print(f"   ~ {key}   {RECOMMENDED[key]}")

    if args.check:
        print("\n(--check: nothing was written)")
        return 1 if added else 0

    if not added:
        print("\nNothing to do.")
        return 0

    if env_path.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = env_path.with_name(f"{env_path.name}.backup-{stamp}")
        shutil.copy2(env_path, backup)
        print(f"\nBacked up to {backup.name}")

    env_path.write_text(text, encoding="utf-8")
    print(f"Wrote {env_path} — existing values preserved, comments refreshed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
