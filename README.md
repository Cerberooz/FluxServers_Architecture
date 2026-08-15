# Flux Servers deployment

This directory is the deployment root for all three applications. You can run
everything on one VPS with `compose.yaml`, or split the business stack across
two small VPSes with the role-specific Compose files.

| Directory | Service | Local-only port | Public hostname |
| --- | --- | ---: | --- |
| `FluxPanel` | FluidPanel, worker, scheduler | 18080 | `panel.fluxservers.cloud` |
| `Flux Status` | status page | 18081 | `status.fluxservers.cloud` |
| `FluxWeb` | customer website and billing | 18082 | `fluxservers.cloud` and `www.fluxservers.cloud` |
| root `compose.yaml` | Panel MariaDB and shared Redis | private Docker network | none |

The host reverse proxy is the only service listening on ports 80 and 443. Wings
remains on the game node and is not managed by these Compose files.

## Recommended three-VPS layout

Use your servers like this:

| VPS | Purpose | Compose file | Script |
| --- | --- | --- | --- |
| 1 GB / 50 GB | Control plane: Panel, Panel MariaDB, Panel Redis, worker, scheduler | `compose.control.yaml` | `scripts/setup-control-vps.sh` |
| 1 GB / 50 GB | Public business apps: website, status page, web Redis, sync worker | `compose.public.yaml` | `scripts/setup-public-vps.sh` |
| 48 GB / 250 GB | Customer game servers only: Wings and Minecraft servers | none from this repo | Wings/systemd |

This keeps the 48 GB machine focused on customer servers and keeps the website
separate from the Panel/database VPS. FluxWeb still uses Supabase/Postgres; it
does not use the Panel MariaDB container.

## First-time root configuration

Create a root `.env` from the values already used in `FluxPanel/.env`. The helper does this without printing the passwords:

```bash
cd ~/FluxServers
chmod +x scripts/create-compose-env.sh
./scripts/create-compose-env.sh
```

If you create it manually instead, use `.env.example` and set the root variables as follows:

- `PANEL_DB_DATABASE` = `DB_DATABASE`
- `PANEL_DB_USERNAME` = `DB_USERNAME`
- `PANEL_DB_PASSWORD` = `DB_PASSWORD`
- `PANEL_MYSQL_ROOT_PASSWORD` = `MYSQL_ROOT_PASSWORD`

Keep the three application environment files in their app folders:

- `FluxPanel/.env`
- `Flux Status/.env`
- `FluxWeb/.env.production`

For FluxWeb production, ensure `FLASK_ENV=production`, `BASE_URL=https://fluxservers.cloud`, its Supabase/Postgres (`DATABASE_URL` and `DIRECT_URL`) values, Supabase Auth values, and its Panel Application API key are configured. FluxWeb does **not** use the internal MariaDB container. In the split-VPS layout, `FLUID_URL` should be `https://panel.fluxservers.cloud`; in the single-VPS layout, Compose overrides it internally.

### Minecraft protected ingress and customer subdomains

Set this in `FluxPanel/.env` before starting the Panel:

```env
MINECRAFT_PUBLIC_HOST=play.fluxservers.cloud
```

This must be the Sucura-protected Minecraft hostname, never a Wings/node IP.
Customer allocations are shown as `play.fluxservers.cloud:<port>`. Customer
subdomains are created as DNS-only SRV records targeting that hostname, so no
per-customer A record exposes the origin node. In **Admin → Subdomain Manager**,
store a Cloudflare token with only **Zone:DNS:Edit** and **Zone:Zone:Read** for
the relevant zones, then register each root domain and its zone ID.

## Start or update every service

For the recommended two-app-VPS split, run these instead:

```bash
# On the control VPS for panel.fluxservers.cloud:
cd ~/FluxServers
chmod +x scripts/*.sh
sudo ./scripts/setup-control-vps.sh
sudo ./scripts/verify-control-vps.sh
```

```bash
# On the public VPS for fluxservers.cloud and status.fluxservers.cloud:
cd ~/FluxServers
chmod +x scripts/*.sh
sudo ./scripts/setup-public-vps.sh
sudo ./scripts/verify-public-vps.sh
```

