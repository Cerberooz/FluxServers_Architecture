#!/usr/bin/env bash
# One-command local start for FluxWeb (macOS / Linux / Git Bash).
#
#   ./run.sh           start the dev server
#   ./run.sh --test    run the test suite
#   ./run.sh --lint    run ruff + black --check
#   ./run.sh --fresh   rebuild the virtualenv
set -euo pipefail

cd "$(dirname "$0")"

VENV_DIR=".venv"
PORT="${PORT:-27003}"
MODE="run"

for arg in "$@"; do
  case "$arg" in
    --test)  MODE="test" ;;
    --lint)  MODE="lint" ;;
    --fresh) rm -rf "$VENV_DIR" ;;
    --port=*) PORT="${arg#*=}" ;;
    *) echo "Unknown option: $arg" >&2; exit 1 ;;
  esac
done

cyan()  { printf '\n\033[36m==> %s\033[0m\n' "$1"; }
green() { printf '    \033[32m%s\033[0m\n' "$1"; }
yellow(){ printf '    \033[33m%s\033[0m\n' "$1"; }
red()   { printf '    \033[31m%s\033[0m\n' "$1"; }

# --- 1. Python ----------------------------------------------------------
cyan "Checking Python"
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    # Skip the Windows Store stub, which is not a real interpreter.
    src="$(command -v "$candidate")"
    case "$src" in *WindowsApps*) continue ;; esac
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
      PYTHON="$candidate"
      break
    fi
  fi
done

if [ -z "$PYTHON" ]; then
  red "No usable Python 3.11+ found."
  echo
  echo "    macOS:  brew install python@3.12"
  echo "    Debian: sudo apt install python3.12 python3.12-venv"
  echo "    Windows: winget install Python.Python.3.12  (then use run.ps1)"
  exit 1
fi
green "Using $PYTHON ($($PYTHON --version))"

# --- 2. Virtualenv ------------------------------------------------------
if [ ! -x "$VENV_DIR/bin/python" ]; then
  cyan "Creating virtualenv (.venv)"
  "$PYTHON" -m venv "$VENV_DIR"
  green "Created .venv"
else
  cyan "Virtualenv present"
  green ".venv"
fi
VPY="$VENV_DIR/bin/python"

# --- 3. Dependencies ----------------------------------------------------
REQ_FILE="requirements.txt"
if [ "$MODE" != "run" ]; then REQ_FILE="requirements-dev.txt"; fi

STAMP_FILE="$VENV_DIR/.deps-stamp"
if command -v sha256sum >/dev/null 2>&1; then
  REQ_HASH="$(sha256sum "$REQ_FILE" | cut -d' ' -f1)"
else
  REQ_HASH="$(shasum -a 256 "$REQ_FILE" | cut -d' ' -f1)"
fi

if [ ! -f "$STAMP_FILE" ] || [ "$(cat "$STAMP_FILE")" != "$REQ_FILE:$REQ_HASH" ]; then
  cyan "Installing dependencies from $REQ_FILE"
  "$VPY" -m pip install --upgrade pip --quiet
  "$VPY" -m pip install -r "$REQ_FILE" --quiet
  echo "$REQ_FILE:$REQ_HASH" > "$STAMP_FILE"
  green "Dependencies installed"
else
  cyan "Dependencies up to date"
  green "matches $REQ_FILE"
fi

# --- 4. .env ------------------------------------------------------------
if [ ! -f .env ]; then
  cyan "Creating .env"
  SECRET_KEY="$("$VPY" -c 'import secrets; print(secrets.token_urlsafe(64))')"
  ENC_KEY="$("$VPY" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"

  if [ -f .env.example ]; then
    sed -e "s|^SECRET_KEY=.*|SECRET_KEY=$SECRET_KEY|" \
        -e "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$ENC_KEY|" \
        -e "s|^FLASK_ENV=.*|FLASK_ENV=development|" \
        .env.example > .env
  else
    printf 'FLASK_ENV=development\nSECRET_KEY=%s\nENCRYPTION_KEY=%s\n' "$SECRET_KEY" "$ENC_KEY" > .env
  fi
  green "Generated .env with fresh SECRET_KEY and ENCRYPTION_KEY"
  yellow "Development mode uses local SQLite and logs emails to the console."
