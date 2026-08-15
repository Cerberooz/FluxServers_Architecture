#!/usr/bin/env sh
set -eu

# Build and start the application layer only. MariaDB and Redis must already
# be running; use setup-database.sh first on a new or stopped host.
root_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root_dir"

for env_file in FluxPanel/.env FluxWeb/.env.production FluxStatus/.env; do
    if [ ! -f "$env_file" ]; then
        echo "Missing $env_file. Configure that application before starting it." >&2
        exit 1
    fi
done

if ! docker compose exec -T database healthcheck.sh --connect --innodb_initialized >/dev/null 2>&1 \
    || ! docker compose exec -T redis redis-cli ping >/dev/null 2>&1; then
    echo "MariaDB and Redis must be healthy first. Run: sudo ./scripts/setup-database.sh" >&2
    exit 1
fi

docker compose config -q
docker compose build panel status web
docker compose up -d --no-deps panel worker scheduler status web web-sync

# These target two independent databases: Panel uses internal MariaDB while
# FluxWeb uses DIRECT_URL for its external Supabase/Postgres migrations.
docker compose exec -T panel php artisan migrate --force
docker compose exec -T panel php artisan optimize
docker compose exec -T web flask --app app.py db upgrade
docker compose ps
