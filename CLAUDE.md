# Aaroham — working notes

Preschool management platform and public website. One preschool in India, more branches
later, native apps much later.

**Read `docs/plan.md` before changing architecture** and `docs/implementation-plan.md`
before starting a phase. They own decisions and sequence respectively, and neither
restates the other. If code and plan disagree, one of them is wrong — say which.

## Commands

```sh
uv sync                                   # install (uv manages Python; no system Python needed)
uv run python manage.py runserver         # dev server
uv run python manage.py seed              # one Organization + Branch + superadmin, idempotent
uv run python manage.py db_worker         # background worker (django-tasks, DB-backed)
uv run pytest                             # tests — needs Postgres on :5432
uv run ruff check . && uv run ruff format .
uv run lint-imports                       # layer contract

./scripts/start.sh                        # dev stack: postgres + web + worker
./scripts/start.sh prod                   # prod stack: caddy + web + worker + postgres
./scripts/start.sh testdb                 # postgres alone, for host-run pytest
./scripts/stop.sh [dev|prod|testdb]       # halt. --down removes containers, --destroy volumes
./scripts/test.sh                         # pytest inside the dev image; args pass through

./scripts/backup-local.sh                 # pg_dump to backups/ (gitignored)
./scripts/restore.sh [DUMP]               # rehearse a restore into a scratch database
uv run python manage.py backup_database   # the nightly one: pg_dump -> R2, then prune
uv run python manage.py backup_database --list

uv run python manage.py seed_media --source <wp-content/uploads>   # marketing photos
uv run python manage.py seed_media --source <path> --dry-run       # report, write nothing
```

`seed_media` converts the Udgam photographs to WebP at a few widths and attaches them
to `SiteSettings`, `Program` and `GalleryImage`. `--source` is required and has no
default on purpose: a path that exists on one laptop and not on the VPS is how a
command silently half-works. It refuses a blocklist — one file is a named person who
must not appear on this site, the rest carry watermarks or burnt-in text — and
`apps/website/tests/test_media_blocklist.py` keeps that honest.

`restore.sh` never touches the live database — it creates `aaroham_restore_check`,
restores into that, counts what came back, and drops it. Run it after every phase that
grows the schema. An untested backup is not a backup, and a restore that produces an
empty schema looks exactly like one that worked.

`backup_database` is a management command rather than only a task because the thing
that schedules it is cron on the VPS, and cron cannot enqueue. The image carries
`postgresql-client-17` from PGDG rather than Debian's 15 — `pg_dump` refuses to talk
to a newer server than itself, so that pin moves with `postgres:17-bookworm`.

`test.sh` exists because `uv run pytest` on the host currently fails on this Windows
machine — Application Control blocks the SSL DLL psycopg's binary wheel loads, and
pytest dies at import. The container carries its own libpq. On Linux and in CI the
plain `uv run pytest` is still the command.

The scripts are the convenience; the commands below are the documentation, and they
still work. Reach for the scripts because they preflight Docker and `.env`, refuse a
port collision with an explanation, and cannot forget `--env-file`.

```sh
docker compose up                         # dev: postgres + web + worker, migrated on boot

# prod — from the REPO ROOT. --env-file is required: without it the ${POSTGRES_*}
# interpolation resolves empty. It now fails loudly rather than building a broken URL.
docker compose --env-file .env -f deploy/docker-compose.prod.yml up -d --build
```

The prod stack **forces** `DJANGO_SETTINGS_MODULE` and the database host in the compose
`environment:` rather than trusting `.env`. A `.env` copied from `.env.example` still
says `config.settings.dev`, and one forgotten line would otherwise run production with
`DEBUG=True`. Don't "simplify" that back into `.env`.

Postgres for host-run tests, if you aren't using compose — `./scripts/start.sh testdb`,
or by hand:

```sh
docker run -d --name aaroham-pg -e POSTGRES_USER=aaroham -e POSTGRES_PASSWORD=aaroham \
  -e POSTGRES_DB=aaroham -p 5432:5432 postgres:17-bookworm
```

Those hardcoded credentials only work if `.env` still uses them; the script reads the
real `POSTGRES_*` instead, so the `DATABASE_URL` already in `.env` connects. **The dev
stack and `aaroham-pg` both want port 5432** and cannot run together — the dev stack's
own postgres serves host-run tests equally well, so `testdb` is for when you don't want
the whole stack. `POSTGRES_HOST_PORT` moves the dev stack if you need both.

Scripts are POSIX `sh`, one implementation for Git Bash on Windows and the Linux VPS.
`.gitattributes` pins them to LF: with `core.autocrlf=true` a CRLF checkout gives
`bad interpreter: /bin/sh^M` on the server — invisible on Windows, fatal there.

Tailwind is the **standalone CLI** — no Node, no `package.json`, no PostCSS. See
`assets/README-frontend.md`. `static/css/app.css` is build output, gitignored, and built
inside the Dockerfile's `tailwind` stage; never edit it by hand.

