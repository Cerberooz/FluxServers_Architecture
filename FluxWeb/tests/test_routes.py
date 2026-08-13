"""Route-level checks.

The blueprint split must not have moved or dropped a URL, because every
template links to these paths as hardcoded strings.
"""

from __future__ import annotations

import pytest

# Every path the pre-refactor application served.
LEGACY_PATHS = [
    "/",
    "/minecraft",
    "/hytale",
    "/dedicated",
    "/discord-bots",
    "/about",
    "/contact",
    "/status",
    "/maintenance",
    "/ram-calculator",
    "/privacy",
    "/terms",
    "/account",
    "/account/sync",
    "/account/change-password",
    "/cart",
    "/checkout",
    "/apply-coupon",
    "/remove-coupon",
    "/create-stripe-checkout",
    "/stripe-success",
    "/login",
    "/logout",
    "/register",
    "/checker",
    "/admin",
    "/admin/pelican-test",
    "/admin/plans/export",
    "/admin/plans/import",
    "/admin/plans/add",
    "/admin/faqs/add",
    "/admin/maintenance/add",
    "/admin/status/update",
    "/admin/locations/add",
    "/admin/coupons/add",
    "/admin/add-referral",
    "/api/locations",
]

PARAMETERISED_RULES = [
    "/add-to-cart/<int:plan_id>",
    "/remove-from-cart/<int:index>",
    "/update-cart-item/<int:index>",
    "/renew/<int:server_id>",
    "/upgrade/<int:server_id>",
    "/add-upgrade-to-cart/<int:server_id>/<int:plan_id>",
    "/api/server/<identifier>/stats",
    "/api/server/<identifier>/websocket",
    "/api/server/<identifier>/power",
    "/admin/api/eggs/<nest_id>",
    "/admin/plans/edit/<int:plan_id>",
    "/admin/plans/delete/<int:plan_id>",
    "/admin/faqs/edit/<int:faq_id>",
    "/admin/faqs/delete/<int:faq_id>",
    "/admin/locations/delete/<int:loc_id>",
    "/admin/user/<int:user_id>/provision",
    "/admin/server/<int:server_id>/suspend",
    "/admin/server/<int:server_id>/delete",
    "/admin/delete-referral/<int:ref_id>",
    "/r/<string:code>",
]


def _rules(app) -> set[str]:
    return {str(rule) for rule in app.url_map.iter_rules()}


@pytest.mark.parametrize("path", LEGACY_PATHS)
def test_legacy_path_still_registered(app, path):
    assert path in _rules(app), f"{path} disappeared in the blueprint split"


@pytest.mark.parametrize("rule", PARAMETERISED_RULES)
def test_parameterised_rule_still_registered(app, rule):
    assert rule in _rules(app), f"{rule} disappeared in the blueprint split"


def test_new_routes_registered(app):
    rules = _rules(app)
    for rule in (
        "/webhooks/stripe",
        "/api/paypal/order",
        "/api/paypal/capture",
        "/auth/confirm",
        "/verify-email/<token>",
        "/forgot-password",
        "/admin/coupons/delete/<int:coupon_id>",
    ):
        assert rule in rules


class TestPublicPages:
    @pytest.mark.parametrize("path", ["/", "/minecraft", "/about", "/privacy", "/terms", "/cart"])
    def test_renders(self, client, path):
        assert client.get(path).status_code == 200


class TestAccessControl:
    def test_account_requires_login(self, client):
        response = client.get("/account")
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    def test_admin_requires_login(self, client):
        assert client.get("/admin").status_code == 302

    def test_admin_refuses_ordinary_user(self, client, user, login):
        login(user)
        response = client.get("/admin")
        assert response.status_code == 302
        assert "/admin" not in response.headers["Location"]

    def test_checker_is_no_longer_public(self, client):
        """H-17: this used to be an unauthenticated upload endpoint."""
        assert client.get("/checker").status_code == 302


class TestSupabaseEmailRoutes:
    def test_auth_confirm_redirects_email_tokens(self, client):
        response = client.get("/auth/confirm?token_hash=abc123&type=email")
        assert response.status_code == 302
        assert "/verify-email?token_hash=abc123&type=email" in response.headers["Location"]

    def test_auth_confirm_redirects_recovery_tokens(self, client):
        response = client.get("/auth/confirm?token_hash=reset123&type=recovery")
        assert response.status_code == 302
        assert "/reset-password?token_hash=reset123&type=recovery" in response.headers["Location"]

    def test_auth_confirm_rejects_unknown_types(self, client):
        response = client.get("/auth/confirm?token_hash=abc123&type=magiclink")
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    def test_stats_endpoint_refuses_other_peoples_servers(self, client, other_user, server, login):
        login(other_user)
        response = client.get(f"/api/server/{server.pelican_server_identifier}/stats")
        assert response.status_code == 403


class TestWebhookSignature:
    """C-7: an unsigned webhook must never be acted on."""

    def test_unsigned_webhook_is_rejected(self, client):
        response = client.post("/webhooks/stripe", json={"type": "checkout.session.completed"})
        assert response.status_code == 400

    def test_bad_signature_is_rejected(self, client):
        response = client.post(
            "/webhooks/stripe",
            data=b'{"type":"checkout.session.completed"}',
            headers={"Stripe-Signature": "t=1,v1=deadbeef"},
        )
        assert response.status_code == 400


class TestSecurityHeaders:
    def test_headers_present(self, client):
        headers = client.get("/").headers
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "SAMEORIGIN"
        assert "Content-Security-Policy" in headers
        assert "frame-ancestors" in headers["Content-Security-Policy"]
        assert "object-src 'none'" in headers["Content-Security-Policy"]

    def test_server_header_removed(self, client):
        assert "X-Powered-By" not in client.get("/").headers


class TestCartIntegrity:
    """C-6: the cart cookie must not carry prices."""

    def test_cart_stores_ids_only(self, client, plan):
        client.post(f"/add-to-cart/{plan.id}")
        with client.session_transaction() as sess:
            for entry in sess["cart"]:
                assert "price" not in entry
                assert "plan_id" in entry

    def test_cart_size_is_capped(self, client, plan):
        for _ in range(30):
            client.post(f"/add-to-cart/{plan.id}")
        with client.session_transaction() as sess:
            assert len(sess["cart"]) <= 20
