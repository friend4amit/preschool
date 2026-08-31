# Aaroham — Tech Stack & Architecture

**Two documents, one boundary.** This one owns **decisions** — the stack, the architecture, the data model, compliance rules, hosting and cost. [`implementation-plan.md`](./implementation-plan.md) owns **sequence** — phases, effort, per-phase build lists and exit criteria. Neither repeats the other; where one needs the other's material it links rather than restates. Keep it that way, or they will disagree within a month.

## Context

The product is **Aaroham**, a preschool management platform and public website. Work started from an empty repo. The goal is **one comprehensive, responsive website that works on laptop and phone**, for **one preschool in India**, with additional branches later and native Android/iOS apps as a much later phase. Constraints as stated:

- Strongest language: **Python**
- Own the backend + Postgres (not a BaaS)
- **India only** — no international expansion planned
- **Keep it simple, deploy as cheaply as possible**
- **No SMS/OTP login** — an admin creates every account
- **No WhatsApp integration** yet
- **Payments via a UPI link**, not a payment gateway
- The Udgam Learning Centre site dump is a **reference only**
- **Clean, layered code** — frontend, backend, and data access separated MVC-style — but **one deployable unit**

**Status:** plan of record, agreed 2026-08-28. No application code exists yet. Library versions below were checked against current docs on that date rather than recalled, so re-verify them if you start much later.

This document lives in the repo on purpose: when a decision here turns out to be wrong, change it in a PR alongside the code that proves it, rather than letting the code and the plan quietly diverge.

---

## The Udgam reference — what it tells us, and what it doesn't

The dump at `C:\work\learn\New folder\reference` is a full WordPress install for `udgamlearningcentre.com`: Elementor + Elementor Pro, ElementsKit, Essential Addons, MetForm, Cloudflare Turnstile. Content lives in the AIO-Migration SQL dumps under `wp-content/plugins/all-in-one-wp-migration/storage/`.

**It is a brochure site.** There is no student portal, no attendance, no fees, no photo sharing, no parent login — nothing of the management product. So it's a reference for **one thing: what the public-facing half of a preschool site should contain.** Everything else in this plan is net-new.

**The page inventory worth mirroring:**

| Page | Blocks it establishes |
|---|---|
| Home | Hero + tagline · "Why Early Education Matters" · Philosophy & pedagogy pillars · Programs at a glance · Testimonials · "Join the family" CTA · footer with quick links, contact details, social |
| About Us | Our Story · Our Mission · Core Values & Beliefs · Learning Environment & Ethos |
| Our Team | Per-educator cards: photo, name, credentials, short bio |
| Programs | Age-banded program cards |
| Montessori Method | Long-form pedagogy explainer |
| Special Education Awareness | Long-form topic page |
| Contact | Address + location map + enquiry form (spam-protected) |

That's a good IA for an Indian preschool and worth keeping. The pedagogy framing it uses — Indian values and culture, learning through play and rhythm, hands-on independent learning, global practices thoughtfully applied — is a sensible four-pillar structure for the philosophy section.

**Two cautions when mining it.**

1. **A lot of it is unfinished Elementor boilerplate, not requirements.** The dump contains dozens of `Add Your Heading Text Here` blocks, `First item on the list` bullets, a template testimonial ("Emma Markson / Father of Ethan Bentote, Nursery"), leftover blocks from an unrelated audio template kit ("Crystal Sound", "Superior Sound"), `test@gmail.com` form submissions, and **five program tabs all labelled `ULHAAS` with no distinct content**. Don't read placeholder text as a spec. The programs in particular are a genuine content gap the school still has to fill.
2. **Exclude all Dr. Surashree Shome content.** In the reference she is one of two team cards (alongside Prachi Tamrakar) with a bio paragraph and the image `wp-content/uploads/2026/02/surashree-shome.png`. Drop the card, the bio, and that image **including its generated thumbnail sizes** (`-150x150`, `-300x300`, and similar). Make it a checked step — scoped to shipped code and content, since these planning docs necessarily name her:

