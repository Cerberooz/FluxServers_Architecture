"""PayPal provider.

The previous flow created the order **in the browser** with a JavaScript
variable as the amount, and the server accepted any order whose status was
COMPLETED without checking what was actually paid (audit C-4). A customer
could pay $0.01 for any cart with a one-line console edit.

Here:

* The order is created server-side from the stored :class:`Order` snapshot.
  The browser only ever receives an opaque PayPal order id.
* Capture happens server-side, and the captured amount, currency, and payee
  are all verified against the snapshot before anything is provisioned.
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from requests.auth import HTTPBasicAuth
from urllib3.util.retry import Retry

from fluxweb.errors import IntegrationError, PaymentError
from fluxweb.integrations.payments.base import CapturedPayment, PaymentProvider
from fluxweb.money import format_amount, to_cents

log = logging.getLogger(__name__)


class PayPalProvider(PaymentProvider):
    name = "paypal"

    def __init__(
        self,
        *,
        client_id: str | None,
        secret_key: str | None,
        api_base: str,
        merchant_id: str | None = None,
        brand_name: str = "Flux Servers",
    ) -> None:
        self.client_id = client_id
        self.secret_key = secret_key
        self.api_base = api_base.rstrip("/")
        self.merchant_id = merchant_id
        self.brand_name = brand_name
        self._session: requests.Session | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.client_id and self.secret_key)

    # --- plumbing -------------------------------------------------------
    @property
    def session(self) -> requests.Session:
        if self._session is None:
            session = requests.Session()
            retry = Retry(
                total=2, backoff_factor=0.4, status_forcelist=(429, 502, 503, 504), raise_on_status=False
            )
            session.mount("https://", HTTPAdapter(max_retries=retry))
            self._session = session
        return self._session

    def _access_token(self) -> str:
        if not self.enabled:
            raise PaymentError("PayPal is not configured.")
        try:
            response = self.session.post(
                f"{self.api_base}/v1/oauth2/token",
                auth=HTTPBasicAuth(self.client_id or "", self.secret_key or ""),
                data={"grant_type": "client_credentials"},
                timeout=15,
            )
        except requests.RequestException as exc:
            raise IntegrationError("paypal", f"token request failed: {exc}") from exc

        if response.status_code != 200:
            log.error("PayPal auth failed: %s %s", response.status_code, response.text[:500])
            raise IntegrationError("paypal", "authentication failed", status=response.status_code)
        return response.json()["access_token"]

    def _api(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._access_token()}",
            "Content-Type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)
        try:
            response = self.session.request(
                method, f"{self.api_base}{path}", headers=headers, json=json_body, timeout=20
            )
        except requests.RequestException as exc:
            raise IntegrationError("paypal", f"{method} {path} failed: {exc}") from exc

        if response.status_code >= 400:
            log.error("PayPal %s %s -> %s %s", method, path, response.status_code, response.text[:500])
            raise IntegrationError("paypal", response.text[:500], status=response.status_code)
        if not response.content:
            return {}
        return response.json()

    # --- flow -----------------------------------------------------------
    def create_order(
        self,
        *,
        total_cents: int,
        currency: str,
        order_public_id: str,
        description: str,
        return_url: str,
        cancel_url: str,
    ) -> str:
        """Create a PayPal order server-side and return its id."""
        payload: dict[str, Any] = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": order_public_id,
                    "custom_id": order_public_id,
                    "description": description[:127],
                    "amount": {
                        "currency_code": currency,
                        "value": format_amount(total_cents),
                    },
                }
            ],
            "application_context": {
                "brand_name": self.brand_name,
                "shipping_preference": "NO_SHIPPING",
                "user_action": "PAY_NOW",
                "return_url": return_url,
                "cancel_url": cancel_url,
            },
        }
        if self.merchant_id:
            payload["purchase_units"][0]["payee"] = {"merchant_id": self.merchant_id}

        result = self._api(
            "POST",
            "/v2/checkout/orders",
            json_body=payload,
            # Idempotency: a retried create cannot produce two live orders.
            extra_headers={"PayPal-Request-Id": f"order-{order_public_id}"},
        )
        paypal_order_id = result.get("id")
        if not paypal_order_id:
            raise PaymentError("PayPal did not return an order id.")
        return str(paypal_order_id)

    def capture_order(self, paypal_order_id: str) -> CapturedPayment:
        """Capture server-side and return exactly what PayPal says was taken."""
        result = self._api("POST", f"/v2/checkout/orders/{paypal_order_id}/capture")
        return self._to_captured_payment(result, paypal_order_id)

    def get_order(self, paypal_order_id: str) -> CapturedPayment:
        result = self._api("GET", f"/v2/checkout/orders/{paypal_order_id}")
        return self._to_captured_payment(result, paypal_order_id)

    def _to_captured_payment(self, result: dict[str, Any], paypal_order_id: str) -> CapturedPayment:
        status = str(result.get("status", "UNKNOWN"))
        units = result.get("purchase_units") or []
        if not units:
            raise PaymentError("PayPal order contained no purchase units.")
        unit = units[0]

        # Prefer the amount PayPal actually captured over the amount that was
        # requested; they differ if the order was altered after creation.
        captures = (unit.get("payments") or {}).get("captures") or []
        if captures:
            capture = captures[0]
            amount = capture.get("amount") or {}
            status = str(capture.get("status", status))
        else:
            amount = unit.get("amount") or {}

        payee_merchant = (unit.get("payee") or {}).get("merchant_id")
        if self.merchant_id and payee_merchant and payee_merchant != self.merchant_id:
            # The money went somewhere else; never release goods for it.
            raise PaymentError("This payment was not made to Flux Servers.")

        return CapturedPayment(
            provider=self.name,
            # The ledger is keyed on the PayPal *order* id, not the capture id:
            # a retried capture can return a different capture id for the same
            # money, and keying on that would let one payment be redeemed
            # twice. The capture id stays retrievable from PayPal by order id.
            reference=str(paypal_order_id),
            amount_cents=to_cents(amount.get("value", "0")),
            currency=str(amount.get("currency_code", "USD")),
            status=status,
            order_public_id=str(unit.get("custom_id") or unit.get("reference_id") or "") or None,
        )
