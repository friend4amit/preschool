#!/bin/sh
# Write a pg_dump of the running database to a local file.
#
# The real nightly backup goes to R2 and keeps nothing on disk — see
# `manage.py backup_database`. This is the version for the two cases that come
# first: rehearsing a restore before R2 is configured, and taking a dump by hand
# before a migration you are not sure about.
#
#   ./scripts/backup-local.sh                    # writes to backups/
#   ./scripts/backup-local.sh /tmp/before.dump   # or wherever you say
#
# Dumps hold every child's name, date of birth and guardian phone number. The
# default directory is gitignored; if you move one elsewhere, that is now your
# problem to keep off a shared drive.

set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

die() { printf '\n%s\n' "$*" >&2; exit 1; }

case "${1:-}" in
  -h|--help)
    printf 'Usage: ./scripts/backup-local.sh [OUTPUT_FILE]\n'
    exit 0
    ;;
esac

command -v docker >/dev/null 2>&1 || die "docker is not on PATH."
docker info >/dev/null 2>&1 || die "Docker is not running."
[ -f .env ] || die ".env is missing. Copy .env.example and fill it in."

envval() {
  sed -n "s/^$1=//p" .env | tail -n 1 | tr -d '\r' | sed 's/^"//; s/"$//'
}

PGUSER=$(envval POSTGRES_USER)
PGPASSWORD=$(envval POSTGRES_PASSWORD)
PGDB=$(envval POSTGRES_DB)
PGPORT=$(envval POSTGRES_HOST_PORT)
[ -n "$PGPORT" ] || PGPORT=5432

docker ps --format '{{.Names}}' --filter "publish=$PGPORT" | grep -q . ||
  die "Nothing is publishing port $PGPORT.

    ./scripts/start.sh dev        # the dev stack
    ./scripts/start.sh testdb     # postgres alone"

OUTPUT=${1:-backups/aaroham-$(date -u +%Y%m%dT%H%M%SZ).dump}
mkdir -p "$(dirname "$OUTPUT")"

IMAGE="aaroham:dev"
docker image inspect "$IMAGE" >/dev/null 2>&1 || docker build --target dev -t "$IMAGE" .

# The image carries the postgres client tools; this Windows machine does not.
MSYS_NO_PATHCONV=1 docker run --rm -i \
  -v "$ROOT:/app" -w /app \
  --add-host=host.docker.internal:host-gateway \
  -e PGPASSWORD="$PGPASSWORD" \
  "$IMAGE" \
  pg_dump --format=custom --no-owner --no-acl \
    -h host.docker.internal -p "$PGPORT" -U "$PGUSER" -d "$PGDB" \
    --file "/app/$OUTPUT"

printf 'Wrote %s (%s)\n' "$OUTPUT" "$(du -h "$OUTPUT" | cut -f1)"
printf 'Rehearse restoring it:\n  ./scripts/restore.sh %s\n' "$OUTPUT"