```sh
grep -ri "surashree\|shome" apps/ templates/ assets/ static/   # must be empty
```

Plus a manual pass over uploaded media: a renamed file still shows the same face, so the grep is necessary and not sufficient.

**Resolved:** Udgam was owned by the same people and is no longer operational, so **Aaroham may reuse its copy and photographs**. That removes the licensing question and makes the reference a genuine asset rather than a shape to imitate — the content table in the implementation plan changes from "write from scratch" to "edit and rebrand" for several blocks, which is worth real days in Phase 1.

Two things the ownership answer does *not* settle:

> **Copyright is not consent, and photographs of children need both.** Owning the images is one question; whether the parents agreed to their child appearing on a *different school's* marketing site is another, and the DPDP Act treats consent as bound to the purpose it was given for. A defunct school's photo library doesn't carry over on the strength of the business having changed name. For each child still enrolled, re-ask under Aaroham's `photos_in_marketing` consent — that flow exists from Phase 2 anyway. For children who have left, don't use the photograph; the parent isn't reachable and the consent can't be refreshed. Room photos, materials, and staff portraits carry no such problem and are the bulk of what a marketing site actually needs.

> **Check whether the domain is still held before planning redirects.** "No longer operational" often means the hosting lapsed and the registration is expiring or already gone. If `udgamlearningcentre.com` is still yours, 301 the old URLs at the new site and keep whatever search equity exists; if it isn't, there's nothing to redirect and no hosting bill to retire — so don't count that saving until someone has checked the registrar.

---

## v1 stack — one language, one server, no paid third parties

| Layer | Choice | Why |
|---|---|---|
| Framework | **Django 5.2 LTS** | Python, and this problem is Django's exact shape: forms, records, permissions, an admin. 6.x is current; pin the LTS for something you'll maintain for years. |
| Interactivity | **htmx 2** | Server-rendered HTML with partial updates — live attendance grids, infinite-scroll photo feeds, inline edits — with no client-side state layer and no JS build step. |
| Styling | **Tailwind CSS v4**, standalone CLI | Mobile-first breakpoints *are* the laptop-and-phone requirement. The standalone binary means no Node in your build at all. |
| DB | **PostgreSQL, self-hosted in a container on the same server** | The biggest single cost saving — managed Postgres costs more than the whole server. One container plus a nightly dump is genuinely enough for one school. Caveat below. |
| Background work | **`django-tasks`** + **`django-tasks-db`** | A backport of Django's built-in Tasks framework. Thumbnails, backups, AI drafting — **no Redis, no broker**. `manage.py db_worker` uses atomic DB locks and runs safely multi-instance: a production posture, not a dev shim. **Install both packages**: since 0.12.0 `django-tasks` ships only the dummy and immediate backends, and the DB backend is a separate distribution. |
| Media | **Cloudflare R2** via `django-storages` | Free for roughly the first year (10 GB), then cents — and **egress is free at any volume**, which is the lever that matters when parents browse photo albums. The real reason to use it: photos survive a server rebuild. Local disk in dev, R2 in prod — one setting. |
| Web server / TLS | **Caddy** | Automatic HTTPS with zero config. Replaces nginx + certbot and their renewal cron. |
| Forms / spam | Django forms + **Cloudflare Turnstile** | Free, privacy-friendly, and what the reference site already used. |
| Auth | **Django sessions. Admin creates all accounts.** | No self-service signup, no OTP, no SMS vendor, no DLT registration. |
| Payments | **UPI deep link + QR code** (`segno`), reconciled by hand | No gateway, no fees, no KYC onboarding. |
| AI | **Anthropic Python SDK**, `claude-opus-5` | Pay-per-use, no floor. |
| Errors | **Sentry** free tier | One line. |

Tests: **pytest-django + factory_boy**. Lint: **ruff**. Layer enforcement: **import-linter**. CI: **GitHub Actions** free tier.

Every external service is free-tier or pay-per-use. **The only fixed cost in the system is the server.**

### Why server-rendered, and where the line is

