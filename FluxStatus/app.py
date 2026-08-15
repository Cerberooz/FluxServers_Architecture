import os
from datetime import datetime, timezone

import requests
from flask import Flask, render_template

app = Flask(__name__)

# ---------- CONFIGURATION ----------
PANEL_URL = os.environ.get("PANEL_URL", "https://panel.fluxservers.cloud").rstrip("/")
API_KEY = os.environ.get("PANEL_API_KEY", "")
# -----------------------------------

REGION_ORDER = ["Europe", "Asia", "North America", "Oceania", "South America", "Africa", "Other"]

# Match both a location's full name (for example "Frankfurt, Germany") and
# common location short codes. Add an entry when a new country is added.
LOCATION_REGIONS = {
    "Europe": (
        ("de", ("germany", "frankfurt", "de-", "de_", "deu")),
        ("fr", ("france", "paris", "fr-", "fr_", "fra")),
        ("nl", ("netherlands", "amsterdam", "nl-", "nl_", "nld")),
        ("gb", ("united kingdom", "uk", "london", "england", "gb-", "gb_")),
        ("fi", ("finland", "helsinki", "fi-", "fi_", "fin")),
        ("se", ("sweden", "stockholm", "se-", "se_", "swe")),
        ("pl", ("poland", "warsaw", "pl-", "pl_", "pol")),
        ("es", ("spain", "madrid", "es-", "es_", "esp")),
        ("it", ("italy", "milan", "it-", "it_", "ita")),
        ("ch", ("switzerland", "zurich", "ch-", "ch_", "che")),
        ("no", ("norway", "oslo", "no-", "no_", "nor")),
    ),
    "Asia": (
        ("sg", ("singapore", "sg-", "sg_", "sgp")),
        ("jp", ("japan", "tokyo", "osaka", "jp-", "jp_", "jpn")),
        ("hk", ("hong kong", "hk-", "hk_", "hkg")),
        ("in", ("india", "mumbai", "delhi", "in-", "in_", "ind")),
        ("kr", ("korea", "seoul", "kr-", "kr_", "kor")),
        ("id", ("indonesia", "jakarta", "id-", "id_", "idn")),
    ),
    "North America": (
        ("us", ("united states", "usa", "us-", "us_", "new york", "dallas", "miami", "los angeles", "chicago")),
        ("ca", ("canada", "toronto", "montreal", "ca-", "ca_", "can")),
    ),
    "Oceania": (("au", ("australia", "sydney", "melbourne", "au-", "au_", "aus")),),
    "South America": (("br", ("brazil", "sao paulo", "são paulo", "br-", "br_", "bra")),),
    "Africa": (("za", ("south africa", "johannesburg", "cape town", "za-", "za_", "zaf")),),
}


def fetch_resource(path):
    """Fetch an Application API collection, or return None on failure."""
    if not API_KEY:
        print("PANEL_API_KEY is not configured")
        return None
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "Application/vnd.pterodactyl.v1+json",
    }
    try:
        resp = requests.get(f"{PANEL_URL}/api/application/{path}", headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", [])
    except requests.exceptions.RequestException as e:
        print(f"API error fetching {path}: {e}")
        return None

def location_region(location_name: str):
    """Return a display region and ISO country code from a panel location."""
    value = location_name.casefold()
    for region, countries in LOCATION_REGIONS.items():
        for country_code, aliases in countries:
            if any(alias in value for alias in aliases):
                return region, country_code
    return "Other", ""


def display_location(location_name: str) -> str:
    """Use the customer-facing location format: Country, City."""
    return location_name.replace(" - ", ", ").replace(" — ", ", ")


def capacity(total, used):
    """Calculate a safe, display-ready capacity summary in panel units (MB)."""
    total = max(int(total or 0), 0)
    used = max(int(used or 0), 0)
    if total == 0:
        return {"total": 0, "used": used, "free": 0, "free_percent": 0.0, "known": False}

    free = max(total - used, 0)
    return {
        "total": total,
        "used": used,
        "free": free,
        "free_percent": round((free / total) * 100, 2),
        "known": True,
    }


def process_nodes(nodes_raw, locations):
    """Extract relevant fields and determine status."""
    processed = []
    for node in nodes_raw:
        attrs = node.get("attributes", {})
        maintenance = attrs.get("maintenance_mode", False)
        location = locations.get(attrs.get("location_id"), {})
        location_name = location.get("long") or location.get("short") or f"Location {attrs.get('location_id', 'N/A')}"
        location_name = display_location(location_name)
        region, country_code = location_region(location_name)
        allocated = attrs.get("allocated_resources") or {}
        # "Active" if NOT in maintenance, else "Offline"
        status = "offline" if maintenance else "active"
        processed.append({
            "id": attrs.get("id", "?"),
            "name": attrs.get("name", "Unnamed Node"),
            "description": attrs.get("description", "No description"),
            "location_id": attrs.get("location_id", "N/A"),
            "location_name": location_name,
            "region": region,
            "flag_url": f"https://flagcdn.com/w40/{country_code}.png" if country_code else "",
            "memory": capacity(attrs.get("memory"), allocated.get("memory")),
            "public": attrs.get("public", True),
            "created_at": attrs.get("created_at", ""),
            "status": status,
            "maintenance_mode": maintenance,
        })
    return processed


def group_nodes(nodes):
    groups = {region: [] for region in REGION_ORDER}
    for node in nodes:
        groups.setdefault(node["region"], []).append(node)
    return [
        {"name": region, "nodes": sorted(groups[region], key=lambda node: (node["location_name"], node["name"]))}
        for region in REGION_ORDER
        if groups.get(region)
    ]

@app.route("/")
def status_page():
    raw = fetch_resource("nodes")

    if raw is None:
        # API call failed
        return render_template(
            "status.html",
            error=True,
            error_message="Could not connect to Pterodactyl panel. Check your settings or panel status.",
            nodes=[],
            total=0,
            active_count=0,
            progress=0
        )

    location_raw = fetch_resource("locations") or []
    locations = {
        item.get("attributes", {}).get("id"): item.get("attributes", {})
        for item in location_raw
    }
    nodes = process_nodes(raw, locations)
    node_groups = group_nodes(nodes)
    total = len(nodes)
    active_count = sum(1 for n in nodes if n["status"] == "active")
    progress = (active_count / total * 100) if total > 0 else 0

    return render_template(
        "status.html",
        error=False,
        error_message=None,
        nodes=nodes,
        node_groups=node_groups,
        total=total,
        active_count=active_count,
        progress=round(progress, 1),
        now=datetime.now(timezone.utc),
    )

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
