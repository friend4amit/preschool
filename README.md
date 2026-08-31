# Aaroham

Preschool management platform and public website. One preschool in India, more
branches later, native apps much later.

- **[`docs/plan.md`](docs/plan.md)** — stack, architecture, data model, compliance, cost.
- **[`docs/implementation-plan.md`](docs/implementation-plan.md)** — phases, effort, exit criteria.
- **[`CLAUDE.md`](CLAUDE.md)** — commands, layering rules, and the decisions not to relitigate.

Django 5.2 + htmx + Tailwind, one Postgres, one server, one deployable unit.

## Quick start

```sh
cp .env.example .env      # then edit the secrets
docker compose up         # postgres + web + worker, migrated on boot
```

Then <http://localhost:8000>. Seed a superadmin and a branch:

```sh
docker compose exec web python manage.py seed
```

Working on the host instead of in containers? `uv sync`, point `DATABASE_URL` at
`localhost`, and use `uv run python manage.py ...`. See `CLAUDE.md`.
