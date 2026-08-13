#!/usr/bin/env sh
set -eu

# Create the root Compose environment from the database credentials already
# used by FluidPanel. This does not print passwords and refuses to overwrite
# an existing root .env file.
root_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
panel_env="$root_dir/FluxPanel/.env"
root_env="$root_dir/.env"

if [ -f "$root_env" ]; then
    echo "Refusing to overwrite $root_env. Edit it directly if a value needs changing." >&2
    exit 1
fi

if [ ! -f "$panel_env" ]; then
    echo "Missing $panel_env. Configure FluidPanel first." >&2
    exit 1
fi

read_env() {
    key="$1"
    value=$(sed -n "s/^${key}=//p" "$panel_env" | tail -n 1)
    if [ -z "$value" ]; then
        echo "Missing $key in $panel_env." >&2
        exit 1
    fi
    printf '%s' "$value"
}

umask 077
{
    printf 'PANEL_DB_DATABASE=%s\n' "$(read_env DB_DATABASE)"
    printf 'PANEL_DB_USERNAME=%s\n' "$(read_env DB_USERNAME)"
    printf 'PANEL_DB_PASSWORD=%s\n' "$(read_env DB_PASSWORD)"
    printf 'PANEL_MYSQL_ROOT_PASSWORD=%s\n' "$(read_env MYSQL_ROOT_PASSWORD)"
    printf 'WEB_SYNC_INTERVAL=300\n'
} > "$root_env"

echo "Created $root_env with permissions restricted to its owner."
