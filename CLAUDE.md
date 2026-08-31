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

docker compose up                         # dev: postgres + web + worker, migrated on boot

# prod — from the REPO ROOT. --env-file is required: without it the ${POSTGRES_*}
# interpolation resolves empty. It now fails loudly rather than building a broken URL.
docker compose --env-file .env -f deploy/docker-compose.prod.yml up -d --build
```

The prod stack **forces** `DJANGO_SETTINGS_MODULE` and the database host in the compose
`environment:` rather than trusting `.env`. A `.env` copied from `.env.example` still
says `config.settings.dev`, and one forgotten line would otherwise run production with
`DEBUG=True`. Don't "simplify" that back into `.env`.

Postgres for host-run tests, if you aren't using compose:

```sh
docker run -d --name aaroham-pg -e POSTGRES_USER=aaroham -e POSTGRES_PASSWORD=aaroham \
  -e POSTGRES_DB=aaroham -p 5432:5432 postgres:17-alpine
```

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

- `templates/base.html` loads fonts from Google Fonts. Fine for marketing pages, but it
  is a third-party request logging viewer IPs — self-host the two faces before the parent
  portal ships in Phase 4.
