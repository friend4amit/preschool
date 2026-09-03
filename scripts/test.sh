#!/usr/bin/env sh
#
# Run the test suite inside the aaroham:dev image.
#
#   ./scripts/test.sh                    the whole suite
#   ./scripts/test.sh -k enquiry -x      arguments pass straight through to pytest
#
# `uv run pytest` on the host stays the documented command and is the right one on
# Linux and in CI. This exists because it does not always work on the Windows dev
# machine: Windows Application Control blocks the SSL DLL that psycopg's binary
# wheel loads, and pytest dies at import with
#
#     couldn't import psycopg 'binary' implementation:
#     DLL load failed while importing _ssl: An Application Control policy has
#     blocked this file.
#
# The container has its own libpq and is unaffected. It reaches whichever postgres
# is publishing 5432 on the host — the dev stack's or the standalone aaroham-pg —
# so ./scripts/start.sh (either target) is the only prerequisite.

set -eu

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

IMAGE="aaroham:dev"

say() { printf '%s\n' "$*"; }
die() { printf '\n%s\n' "$*" >&2; exit 1; }

case "${1:-}" in
  -h|--help)
    say "Run the test suite inside $IMAGE. Arguments pass through to pytest."
    say ""
    say "  ./scripts/test.sh"
    say "  ./scripts/test.sh -k enquiry -x"
    exit 0 ;;
esac

command -v docker >/dev/null 2>&1 ||
  die "docker is not on PATH. Install Docker Desktop, or add it to PATH."

docker info >/dev/null 2>&1 || die "Docker is not running.
  Windows / macOS:  start Docker Desktop.
  Linux:            sudo systemctl start docker"

[ -f .env ] || die ".env is missing.
  cp .env.example .env"

envval() { sed -n "s/^$1=//p" .env | tail -n 1; }

user="$(envval POSTGRES_USER)";     user="${user:-aaroham}"
pass="$(envval POSTGRES_PASSWORD)"; pass="${pass:-aaroham}"
db="$(envval POSTGRES_DB)";         db="${db:-aaroham}"
port="${POSTGRES_HOST_PORT:-$(envval POSTGRES_HOST_PORT)}"; port="${port:-5432}"

docker ps --format '{{.Names}}' --filter "publish=$port" | grep -q . ||
  die "Nothing is publishing postgres on port $port.
  ./scripts/start.sh testdb    just the database
  ./scripts/start.sh dev       the whole dev stack"

# The image carries the dev dependency group; the prod one does not ship pytest.
docker image inspect "$IMAGE" >/dev/null 2>&1 || {
  say "Building $IMAGE..."
  docker build --target dev -t "$IMAGE" .
}

# MSYS_NO_PATHCONV stops Git Bash rewriting /app into a Windows path on the way in.
# --add-host is what makes host.docker.internal resolve on Linux as well as Windows.
MSYS_NO_PATHCONV=1 exec docker run --rm -i \
  -v "$REPO:/app" -w /app \
  --add-host=host.docker.internal:host-gateway \
  -e DJANGO_SETTINGS_MODULE=config.settings.test \
  -e DATABASE_URL="postgres://$user:$pass@host.docker.internal:$port/$db" \
  -e SECRET_KEY=test-only-not-a-secret \
  -e ALLOWED_HOSTS='*' \
  "$IMAGE" python -m pytest "$@"