The public marketing pages need SEO — that's the strong case for server-rendering, not the weak one. The staff console is data-dense CRUD, which is Django's home turf (ModelForms, pagination, filtering, permissions, all free). The parent portal is a photo feed and an invoice page; `hx-get` infinite scroll is a dozen lines. A React frontend would add a second language, a second toolchain, and a second deploy for no gain on any of the three.

**The escape hatch, decided in advance:** if one screen genuinely needs rich client-side state — a drag-and-drop timetable builder, say — build *that screen* as a React island mounted into a Django template via Vite. One island is cheap; rewriting the frontend because of one screen is not.

**`/admin` is superadmin-only.** Django admin uses `_default_manager` and knows nothing about the request user, so any branch admin who reaches it sees **every branch** unless you override `get_queryset` on all 40 ModelAdmins. Keep it as your operator tool; school staff get purpose-built htmx screens. Safer *and* simpler.

---

## Code architecture: layered, MVC-style, one deployable unit

Django is **MTV**, which is MVC with different names — its *Template* is MVC's View, and its *View* is MVC's Controller. Mapped onto a strict layering, with **one rule: dependencies point downward only.**

| Layer | Lives in | May import | Must never contain |
|---|---|---|---|
| **Presentation** (MVC View) | `templates/`, `assets/` | nothing | ORM queries, business rules, inline JS beyond htmx attributes |
| **Controller** (MVC Controller) | `views.py`, `forms.py`, `urls.py` | services, forms | ORM queries, business rules, transactions |
| **Service** (business logic) | `services.py`, `tasks.py` | selectors, models, integrations | `HttpRequest`, `HttpResponse`, `request.user` as a magic global, template names |
| **Data access** (MVC Model) | `models.py`, `selectors.py`, managers | models only | HTTP anything, external API calls |
| **Integrations** | `integrations/` | stdlib + vendor SDKs | domain rules |

**What each layer is for**

- **`views.py` is a translator, not a place where things happen.** Parse the request, validate through a `Form`, call one service function, pick a template or a redirect. If a view is longer than ~15 lines or contains an `if` about business meaning, the logic belongs a layer down.
- **`services.py` is the product.** Plain functions — `enroll_student(...)`, `mark_attendance(...)`, `record_payment(...)` — that take arguments, return objects, own their `transaction.atomic()` blocks, and know nothing about HTTP. **This is the layer the future mobile API calls**, and the reason adding `django-ninja` later is mechanical rather than archaeological. It's also the layer that's genuinely pleasant to unit-test.
- **`selectors.py` holds reads.** Every non-trivial query — `students_for_branch(...)`, `unreconciled_invoices(...)` — lives here, alongside `for_user()` scoping. Nothing outside `models.py` and `selectors.py` touches the ORM. This is what makes an N+1 fixable in one place instead of twelve.
- **`integrations/` wraps every vendor** — R2 storage, Anthropic, UPI/QR generation, email, Turnstile — behind a thin interface. Tests get fakes for free, and swapping UPI-links for Razorpay later touches one file.
- **`tasks.py` entrypoints are three lines**: pull arguments, call a service. Background work and web requests then run identical code paths.

**Frontend separation, without a separate frontend.** Templates split by role, not by page: `templates/layouts/` (public / staff / parent shells), `templates/<app>/pages/` (full pages), `templates/<app>/partials/` (htmx fragments). A partial never extends a layout — that's what makes it swappable into an `hx-target`. Tailwind source lives in `assets/`, built CSS is written to `static/` by the build and never hand-edited.

**Enforce it in CI, not in code review.** `import-linter` declares the layer contract in `.importlinter` and fails the build when `services` imports `django.http` or a view imports a model manager. Roughly twenty lines of config, run alongside `ruff`, and it's what keeps the boundaries real in month eight when you're moving fast. This is the whole reason the boundaries stay honest, so wire it up in phase 0, not later.

