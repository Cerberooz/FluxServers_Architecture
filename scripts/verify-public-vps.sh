#!/usr/bin/env sh
set -eu

root_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root_dir"

docker compose -f compose.public.yaml config -q

for service in redis status web web-sync; do
    if ! docker compose -f compose.public.yaml ps --services --status running | grep -qx "$service"; then
        echo "Service is not running: $service" >&2
        exit 1
    fi
done

curl -fsSI http://127.0.0.1:18081 >/dev/null
curl -fsSI http://127.0.0.1:18082 >/dev/null
docker compose -f compose.public.yaml exec -T web flask --app app.py check-db
docker compose -f compose.public.yaml exec -T status python -c 'import os, requests; response = requests.get(os.environ["PANEL_URL"].rstrip("/") + "/api/application/nodes", headers={"Authorization": "Bearer " + os.environ["PANEL_API_KEY"], "Accept": "Application/vnd.pterodactyl.v1+json"}, timeout=10); response.raise_for_status(); print("Status-to-Panel API: OK")'

echo "Public VPS verification passed."
