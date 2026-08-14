#!/usr/bin/env sh
set -eu

# Run this on the 1 GB VPS that hosts fluxservers.cloud and status.fluxservers.cloud.
root_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root_dir"

for env_file in FluxWeb/.env.production "Flux Status/.env"; do
    if [ ! -f "$env_file" ]; then
        echo "Missing $env_file. Configure that application before starting the public VPS." >&2
        exit 1
    fi
done

require_env_key() {
    file=$1
    key=$2

    if ! grep -Eq "^${key}=.+" "$file"; then
        echo "Missing $key in $file." >&2
        exit 1
    fi
}

env_value() {
    file=$1
    key=$2

    grep -E "^${key}=" "$file" | tail -n 1 | cut -d= -f2-
}

require_any_env_key() {
    file=$1
    first=$2
    second=$3

    if ! grep -Eq "^(${first}|${second})=.+" "$file"; then
        echo "Missing $first or $second in $file." >&2
        exit 1
    fi
}

require_env_key "Flux Status/.env" PANEL_URL
require_env_key "Flux Status/.env" PANEL_API_KEY
require_any_env_key FluxWeb/.env.production FLUID_URL PANEL_URL
require_any_env_key FluxWeb/.env.production FLUID_API_KEY PANEL_API_KEY
require_env_key FluxWeb/.env.production DATABASE_URL
require_env_key FluxWeb/.env.production DIRECT_URL

status_panel_url=$(env_value "Flux Status/.env" PANEL_URL)
web_panel_url=$(env_value FluxWeb/.env.production FLUID_URL || true)
if [ -z "$web_panel_url" ]; then
    web_panel_url=$(env_value FluxWeb/.env.production PANEL_URL)
fi

case "$status_panel_url" in
    http://panel|http://panel/*|http://localhost*|http://127.0.0.1*)
        echo "Flux Status/.env PANEL_URL must be the public Panel URL on the public VPS." >&2
        echo "Use: PANEL_URL=https://panel.fluxservers.cloud" >&2
        exit 1
        ;;
esac

case "$web_panel_url" in
    http://panel|http://panel/*|http://localhost*|http://127.0.0.1*)
        echo "FluxWeb/.env.production FLUID_URL/PANEL_URL must be the public Panel URL on the public VPS." >&2
        echo "Use: FLUID_URL=https://panel.fluxservers.cloud" >&2
        exit 1
        ;;
esac

docker compose -f compose.public.yaml config -q
docker compose -f compose.public.yaml build status web web-sync
docker compose -f compose.public.yaml up -d redis status web web-sync

attempt=0
until docker compose -f compose.public.yaml exec -T redis redis-cli ping >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 30 ]; then
        echo "Redis did not become healthy within 60 seconds." >&2
        docker compose -f compose.public.yaml ps >&2
        exit 1
    fi
    sleep 2
done

docker compose -f compose.public.yaml exec -T web flask --app app.py db upgrade
docker compose -f compose.public.yaml ps
