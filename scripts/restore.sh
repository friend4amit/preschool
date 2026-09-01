#!/bin/sh
# Restore a pg_dump into a CLEAN, THROWAWAY database and prove it holds real rows.
#
# An untested backup is not a backup. This script exists so that testing one is a
# command rather than an afternoon, and so it gets run again every time the schema
# grows — which is the only way the rehearsal stays honest.
#
#   ./scripts/restore.sh                       # fetch the newest dump from R2
#   ./scripts/restore.sh path/to/local.dump    # rehearse a dump you already have
#
# It NEVER touches the live database. The restore target is a scratch database
# created for the run and dropped at the end, and the script refuses if the name it
# was given is the one in DATABASE_URL.

set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

SCRATCH_DB="aaroham_restore_check"
KEEP=0
SOURCE=""

die() { printf '\n%s\n' "$*" >&2; exit 1; }
say() { printf '%s\n' "$*"; }

usage() {
  cat <<'HELP'
Usage: ./scripts/restore.sh [DUMP_FILE] [--keep]

  DUMP_FILE   A local .dump. Omit it to download the newest backup from R2.
  --keep      Leave the scratch database in place so you can poke at it.
HELP
}

for arg in "$@"; do
  case "$arg" in
    -h|--help) usage; exit 0 ;;
    --keep)    KEEP=1 ;;
    -*)        die "Unknown option: $arg" ;;
    *)         SOURCE="$arg" ;;
  esac
done

# --- preflight ----------------------------------------------------------------------

command -v docker >/dev/null 2>&1 ||
  die "docker is not on PATH. Install Docker Desktop, or add it to PATH."

docker info >/dev/null 2>&1 || die "Docker is not running. Start it and try again."

[ -f .env ] || die ".env is missing. Copy .env.example and fill it in."

# Read .env with sed rather than sourcing it: a stray line in a config file should
# not be able to execute.
envval() {
  sed -n "s/^$1=//p" .env | tail -n 1 | tr -d '\r' | sed 's/^"//; s/"$//'
}

PGUSER=$(envval POSTGRES_USER)
PGPASSWORD=$(envval POSTGRES_PASSWORD)
PGDB=$(envval POSTGRES_DB)
PGPORT=$(envval POSTGRES_HOST_PORT)
[ -n "$PGPORT" ] || PGPORT=5432

[ -n "$PGUSER" ] && [ -n "$PGPASSWORD" ] && [ -n "$PGDB" ] ||
  die "POSTGRES_USER, POSTGRES_PASSWORD and POSTGRES_DB must all be set in .env."

# The one refusal that matters. Restoring over the live database is the accident
# this script is most able to cause, so it is the accident it checks for first.
[ "$SCRATCH_DB" != "$PGDB" ] ||
  die "The scratch database name matches POSTGRES_DB. Refusing to restore over the
live database. Change SCRATCH_DB at the top of this script."

docker ps --format '{{.Names}}' --filter "publish=$PGPORT" | grep -q . ||
  die "Nothing is publishing port $PGPORT, so there is no postgres to restore into.

    ./scripts/start.sh dev        # the dev stack
    ./scripts/start.sh testdb     # postgres alone"

IMAGE="aaroham:dev"
docker image inspect "$IMAGE" >/dev/null 2>&1 || {
  say "Building $IMAGE (first run only)…"
  docker build --target dev -t "$IMAGE" .
}

# Inside the repo rather than mktemp -d. The repo is already bind-mounted into the
# container; a host temp directory is not, and on Windows Docker silently mounts an
# empty one instead of failing - which looks exactly like an empty backup.
WORK="$ROOT/.restore-work"
rm -rf "$WORK"
mkdir -p "$WORK"

cleanup() {
  [ "$KEEP" -eq 1 ] || drop_scratch
  rm -rf "$WORK"
}
trap cleanup EXIT

