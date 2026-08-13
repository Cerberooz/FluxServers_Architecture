# Hanodactyl v4 Compatibility Report

## Overview

Hanodactyl v4 is not directly Pterodactyl-compatible, so FluxWeb now includes a
separate adapter selected with `PANEL_TYPE=hanodactyl`.

FluxWeb is currently built against a Pterodactyl-style API. Hanodactyl v4 has similar features, but its API paths, authentication model, and response formats are different.

## What Hanodactyl v4 has

Hanodactyl v4 appears to support:

- users
- nodes
- allocations
- eggs / nests
- servers
- power actions
- stats / logs
- console websocket support

So the required concepts exist.

## What does not match

FluxWeb expects:

- `/api/application/...`
- `/api/client/...`
- Pterodactyl-style bearer key authentication
- Pterodactyl-style `data` / `attributes` response payloads

Hanodactyl v4 currently uses:

- `/api/admin/...`
- `/api/servers/...`
- `/api/auth/...`
- different authentication behavior
- different request / response shapes

## Result after the adapter

The adapter covers the panel operations currently used by FluxWeb:

- connection test
- loading nodes and eggs in admin
- panel user creation and password rotation
- provisioning with node, egg, allocation, resources, and environment
- suspend / unsuspend / delete actions
- lifecycle synchronization
- live stats, power actions, and console websocket URL generation

FluxWeb now provisions Hanodactyl servers through the configured administrator
account only. The panel accepts an explicit `owner_id` from administrators, so
FluxWeb no longer logs in as the customer to create a server. Browser console
access uses a short-lived server-scoped console token instead of exposing the
administrator JWT to the customer browser.

Hanodactyl-only features such as files, backups, schedules, and node management
remain panel features because FluxWeb has no corresponding web-app workflow for
them yet.

## Conclusion

Hanodactyl v4 is now usable by FluxWeb through the adapter, but it still
requires the Hanodactyl administrator credentials described below.

## Recommended next step

Set these deployment variables:

```text
PANEL_TYPE=hanodactyl
PTERODACTYL_URL=https://your-panel.example.com
PANEL_USERNAME=your-hanodactyl-admin
PANEL_PASSWORD=your-hanodactyl-admin-password
```

Hanodactyl itself now refuses unsafe defaults. The panel requires:

```text
HANODACTYL_SECRET_KEY=<32+ random characters>
HANODACTYL_BOOTSTRAP_ADMIN_PASSWORD=<strong password>
```

The daemon requires:

```text
UPDUL_AUTH_TOKEN=<32+ random characters>
```

SQLite remains supported for the panel database. That is acceptable for a small
single-node deployment, but keep these constraints in mind:

- keep the SQLite file on persistent local disk, not an ephemeral container path
- back it up regularly; it contains panel users, nodes, allocations, servers,
  schedules, backups metadata, and daemon tokens
- do not run multiple panel API processes against the same SQLite file under
  heavy write load
- migrating to Postgres later is still recommended if the panel becomes
  multi-node or high-traffic

The existing `PTERODACTYL_API_KEY` and `PTERODACTYL_CLIENT_KEY` settings remain
available when `PANEL_TYPE=pterodactyl`.

## Repo housekeeping

Also completed:

- `hanodactyl_v4/` was added to `.gitignore`
