#!/usr/bin/env sh
set -eu

# Backwards-compatible deployment entrypoint. See start-all.sh for the
# documented single-VPS command and optional --build mode.
exec "$(dirname -- "$0")/start-all.sh" "$@"