**Layering is not deployment.** All of it ships as **one Django project, one Docker image, one `docker compose up`**. Do not split this into services or a separate frontend server: you would pay network hops, deploy orchestration, and distributed debugging for a separation you already have at the import level. The `services.py` boundary gives you every benefit people usually go microservices for — testability, a stable seam for the mobile API, swappable vendors — at zero operational cost.

**Prior art worth reading:** the HackSoftware *Django Styleguide* is essentially this services-and-selectors layout, with more examples.

---

## Auth: admin-created accounts

- **Staff and parents alike** — no signup page exists. An admin creates the account (phone number as username, since every parent has one and no parent reliably has email) and hands over a **one-time set-password link**. The school already communicates with parents; use that channel.
- **Password reset is an admin action.** At one school that's a handful of requests a term, and it removes the entire dependency on parents having working email.
- **No OTP, no SMS vendor** — this also sidesteps India's mandatory DLT registration (one-time ~₹5,000 and weeks of paperwork before a single message sends).
- **Long session expiry, "remember me" on by default.** Parents check this occasionally from a phone; weekly re-authentication is the fastest way to make the portal unused.
- **Authorization** — every read goes through a `for_user(user)` selector, which the view calls; a parent's queryset narrows further to their own children. The scoping lives in `selectors.py`, never in the view — see the layer table above.

---

## Payments: UPI link, reconciled by hand

Skipping the gateway is right at one school, but what a gateway actually buys you is **automatic confirmation**. Without it, someone reconciles — so design for that rather than discovering it.

1. Staff issue an invoice with a short unique reference — `PS-2026-0042`.
2. The invoice page renders a **UPI deep link** (`upi://pay?pa=…&am=…&tn=PS-2026-0042&tr=PS-2026-0042`) as a **tappable button on phones**, and the same URI as a **QR code on laptops**. A UPI deep link does nothing in a desktop browser, so the QR isn't a nicety — it's the desktop path. Generate it with **`segno`**: pure Python, zero dependencies, inline SVG that scales on both screens.
3. The parent pays from GPay / PhonePe / Paytm, then enters the **UTR** on the invoice page. Status → `awaiting_confirmation`.
4. An admin matches it against the bank statement and marks it paid. One screen, one button, a queue of everything awaiting confirmation.

**Know going in:**
- **Use a UPI ID on a current/business account.** Personal VPAs carry per-day limits and banks flag sustained business use.
- **`am=` prefilled means the parent shouldn't change it, not that they can't.** Always reconcile against the credited amount; never trust the request.
- **Partial and late payments are the normal case here.** Model `Invoice` with `amount_paise` and a related `Payment` set — never a `paid: bool`. Retrofitting partial payments onto a boolean is a migration you can trivially avoid.
- **Don't assume the invoice reference reaches your bank statement.** `tn` and `tr` are hints to the payer's UPI app; for a plain (non-merchant) VPA they frequently don't survive into the payee's statement narration. **The UTR the parent types is the join key** — that's why step 3 asks for it, and it's why an automatic reference-matching reconciler is not worth building here. Match UTR to statement, confirm by hand.
- **The reconciliation queue is a real screen.** ~50 students paying monthly is very manageable in the app, and completely unmanageable in someone's inbox.

Move to Razorpay when this hurts — a few hundred students, or the first time you want auto-debit mandates.

---

## Notifications in v1: there are none, and that's fine

No SMS, no WhatsApp, and parents mostly won't read email. The parent portal is **pull-based**: parents open it and see what's new. That's a real limitation — but the school already runs a parent WhatsApp group by hand, and v1 isn't trying to replace it. **v1 replaces the spreadsheet, the fee register, and the photo dumping.** Coordination stays where it already works.

Two cheap softeners: a **PWA manifest** so the portal installs to the home screen with an icon, and an **unread badge** counting new photos and announcements since the parent's last visit. Push, SMS, and WhatsApp are all additive later; none changes the data model.

---

## Deployment: one small VPS in India

**One server running `docker compose up -d`**: Caddy, Django (Gunicorn), the `db_worker`, and Postgres. Deploy with `git pull && docker compose up -d --build`, or a GitHub Action over SSH once that gets tedious. No Kubernetes, no PaaS, no managed anything.

