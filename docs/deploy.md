# Deploying Aaroham

The production stack is four containers — Caddy, Django under Gunicorn, a `db_worker`,
and Postgres — from one image. The same commands work on a laptop and on a server; only
`CADDY_DOMAIN`, `ALLOWED_HOSTS`, and the secrets differ.

> **What "deployed locally" means, plainly.** Running the production stack on your machine
> proves the image, migrations, TLS, static files, and worker all work together. It is
> **not reachable from the internet** and no parent can use it. Going live needs a server
> with a public IP, which is a separate step below.

---

## The one command

Always from the **repo root**:

```sh
docker compose --env-file .env -f deploy/docker-compose.prod.yml up -d --build
```

`--env-file` is not optional. Compose interpolates `${POSTGRES_*}` from the current
directory, not from `env_file:`, so without it the database URL resolves empty. It now
fails loudly rather than building a broken URL, but the flag is still the fix.

That alias is worth having:

```sh
alias aaroham-prod='docker compose --env-file .env -f deploy/docker-compose.prod.yml'
```

Everything below assumes it.

---

## First boot

1. **Create `.env`** from `.env.example` and fill it in. Generate real values:

   ```sh
   uv run python -c "import secrets; print(secrets.token_urlsafe(64))"   # SECRET_KEY
   uv run python -c "import secrets; print(secrets.token_urlsafe(24))"   # POSTGRES_PASSWORD
   ```

   `POSTGRES_PASSWORD` and the password inside `DATABASE_URL` must match by hand —
   compose cannot parse the URL to configure the database container.

   Two variables in `.env` are **ignored** by this stack and that is deliberate:
   `DJANGO_SETTINGS_MODULE` and `DATABASE_URL` are forced in the compose file. A `.env`
   copied from `.env.example` still says `config.settings.dev`, and one forgotten line
   would otherwise run production with `DEBUG=True`.

2. **Bring it up.** Migrations and `collectstatic` run inside the web container's start
   command, so a bare `up -d` is a complete deploy. The worker waits for web to report
   healthy rather than racing it to a schema that does not exist yet.

3. **Seed the school** — idempotent, safe to re-run:

   ```sh
   aaroham-prod exec web python manage.py seed
   ```

   Creates one Organization, one Branch, and a superadmin (`9000000000` / `aaroham`).
   **Change that password before anything real goes in**, via `/admin` or
   `manage.py changepassword 9000000000`.

4. **Check it.**

   ```sh
   curl -k https://localhost/healthz          # 200
   aaroham-prod ps                            # postgres healthy, web healthy
   aaroham-prod logs web | head -40
   ```

### The certificate warning on localhost

With `CADDY_DOMAIN=localhost` Caddy issues from its own internal CA, so browsers warn.
Either click through it, or trust the CA once:

```sh
aaroham-prod exec caddy caddy trust
```

The warning disappears by itself when you switch to a real domain — Caddy then gets a
genuine Let's Encrypt certificate.

---

## Switching to a real domain

Cheap, and mostly not a software change.

1. **Point DNS first.** An `A` record for the domain at the server's public IP. Do this
   *before* restarting Caddy — Let's Encrypt validates by reaching the domain, and
   repeated failures get you rate-limited for hours.
2. **Edit `.env`:**
   ```
   CADDY_DOMAIN=aaroham.in
   CADDY_EMAIL=you@aaroham.in
   ALLOWED_HOSTS=aaroham.in,www.aaroham.in
   ```
   `ALLOWED_HOSTS` matters: Django returns 400 for any host not listed, and the web
   container's healthcheck sends `Host: $CADDY_DOMAIN`, so a mismatch shows up as a
   container stuck unhealthy rather than as an obvious error.
3. **Recreate**, so the new environment is picked up — a plain `restart` keeps the old one:
   ```sh
   aaroham-prod up -d --force-recreate web caddy
   ```
4. Ports **80 and 443** must be reachable from the internet. On a cloud VM that usually
   means opening them in *two* places: the provider's firewall or security list, and the
   instance's own `iptables`/`ufw`. Oracle Cloud in particular does both, and only fixing
   one is the most common reason a first deploy hangs.

---

## Moving to a server

The stack is unchanged; the host is not.

1. Provision a small VM in an Indian region (see `docs/plan.md` for the options and cost).
2. Install Docker Engine and the compose plugin. Add your user to the `docker` group.
3. `git clone` the repo, create `.env` **on the server** with freshly generated secrets —
   never copy the laptop's.
4. Run the one command. Point DNS. Done.
5. Enable the provider's snapshots. Cheapest whole-machine undo there is.

---

## Updating

```sh
git pull
aaroham-prod up -d --build
```

Migrations run automatically as part of web's start command. Watch them:

```sh
aaroham-prod logs -f web
```

**Rolling back** is `git checkout <previous-sha>` and the same command — but only for
code. A migration that dropped a column is not undone by checking out the old code, which
is why `docs/implementation-plan.md` asks for destructive migrations to be split across
two deploys a week apart.

---

## Before this carries real children's data

Phase 0 is a skeleton. Three things are **not** done yet, and each is a phase-1 item in
`docs/implementation-plan.md`:

| Gap | Consequence today | Fixed in |
|---|---|---|
| **No R2 bucket configured** | Uploads fall back to the container filesystem and vanish on the next rebuild. The web log says so loudly at boot. | Before phase 4 ships photos |
| **No backups** | A lost server is lost data. | Phase 1: nightly `pg_dump` to R2 + **a rehearsed restore** |
| **Seeded default password** | `9000000000` / `aaroham` is in a public repo's docs. | Change it now |

An untested backup is not a backup. Restore one into a clean container *before* the first
real student record exists, not after.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| `required variable POSTGRES_USER is missing a value` | Ran without `--env-file .env`, or not from the repo root. |
| Web container never reaches healthy | `ALLOWED_HOSTS` doesn't contain `CADDY_DOMAIN`, so the healthcheck gets a 400. |
| Browser certificate warning | Expected on `localhost`. Real domain, or `caddy trust`. |
| `port is already allocated` | Something else on 80/443, or a dev stack still up: `docker compose down`. |
| Static files 404 | `collectstatic` failed — check `aaroham-prod logs web` for a permissions error on `/app/staticfiles`. |
| Worker restarting | Almost always the database: check `aaroham-prod logs worker` for a connection or schema error. |
