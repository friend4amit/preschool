"""pg_dump and pg_restore, wrapped.

A vendor wrapper like any other: it shells out to the postgres client tools and
knows nothing about students, branches or consent. That is what lets the backup
service be read as "dump, upload, prune" rather than as a page of subprocess
plumbing, and what lets the tests fake it.

The custom format (`-Fc`) rather than plain SQL, deliberately: it is compressed, it
restores selectively, and `pg_restore` can list its contents — which is how you
check a dump is a dump before trusting it.
"""

import subprocess
from pathlib import Path
from urllib.parse import urlparse

# pg_dump can sit and wait on an unreachable host indefinitely. A nightly job that
# never returns is worse than one that fails, because nothing alerts on it.
TIMEOUT_SECONDS = 60 * 30


class DumpFailed(RuntimeError):
    """Raised with pg_dump's own stderr, which is usually the whole diagnosis."""


def dump(*, database_url: str, destination: Path) -> Path:
    """Write a compressed custom-format dump. Returns the path it wrote."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    _run(
        ["pg_dump", "--format=custom", "--no-owner", "--no-acl", "--file", str(destination)],
        database_url=database_url,
    )
    if not destination.exists() or destination.stat().st_size == 0:
        raise DumpFailed(f"pg_dump wrote nothing to {destination}.")
    return destination


def restore(*, database_url: str, source: Path, clean: bool = True) -> None:
    """Load a dump into a database. `clean` drops what it is replacing first.

    Only ever pointed at a scratch database in the rehearsal — see scripts/restore.sh,
    which refuses to target the live one.
    """
    command = ["pg_restore", "--no-owner", "--no-acl", "--dbname", database_url]
    if clean:
        command += ["--clean", "--if-exists"]
    _run([*command, str(source)], database_url=database_url, pass_url_as_argument=False)


def table_names(*, source: Path) -> list[str]:
    """The tables a dump actually contains.

    The point of a backup rehearsal is answering "is my data in there", and a file
    of the right size can still be empty of the rows that matter. This is the cheap
    version of that check, and it needs no database at all.
    """
    listing = subprocess.run(
        ["pg_restore", "--list", str(source)],
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
    )
    if listing.returncode != 0:
        raise DumpFailed(f"pg_restore could not read {source}: {listing.stderr.strip()}")

    # Each data entry reads "<id>; <n> <oid> TABLE DATA <schema> <table> [<owner>]",
    # so the table name is the second field after the marker. Taking the last field
    # instead picks up the owner, or the schema when --no-owner dropped it.
    names = set()
    for line in listing.stdout.splitlines():
        _, marker, tail = line.partition(" TABLE DATA ")
        fields = tail.split()
        if marker and len(fields) >= 2:
            names.add(fields[1])
    return sorted(names)


def database_name(database_url: str) -> str:
    return urlparse(database_url).path.lstrip("/")


def _run(command: list[str], *, database_url: str, pass_url_as_argument: bool = True) -> None:
    full = [*command, database_url] if pass_url_as_argument else command
    result = subprocess.run(full, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
    if result.returncode != 0:
        # The URL holds a password. Report the tool's own stderr and the command
        # name, never the arguments.
        raise DumpFailed(f"{command[0]} failed: {result.stderr.strip()}")