| Option | Cost | Notes |
|---|---|---|
| **Oracle Cloud Always Free** — Mumbai / Hyderabad | **₹0** | Ampere ARM: 4 cores / 24 GB RAM / 200 GB, free indefinitely. Eyes open: free ARM capacity is often unavailable in busy regions, no SLA, idle accounts can be reclaimed. **Ideal while building.** |
| **DigitalOcean Bangalore, 2 GB droplet** ← *recommended once a school depends on it* | **~$12/mo** | Predictable, no promo-renewal cliff, real Indian region, one-click snapshots. |
| Vultr Mumbai / Linode Mumbai, 2 GB | ~$12/mo | Equivalent; pick on preference. |
| Hostinger / E2E Networks (Indian providers) | ₹500–800/mo | Often cheaper on paper — check the *renewal* price, not the promo price. |

Avoid Hetzner despite the price: no India region, and you'd be explaining an EU server for Indian children's data with no upside.

**Total: ≈ $14–15/month (₹1,200–1,300)** — the VPS at ~$12, provider snapshots at ~$1–2, plus ~₹900/year for the domain and pay-per-use Anthropic. Cloudflare, Turnstile, Sentry, GitHub Actions and payments are all ₹0, and Postgres is on the same box.

**R2 is the one free tier you should expect to outgrow.** Ten gigabytes is generous until you're storing daily photos of fifty children: at roughly 300 KB per compressed image and three photos per child per day, a 200-day school year is around 9 GB — so year two crosses the line. That's fine, and worth knowing rather than discovering: R2 beyond the free tier is about $0.015 per GB-month, so 100 GB costs ~$1.50/month, and egress stays free. Budget for a slow climb toward **$16–18/month by year three**, not a cliff.

### The honest cost of the cheap path

Self-hosted Postgres on one box means **you own backups, and one server is a single point of failure**. Correct trade at one school, but not free:

1. **Nightly `pg_dump` to R2** as a `django-tasks` job, 30 days retention.
2. **Restore it once, into a fresh container, on purpose.** An untested backup is not a backup. Do it before the first real student record exists.
3. **Enable provider snapshots** (~$1–2/mo on DO). Cheapest possible whole-machine undo.

Move to managed Postgres when downtime costs money — a connection-string change plus a restore.

---

## What "keep it simple" means concretely

### Explicitly NOT in v1

| Skipped | Add it when |
|---|---|
| Managed Postgres | Downtime costs money — i.e. after paying customers. |
| Redis + **RQ** | The DB-backed queue actually hurts: thousands of jobs/day, or scheduled fan-out. The upgrade path is `django-tasks-rq` — a settings change, no task code touched. **Celery is not a `django-tasks` backend**; moving to Celery means rewriting the task entrypoints, though the `services.py` layer keeps the actual logic untouched either way. |
| SMS / OTP / DLT registration | Never, on current plans. Admin-created accounts cover it. |
| WhatsApp Business API | The school outgrows its manual group. *(Long-lead: Meta verification takes weeks and needs a registered business entity.)* |
| Payment gateway (Razorpay) | Manual reconciliation hurts — a few hundred students, or you want auto-debit. |
| A CMS, or porting Elementor markup | Never. Prose lives in templates; repeating cards (team, programs, testimonials) live in three tiny models editable in `/admin`. |
| Alpine.js, django-cotton | htmx plus `{% include %}` stops being enough. |
| React / Next.js of any kind | One screen genuinely needs rich client state (see the escape hatch). |
| Playwright, mypy, PostHog | Possibly never. `pytest` and `ruff` are the floor and may be the ceiling for a year. |
| Search infra, caching layer, k8s | Genuinely never at this scale. Postgres and one web process go remarkably far. |

### India-only is itself a simplification — take it

