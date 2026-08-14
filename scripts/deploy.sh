#!/usr/bin/env sh
set -eu

# Deploy the whole Flux Servers stack from this repository root. Run with sudo
# on the VPS when the Docker socket requires it.
root_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root_dir"

./scripts/setup-database.sh
./scripts/setup-apps.sh