On the public VPS, set the Panel URL used by FluxWeb and Flux Status to the
public Panel hostname because the Panel is no longer on the same Docker network:

```env
FLUID_URL=https://panel.fluxservers.cloud
PANEL_URL=https://panel.fluxservers.cloud
```

Put `FLUID_URL` in `FluxWeb/.env.production` and `PANEL_URL` in
`Flux Status/.env`. `scripts/setup-public-vps.sh` checks those values before it
starts the public apps.

If you intentionally want all business services on one VPS, use the original
single-stack command. It starts MariaDB, Redis, Panel, worker, scheduler,
Status, Web, and Web Sync without removing persistent data:

```bash
cd ~/FluxServers
chmod +x scripts/*.sh
sudo ./scripts/start-all.sh --build
sudo ./scripts/verify-stack.sh
```

For ordinary restarts without rebuilding images, run:

```bash
sudo ./scripts/start-all.sh
```

The whole stack can technically run on a 1 GB VPS, but it is not a reliable
production capacity: MariaDB plus three Panel PHP processes, Flask Web/Status,
and Redis can exhaust memory during builds, migrations, or traffic. Use at
least 2 GB RAM (4 GB preferred), or add swap as a temporary safeguard.

The Web migration uses `DIRECT_URL` from `FluxWeb/.env.production`; it does not touch the Panel MariaDB database.

### Start only one layer

```bash
# Persistent Panel data only: MariaDB + Redis.
sudo ./scripts/setup-database.sh

# Panel, worker, scheduler, Status, Web, and Web sync only.
# Requires the data layer above to already be healthy.
sudo ./scripts/setup-apps.sh
```

`setup-apps.sh` does not start or recreate MariaDB/Redis. FluxWeb continues to use its external Supabase/Postgres database in both modes.

Use `sudo docker compose down` only when you intentionally want to stop the stack. Never add `-v` in production: the Panel database, Redis, and uploads are persistent volumes.

### One-time move from the old Panel-only Compose file

The first switch needs a brief interruption because both stacks use Panel port `18080`. Run this **before pulling the cleanup version**, while the old `FluxPanel/compose.yaml` file still exists:

```bash
cd ~/FluxServers/FluxPanel
sudo docker compose down

cd ~/FluxServers
./scripts/create-compose-env.sh   # only if the root .env does not exist yet
sudo docker compose config        # validates configuration without starting it
sudo docker compose up -d --build
sudo docker compose exec panel php artisan migrate --force
sudo docker compose exec panel php artisan optimize
sudo docker compose exec web flask --app app.py db upgrade
```

`down` without `-v` stops only the previous Panel containers. It does not stop Wings and preserves the named MariaDB, Redis, and Panel storage volumes. After the unified stack is working, all future commands run only from `~/FluxServers`.

## Host Nginx routes

Keep the existing TLS configuration and proxy each hostname to its matching
localhost port. A complete HTTP template is provided at
`deploy/nginx/fluxservers.conf.example`; run Certbot after DNS points to the VPS
so it adds TLS to those blocks.

The three upstream mappings are:

```nginx
server_name panel.fluxservers.cloud;
location / { proxy_pass http://127.0.0.1:18080; }

server_name status.fluxservers.cloud;
location / { proxy_pass http://127.0.0.1:18081; }

server_name fluxservers.cloud www.fluxservers.cloud;
location / { proxy_pass http://127.0.0.1:18082; }
```

Each `location` should also include the existing `Host`, `X-Real-IP`,
`X-Forwarded-For`, and `X-Forwarded-Proto` headers. With the two-VPS layout,
put only the Panel route on the control VPS and put the Status/Web routes on the
public VPS. Run Certbot for each hostname after its DNS A record points to the
correct VPS.

## Repository structure

This workspace is a single deployment repository. All production deployment
material lives at the root: `compose.yaml`, `compose.control.yaml`,
`compose.public.yaml`, `.env.example`, `scripts/`, and `deploy/nginx/`. App
folders contain application source plus only the Dockerfiles needed to build
that app.