- **One timezone.** `TIME_ZONE = "Asia/Kolkata"`, `USE_TZ = True`, no per-user timezone anywhere. Removes a whole category of date bugs from attendance and fee due-dates.
- **One currency.** Integer paise, `₹` hardcoded. No currency field, no FX.
- **One compliance regime.** DPDP only — no GDPR data-subject machinery, no COPPA.
- **No i18n framework yet.** Ship in English; Django's `gettext` is there for the day you add Hindi. Don't wrap strings until then.
- **One region.** No CDN strategy beyond Cloudflare's free plan in front.

### The three things NOT to simplify away

Simplicity means fewer moving parts, not fewer good decisions. These cost hours now and days-to-months later:

**1. `branch_id` on every domain row, from the first migration.** `Organization → Branch → {Student, Staff, Classroom, Invoice, …}`. One `Branch` row exists at launch; the switcher stays hidden until branch two. **One column and one FK**, not a subsystem — but retrofitting a tenant key across 40 tables once real data exists is a genuine rewrite. Shared-schema, row-scoped.

**2. A custom `User` model in migration 0001.** Even an empty subclass. Swapping `AUTH_USER_MODEL` afterwards is one of the genuinely painful things to undo in Django.

**3. The layering above, with `import-linter` enforcing it from phase 0.** It's a convention plus twenty lines of config — no dependency, no runtime cost — and it's what keeps the mobile API, the vendor swaps, and the tests cheap later. Layers added after the fact are just refactoring.

Also free: scope branches **explicitly** via `for_user(user)` in `selectors.py`. Never auto-scope the default manager through middleware or thread-locals — that silently breaks migrations, `loaddata`, shell sessions, and background tasks, none of which have a request.

---

## Laptop and phone from one codebase

- **Tailwind mobile-first**: base classes are the phone layout, `md:`/`lg:` add the laptop layout. Never two template trees.
- **Parent portal phone-first, staff console laptop-first.** Genuinely different jobs — parents check a photo feed one-handed on a bus; teachers work a 30-child attendance grid. Same codebase, different starting breakpoint.
- **Some flows differ by device by nature** — the UPI payment most clearly: tappable deep link on a phone, QR on a laptop. Render both and swap with CSS visibility, never user-agent sniffing.
- **Test on a real, cheap Android phone over mobile data.** Emulated viewports hide touch-target size, font scaling, and slow-network behaviour — and cheap Android on patchy data is what parents actually have.
- **The honest limit:** iOS web push works only after add-to-home-screen and is less reliable than APNs. That gap — not features — is what eventually justifies a native app.

---

## Repository layout

```
preschool/
  config/               settings (base/dev/prod), urls, tasks config
  apps/
    website/            public pages, TeamMember, Program, Testimonial, Enquiry
    core/               Organization, Branch, User, BranchMembership, Consent
    people/             Student, Guardian, Staff, Document, Enrollment
    attendance/
    activities/         daily timeline entries, media
    billing/            FeeStructure, Invoice, Payment, reconciliation
    comms/              announcements
  integrations/         storage_r2.py, anthropic.py, upi.py, email.py, turnstile.py
  templates/
    layouts/            public.html, staff.html, parent.html
    <app>/pages/        full pages
    <app>/partials/     htmx fragments — never extend a layout
  assets/               tailwind input.css, js  →  built into static/
  static/               build output (never hand-edited), htmx
  deploy/               Caddyfile, docker-compose.prod.yml, backup task
  docker-compose.yml    postgres + web + worker
  .importlinter         the layer contract, enforced in CI
  pyproject.toml
```

Every app under `apps/` carries the same five files — `models.py`, `selectors.py`, `services.py`, `views.py`, `forms.py` — plus `tasks.py` where it needs background work, and `tests/` split the same way. The uniformity is the point: you always know where a thing lives, and so does anyone who joins later.

One project, one deploy, one language.

### Domain model sketch

`Organization` → `Branch` → `AcademicYear` → `Classroom` → `Enrollment`

`User` (custom) + `BranchMembership` (user × branch × role: `superadmin | branch_admin | teacher | parent | accountant`). A teacher who moves branches and an owner who sees all of them both fall out of this naturally — a `role` column on `User` alone can't express either.

