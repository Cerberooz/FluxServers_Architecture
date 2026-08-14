#!/usr/bin/env sh
set -eu

# Verify the running unified stack. This checks the private service links and
# the two independent databases without printing any secrets.
root_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root_dir"

docker compose config -q

for service in database redis panel worker scheduler status web web-sync; do
    if ! docker compose ps --services --status running | grep -qx "$service"; then
        echo "Service is not running: $service" >&2
        exit 1
    fi
done

curl -fsSI http://127.0.0.1:18080 >/dev/null
curl -fsSI http://127.0.0.1:18081 >/dev/null
curl -fsSI http://127.0.0.1:18082 >/dev/null

docker compose exec panel php artisan migrate:status --no-interaction >/dev/null
docker compose exec web flask --app app.py check-db
docker compose exec status python -c 'import os, requests; response = requests.get(os.environ["PANEL_URL"].rstrip("/") + "/api/application/nodes", headers={"Authorization": "Bearer " + os.environ["PANEL_API_KEY"], "Accept": "Application/vnd.pterodactyl.v1+json"}, timeout=10); response.raise_for_status(); print("Status-to-Panel API: OK")'

echo "Flux Servers stack verification passed."