## The layering, which CI enforces

```
templates/          display only — no ORM, no business logic
  ^
views.py            parse request -> call ONE service or selector -> pick a template
  ^
services.py         business logic, owns transaction.atomic(), knows nothing about HTTP
  ^
selectors.py        every non-trivial read, plus for_user() scoping
  ^
models.py           schema and invariants
integrations/       vendor wrappers (R2, Anthropic, UPI, email) — imports no domain code
```

Dependencies point **downward only**. Two mechanisms keep this honest, both in CI:

- `uv run lint-imports` — the direction of dependencies (`.importlinter`).
- `apps/core/tests/test_architecture.py` — bans `django.http`, `django.shortcuts` etc.
  below the view layer. AST-based, so it covers new apps automatically; you don't have
  to register them anywhere.

A view longer than ~15 lines, or containing an `if` about business meaning, has logic
that belongs a layer down.

## Non-negotiables

These cost hours now and weeks later. They are decided; don't relitigate them in code.

- **`branch` FK on every model holding school data.** One Branch row exists today. The
  switcher stays hidden until branch two. Retrofitting a tenant key across forty tables
  is a rewrite.
- **Scope explicitly** via `for_user(user)` in selectors. Never auto-scope the default
  manager through middleware or thread-locals — that breaks migrations, `loaddata`,
  shell sessions, and background tasks, none of which have a request.
- **`/admin` is superadmin-only** (`config/admin.py`). Django admin ignores request
  context, so it is an operator tool, not a staff surface. Staff get built screens.
- **Consent is off by default**, per guardian, per purpose, versioned, revocable. Note
  `photos_in_app` and `photos_shared_with_class` are *different questions* — most
  classroom photos contain several children, and a photo publishes only if **every**
  tagged child carries the second one.
- **Return 404, not 403**, when a user asks for another family's data. Don't leak
  existence. Every parent-visible model gets a cross-family test the day it is added.
- **Money is integer paise.** Invoices carry a set of `Payment` rows, never `paid: bool`;
  refunds are `CreditNote`, never a negative payment. Fees are GST-taxable, so tax lives
  per `InvoiceLine` with values *stored*, not recomputed at render.
- **No behavioural analytics on parent-facing pages.** Sentry errors only, Session Replay
  off. India's DPDP Act, and it's simpler anyway.
- **No face recognition on children.** Teachers tag photos.

## Conventions

- Timezone is `Asia/Kolkata` everywhere; there is no per-user timezone. Currency is ₹ only.
- Mobile-first: base Tailwind classes are the phone layout, `md:`/`lg:` add the laptop.
  Parent portal is phone-first; staff console is laptop-first.
- A partial never extends a layout — that's what makes it swappable into an `hx-target`.
- Service tests construct **no `HttpRequest`**. If a service needs one to be testable,
  the logic has leaked upward.
- Ship in English. Django's `gettext` is there for the day Hindi arrives; don't wrap
  strings until then.
- Secrets live in `.env`, which is gitignored. `.env.example` documents every variable.
- `POSTGRES_*` in `.env` and the `DATABASE_URL` there must agree by hand — compose
  cannot parse the URL to configure the postgres container.

## Known follow-ups

- **A public R2 bucket does not exist yet.** `STORAGES["public_media"]` holds the
  marketing photographs and must be a *separate, public* bucket from the private one
  children's photos live in. Until `R2_PUBLIC_BUCKET` and `R2_PUBLIC_BASE_URL` are set,
  prod falls back to local disk and Caddy serves `/media/`. On R2, `custom_domain` is
  the setting that makes URLs work — `querystring_auth: False` alone yields an unsigned
  S3-endpoint URL that R2 refuses anonymously.
- **`SITE_ID = 1` points at the unconfigured `example.com` Site row**, so `sitemap.xml`
  advertises the wrong host. One row to edit in `/admin`, before the domain goes live.
- **The nightly backup has no schedule yet.** `manage.py backup_database` works and the
  restore is rehearsed, but nothing calls it on a timer — that is a cron entry on the
  VPS, and it belongs with the deploy rather than in the repo.
- **R2 is unconfigured on this machine**, so `backup_database` refuses. That is the
  intended behaviour, not a bug: a backup that silently no-ops is worse than one that
  fails. `./scripts/backup-local.sh` covers the local case.
- **The Phase 2 screens have never been seen below ~1218px.** Chrome on Windows will
  not size a window narrower than that, so the phone layout is written but unverified —
  the plan's "renders at 390px" check is outstanding. The one to look at first is the
  student list: its filter bar is `md:grid-cols-[2fr_1fr_1fr_auto]`, so on a phone it
  stacks into four full-width rows before the first student appears, and that may want
  collapsing behind a summary. Check it on a real cheap Android over mobile data rather
  than in a device emulator — `plan.md` is right that emulated viewports hide
  touch-target size, font scaling and slow-network behaviour.
