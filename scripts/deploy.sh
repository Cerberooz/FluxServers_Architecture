#!/usr/bin/env sh
set -eu

# Deploy the whole Flux Servers stack from this repository root. Run with sudo
# on the VPS when the Docker socket requires it.
root_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root_dir"

if [ ! -f .env ]; then
    ./scripts/create-compose-env.sh
fi

docker compose config -q
docker compose up -d --build

# Panel state is internal MariaDB. FluxWeb migrations use its separately
# configured DIRECT_URL (Supabase/Postgres), never the Panel database.
docker compose exec panel php artisan migrate --force
docker compose exec panel php artisan optimize
docker compose exec web flask --app app.py db upgrade
docker compose ps