`Student` ← `Guardian`, many-to-many with a relationship type. Siblings and split families are the norm, so never put the parent on the student row.

`Invoice` (reference, `amount_paise`, due date, status) ← **many** `Payment` (`amount_paise`, UTR, `recorded_by`, `confirmed_at`).

**Fees are GST-taxable, so the invoice is a statutory document, not a formatted total.** This is a schema decision and it lands in the first version of the billing models — bolting tax onto a settled invoice table later means migrating live financial records, which is the one migration you least want to do:

- **Tax lives on `InvoiceLine`, per component, not on `Invoice`.** Rate is a property of what's being charged — tuition, transport, meals, and materials can differ, and a component can be exempt while its neighbours aren't. A single invoice-level rate cannot express that and will have to be unpicked.
- Each line carries **taxable value, SAC code, rate, and the CGST and SGST amounts** as stored integers — not computed on render. A tax figure that recalculates when you display an old invoice is a figure you cannot defend. A single-state preschool is always an intra-state supply, so it's CGST + SGST at half the rate each; IGST doesn't arise and isn't worth modelling.
- **`Branch` carries the GSTIN** and the registered address, because place of supply is per branch and branch two may register separately.
- **Round once, at the line, to the paise; round the invoice total to the rupee.** Decide it once and test it, because rounding drift is how ledgers stop reconciling.
- **Sequential gapless invoice numbering, restarting each financial year.** Already good practice above — under GST it's a requirement.
- **Credit notes must reference the original invoice** and carry their own tax reversal. Another reason refunds are a `CreditNote` and never a negative `Payment`.

Tuition at a pre-school is commonly *exempt* under the education notification, so the school's accountant should confirm which components they're actually charging on before the rates are seeded. The per-component design above is what makes that answer cheap to apply either way.

`Enquiry` (from the public contact form) → converts to `Student` + `Guardian` on admission. **This is the join between the two halves of the product** — the contact form is the front of the admissions funnel, and wiring it straight into enrolment is exactly what a brochure site can't do. Note that `Enquiry` carries `branch` like everything else: once there are two branches, a parent is enquiring about *one* of them, and the enquiry list has to be scoped for the branch admin who works it.

`Document` (per student: birth certificate, immunisation record, guardian ID) — a file in R2, a type, an uploader, and an expiry where one applies. Small, but every school needs it and it's easier to add in Phase 2 than to retrofit into a settled `Student` page.

**Child-safety records — not optional, and not a later phase.** A system that can't answer "is this child allergic to peanuts" or "is this man allowed to take her home" is not usable by a preschool, whatever else it does. So `Student` carries medical fields, and **`EmergencyContact`** and **`AuthorizedPickup`** are first-class models built alongside it — the first separate from `Guardian` because the person you actually call is often a grandparent with no account, the second carrying a validity window because "her uncle, this Friday only" is the common case. **`IncidentReport`** is likewise its own model rather than a note, because it needs a parent acknowledgement with a timestamp: when a child is hurt, "we told the parent" has to be a record, not a memory. Fields and screens are in the implementation plan.

`AttendanceRecord`, `ActivityEntry`, `MediaAsset` all hang off `Branch` + `Student`.

---

## AI features (the "AI" in the README)

Layer these on **after** the CRUD works — worthless without data underneath, and the easiest thing to over-invest in early.

1. **Daily report drafting** — teacher types shorthand ("ate half lunch, cried at nap, built tall tower"), Claude expands it into a warm parent-facing note. Highest-value feature by a distance; teachers hate writing 20 of these a day. **Build this one first and possibly alone.**
2. **Translation** — the same note in Hindi or the local language, per-parent preference. (Content, not UI strings, so the "no i18n framework" call still holds.)
3. **Admissions enquiry assistant** on the public site, grounded in real fee and timing data.
4. **Photo captioning and scene-tagging**, to make the album searchable.

