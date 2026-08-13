"""HTTP layer, split by concern.

Every URL path is byte-identical to the pre-refactor application because the
templates link to them as hardcoded strings.
"""

from fluxweb.web import account, admin, api, auth, cart, checker, checkout, jobs, public, webhooks

BLUEPRINTS = (
    public.bp,
    auth.bp,
    account.bp,
    cart.bp,
    checkout.bp,
    api.bp,
    admin.bp,
    checker.bp,
    webhooks.bp,
    jobs.bp,
)

__all__ = ["BLUEPRINTS"]
