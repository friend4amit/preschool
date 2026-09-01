#!/usr/bin/env sh
#
# Stop one of this project's three container situations.
#
#   ./scripts/stop.sh             dev stack
#   ./scripts/stop.sh prod        prod stack
#   ./scripts/stop.sh testdb      the standalone postgres
#
# The default halts containers and touches nothing else. Removing data is a
# separate, louder decision:
#
#   (default)     docker compose stop      — containers halt, volumes untouched
#   --down        docker compose down      — containers and network go, volumes stay
#   --destroy     down -v                  — volumes go too, after typed confirmation
#
# Why the ceremony: on the prod stack `-v` destroys postgres_data AND caddy_data,
# and losing caddy_data means re-issuing certificates and burning Let's Encrypt
# rate limit. That must never be one keystroke away from a routine stop.

set -eu

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

PROD_COMPOSE="deploy/docker-compose.prod.yml"
TESTDB_NAME="aaroham-pg"

say() { printf '%s\n' "$*"; }
die() { printf '\n%s\n' "$*" >&2; exit 1; }

usage() {
  say "Stop one of this project's three container situations."
  say ""
  say "  ./scripts/stop.sh             dev stack"
  say "  ./scripts/stop.sh prod        prod stack"
  say "  ./scripts/stop.sh testdb      the standalone postgres"
  say ""
  say "  (default)    halt containers, keep everything"
  say "  --down       also remove containers and networks; volumes survive"
  say "  --destroy    also remove volumes — asks first, and means it"
  say "  -h, --help   this"
}

# --- arguments ---------------------------------------------------------------

TARGET=dev
MODE=stop

for arg in "$@"; do
  case "$arg" in
    dev|prod|testdb) TARGET="$arg" ;;
    --down)          MODE=down ;;
    --destroy)       MODE=destroy ;;
    -h|--help)       usage; exit 0 ;;
    *) die "unknown argument: $arg
Run './scripts/stop.sh --help'." ;;
  esac
done

# --- preflight ---------------------------------------------------------------

command -v docker >/dev/null 2>&1 ||
  die "docker is not on PATH. Install Docker Desktop, or add it to PATH."

docker info >/dev/null 2>&1 || die "Docker is not running — so nothing is either.
  Windows / macOS:  start Docker Desktop.
  Linux:            sudo systemctl start docker"

# Not just for the containers: the prod compose file uses required-variable
# syntax, so even `down` fails without --env-file .env.
[ -f .env ] || die ".env is missing, and compose needs it even to stop cleanly.
  cp .env.example .env"

# --- the confirmation --------------------------------------------------------
# Typed, naming the target. A y/n prompt is too easy to answer on reflex.

confirm_destroy() {
  what="$1"
  [ -t 0 ] || die "--destroy needs an interactive terminal. Refusing to guess."

  say ""
  say "This permanently deletes:"
  say "$what"
  say ""
  printf 'Type the target name (%s) to confirm: ' "$TARGET"
  read -r answer
  [ "$answer" = "$TARGET" ] || die "Not confirmed. Nothing was removed."
}

# --- targets -----------------------------------------------------------------

dev_compose()  { docker compose "$@"; }
prod_compose() { docker compose --env-file .env -f "$PROD_COMPOSE" "$@"; }

stop_compose_stack() {
  runner="$1"; label="$2"; volumes="$3"

  case "$MODE" in
    stop)
      say "Halting the $label stack. Volumes and data untouched."
      "$runner" stop ;;
    down)
      say "Removing the $label containers and network. Volumes survive."
      "$runner" down ;;
    destroy)
      confirm_destroy "$volumes"
      say "Removing the $label stack and its volumes."
      "$runner" down -v ;;
  esac
}

case "$TARGET" in
  dev)
    stop_compose_stack dev_compose dev \
      "  postgres_data   every local student, enquiry and migration state" ;;

  prod)
    stop_compose_stack prod_compose prod \
      "  postgres_data   the production database
  caddy_data      TLS certificates and the ACME account — re-issuing them
                  burns Let's Encrypt rate limit" ;;

  testdb)
    if ! docker ps -a --format '{{.Names}}' | grep -qx "$TESTDB_NAME"; then
      say "No $TESTDB_NAME container exists. Nothing to do."
      exit 0
    fi
    case "$MODE" in
      stop)
        say "Halting $TESTDB_NAME. Start it again with ./scripts/start.sh testdb."
        docker stop "$TESTDB_NAME" >/dev/null ;;
      down|destroy)
        # This container holds no volume, so its data dies with it either way —
        # say so rather than pretending --down is the safe half.
        confirm_destroy "  $TESTDB_NAME   the throwaway test database (no volume; data goes with it)"
        say "Removing $TESTDB_NAME."
        docker rm -f "$TESTDB_NAME" >/dev/null ;;
    esac ;;
esac