Model: **`claude-opus-5`** via the `anthropic` Python SDK, `thinking={"type": "adaptive"}`. $5 / $25 per million input / output tokens — a day of reports for a 50-child school is cents. Levers if it ever matters: the **Batch API** (50% off, ideal for a nightly job drafting every report at once) and `output_config={"effort": "low"}` for short formulaic generations. Call it from a background task, never inline in a request; with htmx that's natural — the view enqueues, the fragment polls the result in.

> **Do not build automatic face recognition on children.** Auto-tagging minors' faces is a legal and PR minefield under the DPDP Act. Let teachers tag who's in a photo — a two-tap action they're already doing mentally.

---

## Compliance — a design input, not an afterthought

India's **DPDP Act 2023** requires **verifiable parental consent** before processing a child's data, and prohibits tracking or behaviourally targeted advertising directed at children. From the first schema:

- A `Consent` model: per-guardian, per-purpose, versioned, timestamped, revocable, defaulting to **off**. Admin-created accounts make this easier — consent is captured at the same desk where the account is created. Four purposes, and the distinction between the first two is the one that matters:
  - **`photos_in_app`** — we may show photos of our child, to us.
  - **`photos_shared_with_class`** — our child may *appear* in photos shown to other enrolled families. Most classroom photos contain several children, so without this separate flag you end up showing child B's face to child A's family on the strength of A's consent, which is precisely backwards. **A photo is publishable only if every tagged child carries this consent.**
  - **`photos_in_marketing`** — what keeps a child's face off the public site by accident.
  - **`comms`**.
- Photo visibility strictly scoped to the guardians of tagged children. **Write one test that a parent cannot fetch another family's child or photo by ID, and keep it green forever** — cross-family photo leakage is the reputational failure mode here. Return 404, not 403; don't leak existence.
- **The R2 bucket is private; photos are served by short-lived presigned GET URLs** generated after the consent check. Every rule above is decorative if the object itself has a public URL — URLs get forwarded, cached, and indexed, and none of that passes through your permission code. Don't proxy the bytes through Django to fix it: that trades R2's free egress for VPS egress. Presigned URLs keep the bandwidth on Cloudflare and the authorisation in your code.
- **Erasure has to reach the bucket.** The per-student delete path must remove R2 objects, not only database rows. Agree a retention window with the school — a year after a child leaves is a common answer — because "keep every photo forever" is a decision, and the wrong one.
- `django-simple-history` on `Student`, `Consent`, and `Payment` only — not everywhere. (Payment history matters the moment a parent disputes a reconciliation.)
- The India-only server choice already answers data residency. Build the per-student export/delete path early rather than when someone asks.
- **No behavioural analytics on parent-facing pages.** Sentry for errors only — and explicitly **disable Session Replay and set a low traces sample rate on parent routes**. Replay records the screen, which on a page of children's photos is precisely the processing the Act is pointed at. "We only use Sentry" isn't a defence if Sentry is recording sessions.

---

## Build order — see the implementation plan

The sequence, the effort estimates, the per-phase build lists and exit criteria all live in **[`implementation-plan.md`](./implementation-plan.md)**. They are deliberately not repeated here; two copies of a nine-phase plan diverge the first time one is edited.

What belongs here is the *reasoning* behind the order, because that's a decision rather than a schedule:

- **Foundations before features.** The layer contract, the custom `User`, and `branch` on every row cost hours in phase 0 and weeks at any later point. Guardrails added afterwards are just refactoring.
- **The public site ships second, not last.** It's the only early phase with an external audience, and its enquiry form is the front of the admissions funnel — so it earns its keep while the rest is built rather than waiting on it.
- **Records, then attendance, then the photo feed.** Each leans on the one before: attendance needs classrooms, the feed needs children to tag.
- **The photo feed is the product.** Everything before it replaces a spreadsheet, and spreadsheets are free. It's the reason a school pays, so it is never the thing that slips.
- **Fees come after the feed.** Money is where the edge cases live, and a school will tolerate the old fee register far longer than it will tolerate no photos.
- **Branch two is a switch, not a migration** — but only because `branch` was there from the first migration.