# Everything runs inside the image: it carries libpq and the postgres client tools,
# which this Windows machine does not have and should not need.
in_container() {
  MSYS_NO_PATHCONV=1 docker run --rm -i \
    -v "$ROOT:/app" -w /app \
    --env-file .env \
    --add-host=host.docker.internal:host-gateway \
    -e PGPASSWORD="$PGPASSWORD" \
    -e DATABASE_URL="postgres://$PGUSER:$PGPASSWORD@host.docker.internal:$PGPORT/$SCRATCH_DB" \
    "$IMAGE" "$@"
}

psql_admin() {
  in_container psql -h host.docker.internal -p "$PGPORT" -U "$PGUSER" -d postgres \
    -v ON_ERROR_STOP=1 -c "$1"
}

drop_scratch() {
  psql_admin "DROP DATABASE IF EXISTS $SCRATCH_DB WITH (FORCE);" >/dev/null 2>&1 || true
}

# --- 1. get a dump --------------------------------------------------------------------

if [ -n "$SOURCE" ]; then
  [ -f "$SOURCE" ] || die "No such file: $SOURCE"
  cp "$SOURCE" "$WORK/restore.dump"
  say "Rehearsing $SOURCE"
else
  say "Fetching the newest backup from R2…"
  in_container python - <<'PY' || die "Could not fetch a backup from R2.

If R2 is not configured yet, pass a local dump instead:
    ./scripts/backup-local.sh          # writes one from the running database
    ./scripts/restore.sh <that file>"
import django, os, pathlib
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()
from apps.core import backups
from integrations import storage_r2

latest = backups.latest_backup()
if latest is None:
    raise SystemExit("The bucket holds no backups.")
storage_r2.download(key=latest.key, destination=pathlib.Path("/app/.restore-work/restore.dump"))
print(f"Downloaded {latest.key} ({latest.size / 1_048_576:.1f} MB)")
PY
fi

# --- 2. is it actually a dump? --------------------------------------------------------

say ""
say "Tables carrying data in this dump:"
in_container python - <<'PY'
import pathlib
from integrations import postgres

names = postgres.table_names(source=pathlib.Path("/app/.restore-work/restore.dump"))
if not names:
    raise SystemExit("The dump contains no table data. That is not a backup.")
for name in names:
    print(f"  {name}")
PY

# --- 3. restore into a clean database -------------------------------------------------

say ""
say "Creating a clean $SCRATCH_DB…"
drop_scratch
psql_admin "CREATE DATABASE $SCRATCH_DB;" >/dev/null

say "Restoring…"
in_container python - <<'PY'
import os, pathlib
from integrations import postgres

postgres.restore(
    database_url=os.environ["DATABASE_URL"],
    source=pathlib.Path("/app/.restore-work/restore.dump"),
    clean=False,
)
print("Restored.")
PY

# --- 4. prove the rows are there ------------------------------------------------------

say ""
say "What came back:"
in_container python - <<'PY'
import django, os
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.dev"
django.setup()

from apps.core.models import Branch, Consent, Organization, User
from apps.people.models import Enrollment, Guardian, Student
from apps.website.models import Enquiry

counts = {
    "organizations": Organization.objects.count(),
    "branches": Branch.objects.count(),
    "users": User.objects.count(),
    "students": Student.objects.count(),
    "guardians": Guardian.objects.count(),
    "enrolments": Enrollment.objects.count(),
    "consents": Consent.objects.count(),
    "enquiries": Enquiry.objects.count(),
}
width = max(len(k) for k in counts)
for name, count in counts.items():
    print(f"  {name:<{width}}  {count}")

# A restore that produces an empty schema looks like a success and is not one.
if not any(counts.values()):
    raise SystemExit("\nEvery table is empty. The restore ran but restored nothing.")
PY

say ""
if [ "$KEEP" -eq 1 ]; then
  say "Restore rehearsed. $SCRATCH_DB is still there — drop it when you are done:"
  say "  docker exec -it <postgres container> psql -U $PGUSER -d postgres \\"
  say "    -c 'DROP DATABASE $SCRATCH_DB WITH (FORCE);'"
else
  say "Restore rehearsed, and $SCRATCH_DB dropped. The live database was never touched."
fi
