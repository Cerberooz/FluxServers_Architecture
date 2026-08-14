#!/usr/bin/env sh
set -eu

# Run this on the 1 GB VPS that hosts panel.fluxservers.cloud.
root_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root_dir"

if [ ! -f FluxPanel/.env ]; then
    echo "Missing FluxPanel/.env. Configure the Panel before starting the control VPS." >&2
    exit 1
fi

if [ ! -f .env ]; then
    ./scripts/create-compose-env.sh
fi

docker compose -f compose.control.yaml config -q
docker compose -f compose.control.yaml build panel worker scheduler
docker compose -f compose.control.yaml up -d database redis panel worker scheduler

attempt=0
until docker compose -f compose.control.yaml exec -T database healthcheck.sh --connect --innodb_initialized >/dev/null 2>&1 \
    && docker compose -f compose.control.yaml exec -T redis redis-cli ping >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 30 ]; then
        echo "MariaDB or Redis did not become healthy within 60 seconds." >&2
        docker compose -f compose.control.yaml ps >&2
        exit 1
    fi
    sleep 2
done

docker compose -f compose.control.yaml exec -T panel php artisan migrate --force
docker compose -f compose.control.yaml exec -T panel php artisan optimize
docker compose -f compose.control.yaml ps
