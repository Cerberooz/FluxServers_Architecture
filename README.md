# Flux Servers deployment

This directory is the deployment root for all three applications:

| Directory | Service | Local-only port | Public hostname |
| --- | --- | ---: | --- |
| `FluxPanel` | FluidPanel, worker, scheduler | 18080 | `panel.fluxservers.cloud` |
| `Flux Status` | status page | 18081 | `status.fluxservers.cloud` |
| `FluxWeb` | customer website and billing | 18082 | `fluxservers.cloud` and `www.fluxservers.cloud` |
| root `compose.yaml` | Panel MariaDB and shared Redis | private Docker network | none |

The host reverse proxy is the only service listening on ports 80 and 443. Wings remains on its existing host port 8080 and is not managed by this Compose file.

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
- `FluxWeb/.env`

For FluxWeb production, ensure `FLASK_ENV=production`, `BASE_URL=https://fluxservers.cloud`, its Supabase/Postgres (`DATABASE_URL` and `DIRECT_URL`) values, Supabase Auth values, and its Panel Application API key are configured. FluxWeb does **not** use the internal MariaDB container. The Compose stack supplies its private `FLUID_URL=http://panel` and Redis URL at runtime.

## Start or update every service

```bash
cd ~/FluxServers
sudo docker compose up -d --build
sudo docker compose exec panel php artisan migrate --force
sudo docker compose exec panel php artisan optimize
sudo docker compose exec web flask --app app.py db upgrade
sudo docker compose ps
```

The Web migration uses `DIRECT_URL` from `FluxWeb/.env`; it does not touch the Panel MariaDB database.

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

Keep the existing TLS configuration and proxy each hostname to its matching localhost port. A complete HTTP template is provided at `deploy/nginx/fluxservers.conf.example`; run Certbot after DNS points to the VPS so it adds TLS to those blocks.

The three upstream mappings are:

```nginx
server_name panel.fluxservers.cloud;
location / { proxy_pass http://127.0.0.1:18080; }

server_name status.fluxservers.cloud;
location / { proxy_pass http://127.0.0.1:18081; }

server_name fluxservers.cloud www.fluxservers.cloud;
location / { proxy_pass http://127.0.0.1:18082; }
```

Each `location` should also include the existing `Host`, `X-Real-IP`, `X-Forwarded-For`, and `X-Forwarded-Proto` headers. Run Certbot for the website hostname after its DNS A records point to the VPS.

## Repository structure

`FluxPanel` and `FluxWeb` still contain their own `.git` folders. This preserves their existing Git histories, but means this parent directory is a deployment workspace rather than a true single Git repository. Do not delete those `.git` folders until you deliberately choose a history-migration strategy.

Within this workspace, all production deployment material lives at the root: `compose.yaml`, `.env.example`, `scripts/`, and `deploy/nginx/`. App folders contain application source plus only the Dockerfiles needed to build that app.
