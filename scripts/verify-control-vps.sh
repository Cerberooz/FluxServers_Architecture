#!/usr/bin/env sh
set -eu

root_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root_dir"

docker compose -f compose.control.yaml config -q

for service in database redis panel worker scheduler; do
    if ! docker compose -f compose.control.yaml ps --services --status running | grep -qx "$service"; then
        echo "Service is not running: $service" >&2
        exit 1
    fi
done

curl -fsSI http://127.0.0.1:18080 >/dev/null
docker compose -f compose.control.yaml exec -T panel php artisan migrate:status --no-interaction >/dev/null

echo "Control VPS verification passed."
