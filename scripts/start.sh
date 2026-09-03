#!/usr/bin/env sh
#
# Start one of this project's three container situations.
#
#   ./scripts/start.sh            dev stack — postgres + web + worker, migrated
#   ./scripts/start.sh prod       prod stack — caddy + web + worker + postgres
#   ./scripts/start.sh testdb     postgres alone, for host-run `uv run pytest`
#
# The raw `docker compose` commands stay documented in CLAUDE.md — this script is
# the convenience, not the documentation. It exists because two of those commands
# are wrong more often than they are right:
#
#   - prod needs `--env-file .env`, and without it the ${POSTGRES_*} interpolation
#     resolves empty. The compose file fails loudly rather than building a broken
#     URL, but only if you remember the flag.
#   - testdb is a long `docker run` that gets retyped from the docs, and the
#     documented one hardcodes the password `aaroham` — which will not match a
#     real .env, so host-run pytest then cannot connect. This reads the actual
#     POSTGRES_* values instead.
#
# POSIX sh on purpose: one implementation for Git Bash on Windows and the Linux
# VPS. A PowerShell twin would drift within a month.

set -eu

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

PROD_COMPOSE="deploy/docker-compose.prod.yml"
TESTDB_NAME="aaroham-pg"
# Matches the compose files, so tests run against the same engine build as prod.
TESTDB_IMAGE="postgres:17-bookworm"

say() { printf '%s\n' "$*"; }
die() { printf '\n%s\n' "$*" >&2; exit 1; }

usage() {
  say "Start one of this project's three container situations."
  say ""
  say "  ./scripts/start.sh            dev stack — postgres + web + worker"
  say "  ./scripts/start.sh prod       prod stack — caddy + web + worker + postgres"
  say "  ./scripts/start.sh testdb     postgres alone, for host-run pytest"
  say ""
  say "  --build      force an image rebuild (prod does this by default)"
  say "  --no-build   skip the rebuild"
  say "  -h, --help   this"
}

# --- arguments ---------------------------------------------------------------

TARGET=dev
BUILD=auto

for arg in "$@"; do
  case "$arg" in
    dev|prod|testdb) TARGET="$arg" ;;
    --build)         BUILD=yes ;;
    --no-build)      BUILD=no ;;
    -h|--help)       usage; exit 0 ;;
    *) die "unknown argument: $arg
Run './scripts/start.sh --help'." ;;
  esac
done

# --- preflight ---------------------------------------------------------------
# Name the fix in the error, not just the fault.

command -v docker >/dev/null 2>&1 ||
  die "docker is not on PATH. Install Docker Desktop, or add it to PATH."

docker info >/dev/null 2>&1 || die "Docker is not running.
  Windows / macOS:  start Docker Desktop and wait for it to settle.
  Linux:            sudo systemctl start docker"

# Every target needs .env: dev and prod read it as env_file, and testdb needs the
# POSTGRES_* values so the DATABASE_URL already in .env actually connects.
[ -f .env ] || die ".env is missing.
  cp .env.example .env    then fill in the secrets — every one generated fresh."

# --- helpers -----------------------------------------------------------------

# .env is plain KEY=VALUE; read it rather than sourcing it, so a stray line
# cannot execute anything.
envval() { sed -n "s/^$1=//p" .env | tail -n 1; }

# Which container, if any, publishes this host port. Uses docker's own filter
# rather than netstat or lsof, which differ between Git Bash and Linux.
port_holder() { docker ps --format '{{.Names}}' --filter "publish=$1" | head -n 1; }

# The dev stack's published postgres port. The environment wins over .env, which
# is how you move the dev stack out of a collision without editing a file.
dev_pg_port() {
  p="${POSTGRES_HOST_PORT:-}"
  [ -n "$p" ] || p="$(envval POSTGRES_HOST_PORT)"
  printf '%s' "${p:-5432}"
}

# Poll a container's health, or its plain running state if it declares none.
wait_healthy() {
  name="$1"; limit="$2"; n=0
  while [ "$n" -lt "$limit" ]; do
    state="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$name" 2>/dev/null || printf 'missing')"
    case "$state" in
      healthy|running) return 0 ;;
      exited|dead)     return 1 ;;
    esac
    n=$((n + 1)); sleep 1
  done
  return 1
}

# Both dev failures below were met while writing this script, which is why they
# are named rather than left to a stack trace.
dev_failure_help() {
  cat <<'HELP'
The dev stack did not come up. Read the reason first:

    docker compose logs web

ModuleNotFoundError
    The aaroham:dev image predates a dependency. Rebuild it:
    ./scripts/start.sh dev --build

password authentication failed for user
    postgres_data was initialised with a different POSTGRES_PASSWORD than the one
    now in .env, and the volume wins — postgres reads that variable only on first
    init. Either put the original password back, or throw the dev database away:
    ./scripts/stop.sh dev --destroy
HELP
}

# --- targets -----------------------------------------------------------------

