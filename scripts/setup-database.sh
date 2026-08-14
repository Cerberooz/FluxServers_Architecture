#!/usr/bin/env sh
set -eu

# Start only the persistent data layer. Redis is included because the Panel
# uses it for sessions, cache, and queued jobs alongside MariaDB.
root_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root_dir"

if [ ! -f .env ]; then
    ./scripts/create-compose-env.sh
fi

docker compose config -q
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

echo "MariaDB and Redis are healthy."
