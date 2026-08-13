"""Inspect payment keys without revealing them.

Two levels of confidence:

  offline  - prefix and shape only. Tells you live vs test vs placeholder.
             Never leaves the machine.
  --live   - asks Stripe/PayPal whether the credential actually works.
             Read-only calls; no money moves. Requires network.

Usage:
    python tools/check_keys.py                  # inspect .env
    python tools/check_keys.py --file .env.bak  # inspect a different file
    python tools/check_keys.py --live           # also verify against the APIs
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PLACEHOLDER_MARKERS = ("your", "xxx", "placeholder", "changeme", "example", "abc123", "...", "<")

# Documented Stripe key prefixes.
STRIPE_PREFIXES = {
    "sk_live_": ("secret", "LIVE", True),
    "sk_test_": ("secret", "test", False),
    "rk_live_": ("restricted", "LIVE", True),
    "rk_test_": ("restricted", "test", False),
    "pk_live_": ("publishable", "LIVE", True),
    "pk_test_": ("publishable", "test", False),
    "whsec_": ("webhook signing", "either", False),
}


def mask(value: str) -> str:
    """Show enough to identify a key, never enough to use it.

    ASCII only: the Windows console codepage mangles non-ASCII output.
    """
    if len(value) <= 12:
        return value[:3] + "..."
    return f"{value[:11]}...{value[-4:]}"


def load_env(path: Path) -> dict[str, str]:
    if not path.exists():
        sys.exit(f"No such file: {path}")
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip().strip("'\"")
    return values


def looks_like_placeholder(value: str) -> bool:
    lowered = value.lower()
    if any(marker in lowered for marker in PLACEHOLDER_MARKERS):
        return True
    # A real key's random tail is mixed-case alphanumeric; placeholders are
    # usually short or a single repeated character.
    tail = value.split("_")[-1]
    return len(value) < 20 or len(set(tail)) <= 3


def describe_stripe(name: str, value: str) -> None:
    if not value:
        print(f"  {name:26} (empty)")
        return

    for prefix, (kind, mode, is_live) in STRIPE_PREFIXES.items():
        if value.startswith(prefix):
            verdict = "PLACEHOLDER" if looks_like_placeholder(value) else "real-looking"
            flag = "  <-- LIVE MONEY" if is_live and verdict == "real-looking" else ""
            print(f"  {name:26} {mask(value):24} {kind} key, {mode} mode, {verdict}{flag}")
            return

    print(f"  {name:26} {mask(value):24} UNRECOGNISED prefix - not a valid Stripe key")


def check_live_stripe(secret: str) -> None:
    """Ask Stripe whether the key works. Read-only: GET /v1/account."""
    try:
        import requests
    except ImportError:
        sys.exit("requests is not installed; run this inside .venv")

    try:
        response = requests.get("https://api.stripe.com/v1/account", auth=(secret, ""), timeout=15)
    except requests.RequestException as exc:
        print(f"  could not reach Stripe: {exc}")
        return

    if response.status_code == 200:
        data = response.json()
        livemode = data.get("charges_enabled") is not None
        print("  Stripe says: VALID")
        print(f"    account id      : {data.get('id')}")
        print(f"    business name   : {data.get('business_profile', {}).get('name') or '(unset)'}")
        print(f"    country         : {data.get('country')}")
        print(f"    charges enabled : {data.get('charges_enabled')}")
        print(f"    payouts enabled : {data.get('payouts_enabled')}")
        if livemode and not data.get("charges_enabled"):
            print("    NOTE: charges are disabled - onboarding may be incomplete.")
    elif response.status_code == 401:
        print("  Stripe says: INVALID or REVOKED (401)")
    else:
        print(f"  Stripe returned {response.status_code}: {response.text[:200]}")


def describe_supabase(env: dict[str, str], *, live: bool) -> None:
    """Report on the Supabase project URL, keys, and connection strings."""
    from urllib.parse import urlparse

    url = env.get("SUPABASE_URL", "")
    public = (
        env.get("SUPABASE_ANON_KEY") or env.get("SUPABASE_PUBLISHABLE_KEY") or env.get("SUPABASE_KEY", "")
    )
    secret = env.get("SUPABASE_SERVICE_ROLE_KEY") or env.get("SUPABASE_SECRET_KEY", "")

    if not url:
        print("  SUPABASE_URL               (empty)")
        return

    ref = urlparse(url).hostname or ""
    ref = ref.split(".")[0] if ref.endswith(".supabase.co") else "(not a supabase.co host)"
    print(f"  SUPABASE_URL               {url}")
    print(f"  project ref                {ref}")

    def classify(value: str, *, expect_secret: bool) -> str:
        if not value:
            return "(empty)"
        if value.startswith("sb_publishable_"):
            kind = "publishable (public)"
        elif value.startswith("sb_secret_"):
            kind = "SECRET"
        elif value.startswith("eyJ"):
            kind = "legacy JWT key"
        else:
            kind = "unrecognised format"
        wrong = (expect_secret and "publishable" in kind) or (not expect_secret and kind == "SECRET")
        return f"{kind}{'   <-- WRONG SLOT' if wrong else ''}"

    print(f"  public key                 {mask(public):24} {classify(public, expect_secret=False)}")
    print(f"  secret key                 {mask(secret):24} {classify(secret, expect_secret=True)}")

    for name in ("DATABASE_URL", "DIRECT_URL"):
        value = env.get(name, "")
        if not value:
            print(f"  {name:26} (empty)")
            continue
        port = urlparse(value).port
        role = {
            6543: "transaction pooler - correct for DATABASE_URL",
            5432: "session/direct - correct for DIRECT_URL",
        }.get(port, f"port {port}")
        warn = ""
        if name == "DATABASE_URL" and port == 5432:
            warn = "   (works, but 6543 is better for serverless)"
        if name == "DIRECT_URL" and port == 6543:
            warn = "   <-- WRONG: migrations need 5432"
        print(f"  {name:26} port {port} - {role}{warn}")

    if not live:
        print("\n  (add --live to verify the keys against the project)")
        return

    try:
        import requests
    except ImportError:
        return

    print("\n  --- live verification (read-only) ---")
    if public:
        try:
            r = requests.get(f"{url}/auth/v1/settings", headers={"apikey": public}, timeout=15)
            if r.status_code == 200:
                data = r.json()
                print("  public key: VALID")
                print(f"    signups enabled     : {not data.get('disable_signup', False)}")
                print(f"    email autoconfirm   : {data.get('mailer_autoconfirm')}")
                providers = [k for k, v in (data.get("external") or {}).items() if v]
                print(f"    external providers  : {', '.join(providers) or 'none'}")
            else:
                print(f"  public key: REJECTED ({r.status_code})")
        except requests.RequestException as exc:
            print(f"  public key: could not reach Supabase ({exc})")

    if secret:
        try:
            r = requests.get(
                f"{url}/auth/v1/admin/users",
                headers={"apikey": secret, "Authorization": f"Bearer {secret}"},
                params={"per_page": 1},
                timeout=15,
            )
            if r.status_code == 200:
                total = r.json().get("aud") is not None
                print("  secret key: VALID (admin access confirmed)")
                del total
            elif r.status_code in (401, 403):
                print(f"  secret key: REJECTED ({r.status_code}) - not a service-role/secret key")
            else:
                print(f"  secret key: unexpected {r.status_code}")
        except requests.RequestException as exc:
            print(f"  secret key: could not reach Supabase ({exc})")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default=".env")
    parser.add_argument("--live", action="store_true", help="verify against the provider APIs")
    parser.add_argument("--supabase", action="store_true", help="check Supabase settings only")
    args = parser.parse_args()

    env = load_env(Path(args.file))

    if args.supabase:
        print(f"\n=== {args.file} : Supabase ===")
        describe_supabase(env, live=args.live)
        print()
        return

    print(f"\n=== {args.file} : Stripe ===")
    for name in ("STRIPE_PUBLISHABLE_KEY", "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"):
        describe_stripe(name, env.get(name, ""))

    pub, sec = env.get("STRIPE_PUBLISHABLE_KEY", ""), env.get("STRIPE_SECRET_KEY", "")
    if pub and sec:
        pub_live = pub.startswith(("pk_live_", "rk_live_"))
        sec_live = sec.startswith(("sk_live_", "rk_live_"))
        if pub_live != sec_live:
            print("\n  WARNING: publishable and secret keys are in DIFFERENT modes.")

    print(f"\n=== {args.file} : PayPal ===")
    client_id = env.get("PAYPAL_CLIENT_ID", "")
    secret = env.get("PAYPAL_SECRET_KEY", "")
    env_mode = env.get("PAYPAL_ENV", "sandbox")
    if client_id:
        # PayPal client ids carry no live/test prefix; PAYPAL_ENV decides which
        # API they are used against, which is why a mismatch is silent.
        verdict = "PLACEHOLDER" if looks_like_placeholder(client_id) else "real-looking"
        print(f"  PAYPAL_CLIENT_ID           {mask(client_id):24} {verdict}, len={len(client_id)}")
    else:
        print("  PAYPAL_CLIENT_ID           (empty)")
    print(f"  PAYPAL_SECRET_KEY          {'set' if secret else '(empty)'}")
    print(f"  PAYPAL_ENV                 {env_mode}")
    if client_id and not secret:
        print("  WARNING: client id without a secret - every payment would be captured then rejected.")

    print(f"\n=== {args.file} : Supabase ===")
    describe_supabase(env, live=args.live)

    if args.live:
        print("\n=== live verification: Stripe (read-only) ===")
        if sec and not looks_like_placeholder(sec):
            check_live_stripe(sec)
        else:
            print("  no usable Stripe secret key to check")

    print()


if __name__ == "__main__":
    main()
