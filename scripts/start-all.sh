#!/usr/bin/env sh
set -eu

# Start the complete single-VPS stack safely. This never removes volumes or
# runs `compose down`, so the Panel MariaDB, Redis, and uploads remain intact.
#
# Usage:
#   sudo ./scripts/start-all.sh           # start existing images/containers
#   sudo ./scripts/start-all.sh --build   # rebuild images after git pull

root_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root_dir"

build=false
if [ "${1:-}" = "--build" ]; then
    build=true
elif [ "$#" -gt 0 ]; then
    echo "Usage: $0 [--build]" >&2
    exit 64
fi

if [ ! -f .env ]; then
    ./scripts/create-compose-env.sh
fi

for env_file in FluxPanel/.env FluxWeb/.env.production FluxStatus/.env; do
    if [ ! -f "$env_file" ]; then
        echo "Missing $env_file. Configure it before starting the stack." >&2
        exit 1
    fi
done

memory_kib=$(awk '/MemTotal/ { print $2 }' /proc/meminfo)
if [ "${memory_kib:-0}" -lt 1800000 ]; then
    echo "Warning: this host has less than 2 GB RAM. All eight services can start, but 1 GB is not reliable for production." >&2
    echo "Use a 2 GB+ VPS (preferably 4 GB) or add swap and monitor memory closely." >&2
fi

docker compose config -q

if [ "$build" = true ]; then
    # Build one image at a time to avoid simultaneous build memory spikes.
    docker compose build panel
    docker compose build worker
    docker compose build scheduler
    docker compose build status
    docker compose build web
fi

docker compose up -d database redis

attempt=0
until docker compose exec -T database healthcheck.sh --connect --innodb_initialized >/dev/null 2>&1 \
    && docker compose exec -T redis redis-cli ping >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 30 ]; then
        echo "MariaDB or Redis did not become healthy within 60 seconds." >&2
        docker compose ps >&2
        exit 1
    fi
    sleep 2
done

# Start the Panel before dependent services so migrations run against a ready
# app and worker/scheduler jobs do not process an outdated schema.
docker compose up -d --no-deps panel
attempt=0
until docker compose exec -T panel php artisan about --no-ansi >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 30 ]; then
        echo "Panel did not become ready within 60 seconds." >&2
        docker compose logs --tail=100 panel >&2
        exit 1
    fi
    sleep 2
done

docker compose exec -T panel php artisan migrate --force
docker compose exec -T panel php artisan optimize

docker compose up -d --no-deps worker scheduler status web
docker compose exec -T web flask --app app.py db upgrade
docker compose up -d --no-deps web-sync

docker compose ps
echo "All Flux Servers containers are running."