else
  cyan "Checking .env"
  # An .env carried over from an older version can be missing keys the config
  # now requires. Without FLASK_ENV especially, a local run is validated as
  # PRODUCTION and fails on things development does not need.
  added=""
  grep -qE '^[[:space:]]*FLASK_ENV=' .env || added="${added}FLASK_ENV=development\n"
  grep -qE '^[[:space:]]*SECRET_KEY=[^[:space:]]' .env || \
    added="${added}SECRET_KEY=$("$VPY" -c 'import secrets; print(secrets.token_urlsafe(64))')\n"
  grep -qE '^[[:space:]]*ENCRYPTION_KEY=[^[:space:]]' .env || \
    added="${added}ENCRYPTION_KEY=$("$VPY" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')\n"
  grep -qE '^[[:space:]]*CRON_SECRET=[^[:space:]]' .env || \
    added="${added}CRON_SECRET=$("$VPY" -c 'import secrets; print(secrets.token_urlsafe(32))')\n"

  if [ -n "$added" ]; then
    cp .env .env.bak
    printf '\n# --- added automatically by run.sh ---\n' >> .env
    printf "%b" "$added" >> .env
    green "Added missing setting(s); previous file saved as .env.bak"
    printf "%b" "$added" | cut -d= -f1 | sed 's/^/    + /'
  else
    green "using existing .env"
  fi
fi

export FLASK_APP=app.py
mkdir -p instance

# --- 5. Lint / test -----------------------------------------------------
if [ "$MODE" = "lint" ]; then
  cyan "Running ruff"; "$VPY" -m ruff check fluxweb tests app.py
  cyan "Running black --check"; "$VPY" -m black --check fluxweb tests app.py
  green "Lint clean"
  exit 0
fi

if [ "$MODE" = "test" ]; then
  cyan "Running tests"
  exec "$VPY" -m pytest
fi

# --- 6. Database --------------------------------------------------------
cyan "Preparing the database"
db_ok=1

if [ ! -d migrations ]; then
  green "Initialising migrations"
  "$VPY" -m flask db init >/dev/null 2>&1 || db_ok=0
fi

# Only autogenerate when no revision exists yet. Running `db migrate` on every
# start would drop an empty revision file into migrations/versions each time
# the models had not changed.
has_revisions=0
if [ -d migrations/versions ]; then
  if find migrations/versions -maxdepth 1 -name '*.py' ! -name '__init__.py' -print -quit | grep -q .; then
    has_revisions=1
  fi
fi

if [ "$db_ok" -eq 1 ] && [ "$has_revisions" -eq 0 ]; then
  green "Generating the initial migration"
  "$VPY" -m flask db migrate -m 'initial schema' >/dev/null 2>&1 || db_ok=0
fi

if [ "$db_ok" -eq 1 ]; then
  "$VPY" -m flask db upgrade >/dev/null 2>&1 || db_ok=0
fi

if [ "$db_ok" -eq 0 ]; then
  yellow "Migrations did not complete; creating tables directly instead."
  yellow "This is fine for local development. Use 'flask db upgrade' for production."
  if ! "$VPY" -m flask init-db; then
    red "Could not prepare the database. Run this to see the full error:"
    echo "    .venv/bin/python -m flask init-db"
    exit 1
  fi
fi
green "Database ready"

# --- 7. Run -------------------------------------------------------------
cyan "Starting FluxWeb on http://127.0.0.1:$PORT"
printf '    Press Ctrl+C to stop.\n\n'
exec "$VPY" -m flask run --port "$PORT" --host 127.0.0.1
