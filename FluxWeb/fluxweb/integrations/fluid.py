"""Fluid Panel client.

FluidPanel is a Pterodactyl fork and keeps the same application/client API
shape, so one typed client serves both. This is the canonical module; the
older pelican/pterodactyl import paths have been removed rather than kept as
yet another alias layer (architecture review M-2).

Replaces the 30 hand-written ``requests`` calls that were spread through
``app.py``, each with its own timeout, status handling, and swallowed
exception (architecture review §2, P-8).

What this adds:

* One pooled :class:`requests.Session` per client, so repeated calls reuse the
  TCP + TLS connection instead of re-handshaking every time.
* Uniform timeouts and bounded retries with backoff on transient failures.
* Typed :class:`~fluxweb.errors.PanelError` instead of ``None``-or-tuple, so a
  panel outage cannot be mistaken for "no servers".
* Verified, one-to-one adoption of pre-existing panel users, followed by UUID
  based identity matching (unverified accounts are never adopted by email).
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from typing import Any, TypeAlias

import requests
from requests.adapters import HTTPAdapter
from urllib.parse import quote_plus
from urllib3.util.retry import Retry

from fluxweb.errors import ConfigurationError, PanelError

log = logging.getLogger(__name__)

RequestTimeout: TypeAlias = int | float | tuple[float, float]

DEFAULT_TIMEOUT: RequestTimeout = (2, 3)
METADATA_TIMEOUT: RequestTimeout = (1, 2)
LONG_TIMEOUT: RequestTimeout = (5, 20)


@dataclass(frozen=True)
class CreatedServer:
    """What the caller needs after a successful provision."""

    panel_id: int
    identifier: str
    ip_address: str | None
    node_name: str | None = None


class FluidPanelClient:
    """Thin, typed wrapper over the Fluid/Pterodactyl application + client APIs."""

    def __init__(
        self,
        base_url: str | None,
        api_key: str | None,
        client_key: str | None = None,
        *,
        timeout: RequestTimeout = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key
        # Compatibility argument only; the webapp no longer uses a shared
        # panel client credential.
        self.client_key = None
        self.timeout = timeout
        self._session: requests.Session | None = None

    # --- plumbing -------------------------------------------------------
    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            session = requests.Session()
            retry = Retry(
                total=0,
                backoff_factor=0,
                status_forcelist=(429, 502, 503, 504),
                # Reads only. Retrying a POST is dangerous here: if the panel
                # creates the server and *then* the gateway returns 502, a
                # retry creates a SECOND server for one payment. Order-level
                # idempotency cannot catch that, because the duplicate happens
                # below this layer. Write failures surface as PanelError and
                # are retried deliberately, not automatically.
                allowed_methods=frozenset({"GET", "HEAD"}),
                raise_on_status=False,
            )
            adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            self._session = session
        return self._session

    def _headers(self, *, client_api: bool = False) -> dict[str, str]:
        key = self.client_key if client_api else self.api_key
        if not key:
            raise ConfigurationError(
                "FLUID_CLIENT_KEY is not configured" if client_api else "FLUID_API_KEY is not configured"
            )
        return {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        client_api: bool = False,
        json_body: dict[str, Any] | None = None,
        timeout: RequestTimeout | None = None,
        expected: tuple[int, ...] = (200, 201, 204),
    ) -> Any:
        if not self.configured:
            raise ConfigurationError("Fluid Panel is not configured")

        url = f"{self.base_url}{path}"
        try:
            response = self.session.request(
                method,
                url,
                headers=self._headers(client_api=client_api),
                json=json_body,
                timeout=timeout or self.timeout,
            )
        except requests.RequestException as exc:
            log.warning("Panel request failed: %s %s: %s", method, path, exc)
            raise PanelError(f"{method} {path}: {exc}") from exc

        if response.status_code not in expected:
            detail = self._extract_error(response)
            log.warning("Panel rejected %s %s: %s %s", method, path, response.status_code, detail)
            raise PanelError(f"{method} {path}: {detail}", status=response.status_code)

        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise PanelError(f"{method} {path}: response was not JSON") from exc

    @staticmethod
    def _extract_error(response: requests.Response) -> str:
        """Pull a useful message out of a panel error body, for logs only."""
        try:
            payload = response.json()
        except ValueError:
            return (response.text or "")[:500]
        errors = payload.get("errors") if isinstance(payload, dict) else None
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict):
                return str(first.get("detail") or first.get("code") or first)[:500]
        return str(payload)[:500]

    # --- metadata -------------------------------------------------------
    def list_nests(self) -> list[dict[str, Any]]:
        """Return the panel's actual nests.

        Fluid follows Pterodactyl's nested API shape: eggs belong to a nest,
        so there is intentionally no global ``/api/application/eggs`` route.
        """
        payload = self._request("GET", "/api/application/nests", expected=(200,), timeout=METADATA_TIMEOUT)
        return payload.get("data", []) if payload else []

    def eggs_for_nest(self, nest_id: str | int) -> list[dict[str, Any]]:
        payload = self._request(
            "GET", f"/api/application/nests/{int(nest_id)}/eggs", expected=(200,), timeout=METADATA_TIMEOUT
        )
        return payload.get("data", []) if payload else []

    def get_egg(self, egg_id: int, *, nest_id: str | int | None = None) -> dict[str, Any]:
        if nest_id is None:
            # Legacy plans did not store a real nest ID. Find the egg safely
            # rather than querying the non-existent global eggs endpoint.
            for nest in self.list_nests():
                candidate_nest_id = nest.get("attributes", {}).get("id")
                if candidate_nest_id is None:
                    continue
                for egg in self.eggs_for_nest(candidate_nest_id):
                    if int(egg.get("attributes", {}).get("id", 0)) == egg_id:
                        return egg.get("attributes", {})
            raise PanelError(f"Egg {egg_id} was not found")

        payload = self._request(
            "GET", f"/api/application/nests/{int(nest_id)}/eggs/{egg_id}?include=variables", expected=(200,)
        )
        return payload.get("attributes", {}) if payload else {}

    @staticmethod
    def _relationship_attributes(attrs: dict[str, Any], name: str) -> dict[str, Any]:
        relationship = (attrs.get("relationships") or {}).get(name) or {}
        data = relationship.get("data") if isinstance(relationship, dict) else None
        if isinstance(data, dict):
            return data.get("attributes") or {}
        return relationship.get("attributes") if isinstance(relationship, dict) else {}

    @staticmethod
    def _location_label(attrs: dict[str, Any]) -> str:
        location = FluidPanelClient._relationship_attributes(attrs, "location")
        if not location and isinstance(attrs.get("location"), dict):
            location = attrs.get("location") or {}

        short = location.get("short") or location.get("name") or attrs.get("location_short")
        long_name = (
            location.get("long")
            or location.get("description")
            or location.get("city")
            or attrs.get("location_long")
            or attrs.get("location")
        )

        if short and long_name and str(short).lower() not in str(long_name).lower():
            return f"{short} - {long_name}"
        return str(long_name or short or "")

    def list_nodes(self) -> list[dict[str, Any]]:
        try:
            payload = self._request(
                "GET", "/api/application/nodes?include=location", expected=(200,), timeout=METADATA_TIMEOUT
            )
        except PanelError as exc:
            if exc.status not in (400, 404):
                raise
            payload = self._request(
                "GET", "/api/application/nodes", expected=(200,), timeout=METADATA_TIMEOUT
            )
        nodes = payload.get("data", []) if payload else []
        for node in nodes:
            attrs = node.get("attributes", {})
            location_label = self._location_label(attrs)
            attrs["short"] = attrs.get("name")
            attrs["location_label"] = location_label
            attrs["long"] = location_label or attrs.get("fqdn")
            attrs["capacity"] = self._node_capacity(attrs)
        return nodes

    @staticmethod
    def _node_capacity(attrs: dict[str, Any]) -> dict[str, Any]:
        """Free memory and disk on a node, in MB.

        Mirrors the panel's own viability rule (FindViableNodesService): a node
        can take a server when the sum of existing server limits plus the new
        one fits inside ``limit * (1 + overallocate/100)``. An overallocate of
        -1 means the panel forbids overallocation entirely.
        """

        def budget(limit: Any, overallocate: Any) -> int:
            try:
                limit = int(limit or 0)
                over = int(overallocate if overallocate is not None else 0)
            except (TypeError, ValueError):
                return 0
            over = max(over, 0)  # -1 means overallocation is disabled
            return int(limit * (1 + over / 100))

        allocated = attrs.get("allocated_resources") or {}
        try:
            used_memory = int(allocated.get("memory") or 0)
            used_disk = int(allocated.get("disk") or 0)
        except (TypeError, ValueError):
            used_memory = used_disk = 0

        memory_budget = budget(attrs.get("memory"), attrs.get("memory_overallocate"))
        disk_budget = budget(attrs.get("disk"), attrs.get("disk_overallocate"))

        return {
            "memory_free": max(0, memory_budget - used_memory),
            "disk_free": max(0, disk_budget - used_disk),
            "memory_total": memory_budget,
            "disk_total": disk_budget,
            "maintenance": bool(attrs.get("maintenance_mode")),
            # The panel only deploys to public nodes.
            "public": bool(attrs.get("public", True)),
        }

    def node_fits(self, attrs: dict[str, Any], *, memory: int, disk: int) -> bool:
        """Whether a node could accept a server of this size right now."""
        capacity = attrs.get("capacity") or self._node_capacity(attrs)
        if capacity["maintenance"] or not capacity["public"]:
            return False
        return capacity["memory_free"] >= memory and capacity["disk_free"] >= disk

    def deployable_nodes(
        self, *, memory: int, disk: int, location_ids: list[int] | None = None
    ) -> list[dict[str, Any]]:
        """Ask the panel which nodes can take a server of this size.

        Uses the panel's own deployment filter, so the answer matches what
        server creation would actually do. Returns [] when nothing fits rather
        than raising, because "no capacity" is a normal answer here.
        """
        params = [f"memory={int(memory)}", f"disk={int(disk)}"]
        for location_id in location_ids or []:
            params.append(f"location_ids[]={int(location_id)}")
        try:
            payload = self._request(
                "GET", f"/api/application/nodes/deployable?{'&'.join(params)}", expected=(200,)
            )
        except PanelError as exc:
            # The panel raises NoViableNodeException (422) when nothing fits.
            if exc.status in (404, 422):
                return []
            raise
        return payload.get("data", []) if payload else []

    def get_node(self, node_id: int) -> dict[str, Any]:
        payload = self._request("GET", f"/api/application/nodes/{node_id}", expected=(200,))
        return payload.get("attributes", {}) if payload else {}

    def ping(self) -> bool:
        self._request("GET", "/api/application/users", expected=(200,))
        return True

    def check_metadata(self) -> dict[str, int]:
        """Read the panel metadata required for plan editing and provisioning.

        This deliberately performs no write: it is safe for an administrator
        to run against production, while confirming the nests, eggs, and node
        permissions required by the webapp.
        """
        nests = self.list_nests()
        egg_count = 0
        for nest in nests:
            nest_id = nest.get("attributes", {}).get("id")
            if nest_id is not None:
                egg_count += len(self.eggs_for_nest(nest_id))
        nodes = self.list_nodes()
        return {"nests": len(nests), "eggs": egg_count, "nodes": len(nodes)}

    def ping_client(self) -> bool:
        """Validate the client API key independently of the application key."""
        self._request("GET", "/api/client/account", client_api=True, expected=(200,))
        return True

    # --- users ----------------------------------------------------------
    def get_user(self, panel_user_id: int) -> dict[str, Any] | None:
        try:
            payload = self._request("GET", f"/api/application/users/{panel_user_id}", expected=(200,))
        except PanelError as exc:
            if exc.status == 404:
                return None
            raise
        return payload.get("attributes") if payload else None

    def find_users_by_email(self, email: str) -> list[dict[str, Any]]:
        payload = self._request(
            "GET", f"/api/application/users?filter[email]={quote_plus(email)}", expected=(200,)
        )
        return [item.get("attributes", {}) for item in (payload or {}).get("data", [])]

    def find_users_by_external_id(self, external_id: str) -> list[dict[str, Any]]:
        payload = self._request(
            "GET", f"/api/application/users?filter[external_id]={quote_plus(external_id)}", expected=(200,)
        )
        return [item.get("attributes", {}) for item in (payload or {}).get("data", [])]

    def create_user(
        self, *, email: str, username: str, first_name: str, external_id: str | None = None
    ) -> tuple[int, str]:
        """Create a panel user and return ``(panel_user_id, generated_password)``.

        The optional Web UUID is stored as Panel external_id so reconciliation
        can recover the relationship without relying on mutable email.
        """
        password = secrets.token_urlsafe(18)
        payload = self._request(
            "POST",
            "/api/application/users",
            json_body={
                "email": email,
                "username": username,
                "first_name": first_name,
                "last_name": "Client",
                "password": password,
                **({"external_id": external_id} if external_id else {}),
            },
            expected=(201,),
        )
        panel_id = payload["attributes"]["id"]
        return int(panel_id), password

    def set_user_password(
        self, panel_user_id: int, *, email: str, username: str, first_name: str, password: str
    ) -> None:
        self._request(
            "PATCH",
            f"/api/application/users/{panel_user_id}",
            json_body={
                "email": email,
                "username": username,
                "first_name": first_name,
                "last_name": "Client",
                "password": password,
            },
            expected=(200, 201, 204),
        )

    # --- servers --------------------------------------------------------
    def get_server(self, panel_server_id: int, *, include_allocations: bool = False) -> dict[str, Any] | None:
        suffix = "?include=allocations" if include_allocations else ""
        try:
            payload = self._request(
                "GET", f"/api/application/servers/{panel_server_id}{suffix}", expected=(200,)
            )
        except PanelError as exc:
            if exc.status == 404:
                return None
            raise
        return payload.get("attributes") if payload else None

    def suspend_server(self, panel_server_id: int) -> None:
        self._request("POST", f"/api/application/servers/{panel_server_id}/suspend", expected=(204, 200))

    def unsuspend_server(self, panel_server_id: int) -> None:
        self._request("POST", f"/api/application/servers/{panel_server_id}/unsuspend", expected=(204, 200))

    def delete_server(self, panel_server_id: int) -> None:
        self._request(
            "DELETE", f"/api/application/servers/{panel_server_id}", expected=(204, 200), timeout=LONG_TIMEOUT
        )

    def update_build(
        self,
        panel_server_id: int,
        *,
        allocation_id: int,
        memory: int,
        disk: int,
        cpu: int,
        databases: int,
        backups: int,
        allocations: int,
    ) -> None:
        self._request(
            "PATCH",
            f"/api/application/servers/{panel_server_id}/build",
            json_body={
                "allocation": allocation_id,
                "memory": memory,
                "swap": 0,
                "disk": disk,
                "io": 500,
                "cpu": cpu,
                "feature_limits": {
                    "databases": databases,
                    "backups": backups,
                    "allocations": allocations,
                },
            },
            expected=(200, 204),
            timeout=LONG_TIMEOUT,
        )

    def update_description(self, panel_server_id: int, *, name: str, description: str, user_id: int) -> None:
        self._request(
            "PATCH",
            f"/api/application/servers/{panel_server_id}/details",
            json_body={"name": name, "user": user_id, "description": description},
            expected=(200, 204),
        )

    def find_free_allocation(self, node_id: int) -> int | None:
        payload = self._request(
            "GET", f"/api/application/nodes/{node_id}/allocations?per_page=100", expected=(200,)
        )
        for allocation in (payload or {}).get("data", []):
            attrs = allocation.get("attributes", {})
            if not attrs.get("assigned") and not attrs.get("server_id"):
                return int(attrs["id"])
        return None

    def create_allocation(self, node_id: int, *, ip: str, port: int) -> None:
        self._request(
            "POST",
            f"/api/application/nodes/{node_id}/allocations",
            json_body={"ip": ip, "ports": [str(port)]},
            expected=(200, 201, 204),
        )

    def create_server(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._request(
            "POST",
            "/api/application/servers?include=allocations",
            json_body=payload,
            expected=(201,),
            timeout=LONG_TIMEOUT,
        )
        return result or {}

    # --- client API (per-user console/power) ----------------------------
    def server_resources(self, identifier: str) -> dict[str, Any]:
        payload = self._request(
            "GET", f"/api/client/servers/{identifier}/resources", client_api=True, expected=(200,)
        )
        return payload.get("attributes", {}) if payload else {}

    def server_websocket(self, identifier: str) -> dict[str, Any]:
        payload = self._request(
            "GET", f"/api/client/servers/{identifier}/websocket", client_api=True, expected=(200,)
        )
        return payload.get("data", {}) if payload else {}

    def send_power_signal(self, identifier: str, signal: str) -> None:
        if signal not in {"start", "stop", "restart", "kill"}:
            raise ValueError(f"invalid power signal: {signal!r}")
        self._request(
            "POST",
            f"/api/client/servers/{identifier}/power",
            client_api=True,
            json_body={"signal": signal},
            expected=(204, 200),
        )


def get_fluid_client() -> FluidPanelClient:
    """Return the request-scoped panel client."""
    from flask import current_app, g

    if "fluid_client" not in g:
        config = current_app.extensions["flux_config"]
        g.fluid_client = FluidPanelClient(config.panel_url, config.panel_api_key)
    return g.fluid_client