start_dev() {
  port="$(dev_pg_port)"
  holder="$(port_holder "$port")"

  case "$holder" in
    ""|aaroham-postgres*) : ;;
    aaroham-pg)
      die "$TESTDB_NAME is holding port $port, and the dev stack publishes its own
postgres there.

The dev stack's database serves host-run pytest just as well, so the simple fix
is to stop the standalone one:

    ./scripts/stop.sh testdb --down

Or leave it and move the dev stack instead:

    POSTGRES_HOST_PORT=5433 ./scripts/start.sh dev" ;;
    *)
      die "container '$holder' is already publishing port $port.
Stop it, or move the dev stack: POSTGRES_HOST_PORT=5433 ./scripts/start.sh dev" ;;
  esac

  if [ "$BUILD" = yes ]; then set -- --build; else set --; fi
  say "Starting the dev stack — postgres + web + worker, migrating on boot."
  docker compose up -d "$@" || die "$(dev_failure_help)"

  say "Waiting for web to report healthy..."
  wait_healthy aaroham-web-1 120 || die "$(dev_failure_help)"

  say ""
  say "  Site       http://localhost:8000"
  say "  Postgres   localhost:$port"
  say "  Seed       docker compose exec web python manage.py seed"
  say "  Logs       docker compose logs -f web"
}

# Deliberately no --destroy suggestion here. On the prod stack that would take
# caddy_data with it, and re-issuing certificates burns Let's Encrypt rate limit.
prod_failure_help() {
  cat <<'HELP'
The prod stack did not come up. Read the reason first:

    docker compose --env-file .env -f deploy/docker-compose.prod.yml logs web

password authentication failed for user
    postgres_data holds the password it was first initialised with, not the one
    in .env. Put the original back — do NOT delete this volume, it is the
    production database.

no such host / connection refused
    Check ALLOWED_HOSTS and CADDY_DOMAIN in .env agree with each other. The web
    healthcheck sends CADDY_DOMAIN as its Host header.
HELP
}

start_prod() {
  # --env-file is the whole point of this branch. Without it the ${POSTGRES_*}
  # interpolation in the prod compose file resolves empty.
  if [ "$BUILD" = no ]; then set --; else set -- --build; fi
  say "Starting the prod stack — caddy + web + worker + postgres."
  docker compose --env-file .env -f "$PROD_COMPOSE" up -d "$@" || die "$(prod_failure_help)"

  # start_period is 90s there: migrate and collectstatic run before gunicorn binds.
  say "Waiting for web to report healthy (migrate + collectstatic run first)..."
  wait_healthy aaroham-prod-web-1 240 || die "$(prod_failure_help)"

  domain="$(envval CADDY_DOMAIN)"
  say ""
  say "  Site       https://${domain:-localhost}"
  say "  Logs       docker compose --env-file .env -f $PROD_COMPOSE logs -f web"
  say ""
  say "On localhost the certificate is self-signed — see docs/deploy.md."
}

start_testdb() {
  # If the dev stack is already up it publishes postgres itself, and pytest can
  # use that. Starting a second one would only collide.
  holder="$(port_holder 5432)"
  case "$holder" in
    aaroham-postgres*)
      say "The dev stack already publishes postgres on 5432 — pytest can use it."
      say "Nothing to start."
      return 0 ;;
    aaroham-pg|"") : ;;
    *) die "container '$holder' is already publishing port 5432. Stop it first." ;;
  esac

  user="$(envval POSTGRES_USER)";     user="${user:-aaroham}"
  pass="$(envval POSTGRES_PASSWORD)"; pass="${pass:-aaroham}"
  db="$(envval POSTGRES_DB)";         db="${db:-aaroham}"

  if docker ps -a --format '{{.Names}}' | grep -qx "$TESTDB_NAME"; then
    say "Starting the existing $TESTDB_NAME container."
    docker start "$TESTDB_NAME" >/dev/null
  else
    say "Creating $TESTDB_NAME from $TESTDB_IMAGE, with the POSTGRES_* values in .env."
    docker run -d --name "$TESTDB_NAME" \
      -e POSTGRES_USER="$user" \
      -e POSTGRES_PASSWORD="$pass" \
      -e POSTGRES_DB="$db" \
      -p 5432:5432 "$TESTDB_IMAGE" >/dev/null
  fi

  say "Waiting for postgres to accept connections..."
  n=0
  until docker exec "$TESTDB_NAME" pg_isready -U "$user" -d "$db" >/dev/null 2>&1; do
    n=$((n + 1))
    [ "$n" -lt 60 ] || die "postgres did not become ready. Logs:
    docker logs $TESTDB_NAME"
    sleep 1
  done

  say ""
  say "  Postgres   localhost:5432  ($db as $user)"
  say "  Tests      uv run pytest"
  say ""
  say "DATABASE_URL in .env must point at localhost for host-run manage.py and pytest."
}

case "$TARGET" in
  dev)    start_dev ;;
  prod)   start_prod ;;
  testdb) start_testdb ;;
esac
