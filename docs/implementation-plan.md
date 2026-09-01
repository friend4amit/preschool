# Aaroham — Phase-by-Phase Implementation Plan

**Two documents, one boundary.** This one owns **sequence** — phases, effort, per-phase build lists and exit criteria. [`plan.md`](./plan.md) owns **decisions** — the stack, the architecture, the data model, compliance rules, hosting and cost. Neither repeats the other; where one needs the other's material it links rather than restates. Keep it that way, or they will disagree within a month.

- **Product:** Aaroham — preschool management platform and public website.
- **Content reference:** the Udgam Learning Centre site dump at `C:\work\learn\New folder\reference` (structure only — see [Content](#content-what-transfers-from-udgam-and-what-doesnt)).
- **Team assumption:** one developer. Effort is in *working days for one person*, and is a planning estimate, not a commitment.
- **Total to Phase 8:** **68–82 working days** — call it three to four months at a steady pace, longer if this is evenings and weekends.
- **Status:** plan of record, last reviewed 2026-08-28. Revise in a PR alongside the code that proves a phase wrong.

---

## Ground rules for every phase

Each phase ends in something **deployed and usable by a real person**, not a branch. No phase is "done" until all of the following hold — this list is not repeated per phase, it applies to all of them:

| Gate | Meaning |
|---|---|
| **Deployed** | Merged to `main`, deployed to the VPS, reachable over HTTPS. |
| **Tested** | `pytest` green. Every service function has a unit test that constructs no `HttpRequest`. |
| **Layered** | `lint-imports` and `ruff` green in CI. No ORM in views, no HTTP in services. |
| **Scoped** | Every new selector goes through `for_user()`. Every new model with school data carries `branch`. |
| **Mobile-checked** | Opened on a real phone over mobile data, not a resized desktop window. |
| **Reversible** | Migrations apply cleanly to a restored production dump. |

**A note on estimates.** Phases 4 and 6 are the two that reliably overrun — photos and money both have long tails of edge cases. If the schedule slips, it will slip there, so don't schedule anything important immediately after them.

---

## Phase map

| # | Phase | Days | Ships to |
|---|---|---|---|
| 0 | [Foundations](#phase-0--foundations) | 4–5 | Nobody (but it's live) |
| 1 | [Public website](#phase-1--public-website) | 7–9 | Prospective parents |
| 1-a | [Container start/stop scripts](#phase-1-a--container-startstop-scripts) | 0.5–1 | The developer (not in the total) |
| 2 | [People & enrolment](#phase-2--people--enrolment) | 10–12 | Office staff |
| 3 | [Attendance](#phase-3--attendance) | 6–7 | Teachers |
| 4 | [Daily activities & photos](#phase-4--daily-activities--photos) | 12–14 | **Parents** |
| 5 | [AI daily reports](#phase-5--ai-daily-reports) | 4–5 | Teachers |
| 6 | [Fees & UPI](#phase-6--fees--upi) | 15–17 | Office staff, parents |
| 7 | [Announcements & dashboards](#phase-7--announcements-reports--dashboards) | 6–8 | The owner |
| 8 | [Branch two](#phase-8--branch-two) | 4–5 | The owner |
| 9 | [Beyond](#phase-9--beyond-not-scheduled) | — | — |

**Phase 4 is the one that matters.** Everything before it is scaffolding the school tolerates; the photo feed is the thing parents open daily and the reason a school pays. If you have to cut, cut from 7 — never delay 4.

---

## Phase 0 — Foundations

**4–5 days · Goal: an almost-empty application, deployed at the real domain over HTTPS, with every guardrail already switched on.**

Guardrails added later are just refactoring. This phase exists so that they never have to be.

### Build

- Repo scaffold per `plan.md`: `config/`, `apps/`, `integrations/`, `templates/{layouts,…}`, `assets/`, `deploy/`.
- Split settings (`base` / `dev` / `prod`), env via `django-environ`.
- `docker-compose.yml` — postgres + web + worker. `Dockerfile` used by both dev and prod.
- Tailwind v4 standalone CLI wired into the build; htmx 2 vendored into `static/`.
- Three layouts: `public.html`, `staff.html`, `parent.html`. They differ in nav and max-width, not in styling system.
- **`core` app, migration 0001**: custom `User`, `Organization`, `Branch`, `BranchMembership`, `Consent`.
- `selectors.py` with the `for_user()` pattern; one real example.
- `.importlinter` layer contract; `ruff`; `pytest-django` + `factory_boy`.
- `django-tasks` + `django-tasks-db`, worker container, one trivial task proving the path.
- Caddy on the VPS; deploy script; GitHub Actions running lint + lint-imports + tests.
- Sentry DSN wired for web and worker — **Session Replay off**, low trace sampling. See `plan.md` on DPDP.
- **Secrets**: `.env` on the server only, never committed; `SECRET_KEY`, DB password, R2 keys, Sentry DSN, and the Anthropic key generated fresh rather than reused from anywhere. Add `.env` to `.gitignore` in the first commit, because the one that leaks is the one added later.
- Seed command: one `Organization` ("Aaroham"), one `Branch`, one superadmin.

> **You will not have a staging environment**, and for a solo build that's the right trade — but it means migrations run first against real student data. Two habits substitute for staging: every migration is applied to a locally restored production dump before it's deployed (that's the *Reversible* gate above), and destructive migrations get split into an additive deploy and a cleanup deploy a week apart.

### Done when

- `https://<domain>` serves a styled page from the public layout.
- CI is green **and** deliberately breaking the layer contract (add `from django.http import HttpResponse` to a `services.py`) turns it red. Prove the guardrail before trusting it.
- You have run the deploy script at least twice, from a clean shell.

> **Do not skip the custom `User` model.** Swapping `AUTH_USER_MODEL` after data exists is one of the few genuinely painful things to undo in Django, and it costs nothing today.

---

## Phase 1 — Public website

**7–9 days · Goal: Aaroham has a real website, and enquiries land in the database instead of a WhatsApp DM.**

This ships first because it's the only phase with an external audience from day one, and it starts filling the admissions funnel while the rest is built. It's also where the Udgam material is actually used — and since Udgam was owned by the same people and is no longer operating, most of that copy can be edited and rebranded rather than written from scratch.

### Models (`apps/website`)

| Model | Fields worth naming |
|---|---|
| `SiteSettings` | singleton: address, phone, email, map embed, social links, UPI VPA (used later in Phase 6) |
| `TeamMember` | name, role, credentials, bio, photo, `order`, `is_published` |
| `Program` | name, age band (`from_months`, `to_months`), summary, description, `order` |
| `Testimonial` | quote, attribution, relationship, `is_published` |
| `Enquiry` | `branch`, child name, DOB, guardian name, phone, email, message, source, `status`, `created_at` |

Prose lives in templates. Only the repeating cards live in the database, editable in `/admin`. No CMS.

### Pages

`Home` · `About Us` · `Our Team` · `Programs` · `Our Approach` (Montessori method) · `Thoughtful Education` · `Contact`

### Also build

- Enquiry form → `Enquiry` + notification email to staff, protected by **Cloudflare Turnstile**.
- Staff-side enquiry list with status (`new` / `contacted` / `visited` / `admitted` / `lost`). This is the seed of Phase 2's admission flow.
- SEO: per-page `<title>` and meta description, Open Graph tags, `sitemap.xml`, `robots.txt`, and `LocalBusiness` / `Preschool` JSON-LD with the real address.
- R2 storage wired end-to-end; image upload generates thumbnails in a background task.
- Analytics: **none on public pages beyond Sentry.** See `plan.md` on DPDP.
- **Nightly `pg_dump` → R2**, 30-day retention, plus one rehearsed restore. This belongs here rather than in Phase 2: the moment the enquiry form is live you are holding children's names, dates of birth, and guardian phone numbers. Personal data arrives in Phase 1, so backups do too.

### Done when

- All seven pages render correctly at 390px and 1440px.
- Submitting the contact form creates an `Enquiry` and emails the office.
- `grep -ri "surashree\|shome\|udgam" apps/ templates/ assets/ static/` returns **nothing**. Scoped to shipped code and content — these planning docs necessarily name both, so an unscoped grep fails on itself. Then eyeball the uploaded media: a renamed file still shows the same face.
- The domain resolves and HTTPS is valid.
- **If `udgamlearningcentre.com` is still registered**: 301 redirects from the old URLs are live. Check the registrar first — a site that stopped operating has often lost the domain too, in which case there is nothing to redirect and no hosting bill to retire.

---

## Content: what transfers from Udgam, and what doesn't

Udgam ("Udgam Early Years and Daycare") was owned by the same people and is no longer operational, so **its copy and images are Aaroham's to reuse and rebrand** — not merely a shape to imitate. That's worth real days here.

It does not make the content section easy, though, and it's worth being clear why: **most of the Udgam page bodies were never finished.** What you're inheriting is a good skeleton with about four genuinely usable paragraphs in it. The table below marks what can be edited versus what still has to be written — the second column is the state of the dump, not a judgement about the school.

| Block | State in the Udgam dump | Action for Aaroham |
|---|---|---|
| Page inventory & navigation | Complete and sensible | **Adopt the structure** |
| Pedagogy pillars — Indian values & culture; learning through play & rhythm; hands-on independent learning; global practices thoughtfully applied | Real headings, thin body copy | **Adopt the four-pillar frame**, write the copy |
| "Why Early Education Matters" — warm interaction and secure attachment; peer interaction building communication and empathy; safety, nutrition and hygiene; trained teachers guiding play-based exploration | Four real, usable paragraphs | **Reuse, swapping the school name.** The strongest copy in the dump |
| Core values — "Capable & Unique", "Play-based learning" | Headings real, bodies duplicated placeholder | Write |
| Our Story / Our Mission | Fragmentary | **Write from scratch** — needs the founders' input |
| Programs | **Five tabs all labelled `ULHAAS`, no distinct content** | **Content gap.** Aaroham must define its own age bands and program names |
| Team | Two cards | Prachi Tamrakar's card carries over; **Dr. Surashree Shome is removed entirely** |
| Testimonials | Template placeholder ("Emma Markson / Father of Ethan Bentote") | **Collect real ones** from current parents, with consent. Nothing to inherit — the dump's only testimonial is Elementor's sample |
| Contact page body | Lorem ipsum | Write |
| Misc. Elementor leftovers — "Add Your Heading Text Here", "First item on the list", "Crystal Sound"/"Superior Sound" audio-kit blocks, `test@gmail.com` submissions | Boilerplate | **Ignore.** Not requirements |

> **Start the content workstream during Phase 0, not Phase 1.** Programs, mission, story, and testimonials all need a human at the school to decide and write. Writing is not on the critical path for code, but it *is* on the critical path for launching Phase 1 — and it's the item most likely to be what you're waiting on.

**Media — the one place ownership isn't the whole answer.** Room photos, materials, and staff portraits from the Udgam uploads can be reused freely; they're yours and nobody's consent is engaged.

**Photographs of children are different.** Owning the file and having consent to publish it are separate questions, and under the DPDP Act consent is bound to the purpose it was given for — a parent agreeing to photos on Udgam's site didn't agree to a different school's marketing. So: for children still enrolled, re-ask under Aaroham's `photos_in_marketing` consent, which the Phase 2 flow captures anyway. For children who have left, don't publish the photograph — the parent isn't reachable and the consent can't be refreshed. In practice a preschool marketing site needs far fewer child photos than people expect, and rooms, materials, and hands-at-work carry most of it.

---

## Phase 1-a — Container start/stop scripts

**0.5–1 day · Goal: starting and stopping the stack is one command that cannot be got wrong.**

Not a product phase and not counted in the phase totals above — a half-day of tooling
that pays for itself in Phase 2, the first phase that starts and stops the stack many
times a day: new models, repeated migrations, and a restore rehearsal.

### Why now

| Today | What it costs |
|---|---|
| `docker compose --env-file .env -f deploy/docker-compose.prod.yml up -d --build` | `--env-file` is **required**, and omitting it produces a broken `DATABASE_URL`. CLAUDE.md guards this with a paragraph of prose — prose does not run. |
| `docker run -d --name aaroham-pg …` copied out of CLAUDE.md | Retyped from the docs before every host-run `pytest` whenever the container has been pruned. Already cost a two-minute test timeout once. |
| Docker Desktop not running | Each command fails differently, and none of them says "start Docker". |

### There are three container situations, not one

This is the fact the scripts have to encode, and the reason a single "start everything"
script would be wrong:

| Target | Command today | Publishes | Postgres reachable from the host? |
|---|---|---|---|
| **dev** | `docker compose up` (project `aaroham`) | 8000, `${POSTGRES_HOST_PORT:-5432}` | Yes |
| **prod** | `--env-file .env -f deploy/docker-compose.prod.yml` (project `aaroham-prod`) | 80, 443, 443/udp | **No — deliberately** |
| **testdb** | `docker run --name aaroham-pg -p 5432:5432` | 5432 | Yes |

**dev and testdb collide on 5432.** prod and testdb do not — which is exactly why
`aaroham-pg` exists: the prod stack's database is unpublished by design, so host-run
`pytest` has nothing to connect to. The escape hatch is already in `docker-compose.yml`
as `POSTGRES_HOST_PORT`; the scripts use it rather than inventing anything.

### The hard rule: `stop` never destroys a volume

`docker compose down -v` on the prod stack destroys `postgres_data` **and**
`caddy_data` — and losing `caddy_data` means re-issuing certificates and burning
Let's Encrypt rate limit. Therefore:

- `stop` defaults to `docker compose stop` — containers halt, volumes and data untouched.
- `--down` removes containers and networks. Volumes survive.
- `--destroy` removes volumes, and **only** after a typed confirmation naming the
  target. Never reachable as a silent combination of flags.

### Deliverables

- **`scripts/start.sh`** and **`scripts/stop.sh`**, POSIX `sh`, taking a target:
  `dev` (default) | `prod` | `testdb`. One implementation, not two — `sh` runs in Git
  Bash on the Windows dev machine and natively on the VPS; a PowerShell twin would
  drift within a month.
- **Preflight in both**, cheap and worth it: Docker daemon reachable (`docker info`),
  `.env` present, target port free — with the fix named in the error, not just the fault.
- **`--env-file .env` baked into the prod path**, so the one flag that must never be
  forgotten cannot be.
- **`.gitattributes`** forcing LF on `scripts/*.sh`. A CRLF checkout gives
  `bad interpreter: /bin/sh^M` on the server — silent on Windows, fatal on Linux.
- **The exec bit committed**, via `git update-index --chmod=+x`; `chmod` alone does not
  survive a Windows checkout.
- **Docs follow through**: the CLAUDE.md commands block and the README quick start point
  at the scripts, with the raw `docker compose` lines kept underneath. The scripts are
  the convenience; the commands stay the documentation.

### Done when

- `./scripts/start.sh dev` on a machine with Docker stopped prints what to do about it,
  and on a running one brings up a migrated stack.
- `./scripts/start.sh prod` produces a working `DATABASE_URL` with no `--env-file` typed
  by hand.
- `./scripts/start.sh testdb` followed by `uv run pytest` passes with no other setup.
- `./scripts/stop.sh prod` leaves `postgres_data` and `caddy_data` intact — proven by
  starting it again and finding the data still there.
- Both scripts run unmodified in Git Bash on Windows and on a Linux host.

### Added during the build

**`scripts/test.sh`** — runs `pytest` inside the `aaroham:dev` image. `uv run pytest`
on the host stays the documented command and is right on Linux and in CI, but it does
not currently work on this Windows machine: Application Control blocks the SSL DLL
that psycopg's binary wheel loads, and pytest dies at import. The container has its
own libpq. Not planned; added because the alternative was retyping a `docker run` with
four environment variables before every test run, which is the exact thing this phase
exists to remove.

### Not in scope

No Makefile, no `just`, no task runner, no new dependency. Three shell scripts and a
`.gitattributes` line.

---

## Phase 2 — People & enrolment

**10–12 days · Goal: the office runs admissions and student records in the app instead of a spreadsheet.**

### Models

- `apps/people`: `Student`, `Guardian`, `StudentGuardian` (M2M through, with `relationship` and `is_primary`), `Staff`, `Document`, `Enrollment` (student × classroom × year, with join/leave dates).
- `apps/core` additions: `AcademicYear`, `Classroom`.

`Enrollment` sits in `people`, not `core`. An earlier draft of this line put it in
`core` and contradicted the repo layout in [`plan.md`](./plan.md) — `core` was wrong.
`AcademicYear` and `Classroom` hang off `Branch` and exist before any child does, so
they belong to the organisation; `Enrollment` is a fact about a student. Putting it in
`core` would make `core` depend on `people`, which already depends on `core` for
`BranchScopedModel` — the dependency has to point one way.

`Document` — per student: birth certificate, immunisation record, guardian ID. A file in R2, a type, an uploader, and an expiry where one applies. Small, but every school needs it, and it's far easier to add now than to retrofit into a settled `Student` page later.

### Child-safety records — build these here, not later

A preschool system that can't answer *"is this child allergic to peanuts"* or *"is this man allowed to take her home"* isn't usable by a preschool, whatever else it does. These are Phase 2 work, not a nice-to-have:

- **Medical fields on `Student`** — allergies, conditions, medications, blood group, doctor's name and number. **Allergies surface on every roster, attendance grid, and meal screen**, not in a profile tab: the person who needs the information is holding a snack, not browsing records.
- **`EmergencyContact`** — deliberately separate from `Guardian`. The person you actually call is often a grandparent or neighbour with no portal account and no legal guardianship. Ordered by priority; at least one required before an enrolment can be marked complete.
- **`AuthorizedPickup`** — name, relationship, phone, photo, and a validity window. With split families this is a legal matter rather than a convenience, and the common case is a *temporary* authorisation ("her uncle, this Friday only") — so model the window from the start rather than adding it after the first awkward afternoon.

`IncidentReport` lands in Phase 4, where the parent-facing acknowledgement flow already exists.

`Staff` is a profile attached to a `User`, not a parallel identity. A teacher gets an account the same way a parent does — an admin creates it and hands over a set-password link — and their `BranchMembership` row carries the `teacher` role. Don't build two account systems.

`Student` ← `Guardian` is many-to-many **through** a model. Siblings share guardians; split families have two primary contacts. Never put the parent on the student row.

### Screens

- Student list — htmx search-as-you-type, filter by classroom and status, **works as a plain form submit with JS off**.
- Student detail — profile, guardians, enrolment history, documents.
- Guardian add/edit, including linking an existing guardian to a second child.
- Staff list and detail.
- **Enquiry → admission**: convert an `Enquiry` into `Student` + `Guardian` + `Enrollment` in one flow, carrying the enquiry data across. This is the join between the public site and the product.
- **Account creation**: admin creates a parent `User` (phone as username) and generates a **one-time, signed, expiring set-password link** to hand over. No email required, no SMS.
- Parent portal shell: log in → "my children" → a stub child page.

### Also build

- `Consent` capture as part of admission — per guardian, per purpose, defaulting to **off**.
- `django-simple-history` on `Student` and `Consent`.
- Re-rehearse the restore from Phase 1 now that the schema is substantially bigger.

### Done when

- An enquiry from the public site becomes an enrolled student with two guardians, without retyping anything.
- A parent logs in with a handed-over link and sees their own children — and only theirs.
- **You have restored last night's backup into a clean container and it worked.** Do this before real student data exists, not after.

> **The permission test to write now and keep forever:** a parent fetching another family's student by ID gets a **404, not a 403**. Don't leak existence.

---

## Phase 3 — Attendance

**6–7 days · Goal: a teacher marks a full classroom from a phone, standing up, in under a minute.**

### Models

`AttendanceRecord` (student, date, status, reason, marked_by, marked_at) with a unique constraint on (student, date). `StaffAttendance` alongside it.

Statuses: `present` · `absent` · `late` · `half_day` · `holiday`.

### Screens

- **Daily grid** per classroom — one row per child, htmx toggle per cell, optimistic UI, "mark all present" then correct the exceptions. This is the first real htmx workout and the interaction to get right.
- Late arrival and early pickup times, with an optional note.
- **Pickup record at checkout**: who collected the child, chosen from that student's `AuthorizedPickup` list, with an explicit override path (with a reason and the staff member's name) for the parent who phones ahead. This is the screen where the Phase 2 safety records earn their keep — an authorised-pickup list nobody checks at the door is decoration.
- Backdated correction, permission-gated and recorded in history.
- Parent view: my child's month, with a simple calendar.
- Reports: monthly attendance percentage per child and per classroom.

### Done when

- A teacher marks 30 children on a phone in under a minute, on mobile data.
- A parent sees last month's attendance for their child.
- Marking the same day twice doesn't create duplicates.

---

## Phase 4 — Daily activities & photos

**12–14 days · Goal: the thing parents open every day. This is the product.**

Budget generously. Photo handling has a long tail: orientation, HEIC, huge files, failed uploads, slow connections.

### Models

- `ActivityEntry` — student (or classroom, for bulk), `kind` (`meal` / `nap` / `learning` / `note` / `milestone`), body, occurred_at, author, `is_published`.
- `IncidentReport` — **its own model, not an `ActivityEntry` kind**: severity, what happened, action taken, staff member responsible, and a **parent acknowledgement with a timestamp**. When a child is hurt, "we told the parent" needs to be a record rather than a memory. It reuses the feed's delivery but not its casual publish semantics — an incident is acknowledged, not merely seen.
- `MediaAsset` — R2 key, thumbnails, dimensions, uploader, caption, `taken_at`, `upload_state`.
- `MediaTag` — media × student. **Teacher-applied, never automatic.**

**Private bucket, short-lived presigned GET URLs**, generated from a selector that has already applied the consent gate — the reasoning is in [`plan.md`](./plan.md#compliance--a-design-input-not-an-afterthought). Getting this wrong makes every permission rule in both documents decorative, so it's the first thing to verify in this phase, not the last.

**Order the feed by `taken_at`, not `created_at`.** Teachers upload the morning's photos in the evening; a feed ordered by upload time shows parents the day backwards.

### Build

- **Teacher quick entry**: per child, and a bulk mode that writes one entry across a whole classroom (lunch, nap) in one action. The bulk path is what makes it survive contact with a real day.
- **Photo upload**: presigned direct-to-R2 from the browser, background thumbnail generation, client-side downscale before upload. Handle HEIC and EXIF orientation.
- **Tagging**: teacher taps which children are in a photo. Two taps, not a form.
- **Parent feed**: reverse-chronological, htmx infinite scroll, day separators, unread badge since last visit.
- **Consent gate**: a photo is visible to a guardian only if their child is tagged *and* `photos_in_app` consent is active. Revoking consent hides it immediately.
- **PWA**: manifest, icons, minimal service worker, an "add to home screen" nudge for parents.
- Draft/publish: teachers stage the day and publish once, so parents get a complete day rather than a trickle.
- **Orphan reconciliation.** Presigned direct upload means the browser can complete the R2 `PUT` and then fail to tell Django — or tell Django about an object that never arrived. Give `MediaAsset` an `upload_state` (`pending` / `stored` / `failed`), and run a nightly task that confirms each `pending` row against R2, promotes what landed, and deletes objects with no row. Without this you accumulate storage you're paying for and can't see.
- **Retention and erasure.** Photos of children accumulate indefinitely by default, which is the wrong default under DPDP. Decide a retention window with the school (a year after a child leaves is a common answer) and implement the per-student erasure path so that it **deletes the R2 objects too**, not just the database rows. A delete that leaves the images in the bucket isn't a delete.

> **The multi-child photo rule.** Most classroom photos contain several children, so consent is not one flag — see the four consent purposes in [`plan.md`](./plan.md#compliance--a-design-input-not-an-afterthought). Two things to build here: **a photo publishes only if every tagged child has `photos_shared_with_class`**, and the teacher sees a blocked-photo indicator *at tagging time* with the reason, so they can drop the tag, crop, or keep it for that child's own family. Build the indicator — a rule the teacher discovers only at publish time gets worked around.

**Video is out of scope for v1** — and say so to the school rather than leaving it ambiguous, because they will ask. Short clips are what parents most want after photos, but they bring transcoding, thumbnails, playback, and a storage bill an order of magnitude larger. Revisit once photos are boring.

### Done when

- A parent opens the portal on a phone and sees today's photos of their child — **and nothing of anyone else's**.
- Revoking `photos_in_app` for a guardian hides the feed on the next request.
- A 12 MP phone photo uploads over 4G without the teacher waiting on a spinner.
- Installing the PWA gives an Aaroham icon on the home screen.

> **Do not add face recognition.** Auto-tagging minors' faces is a legal and reputational minefield under the DPDP Act. Teacher tagging is a two-tap action they're already doing mentally.

---

## Phase 5 — AI daily reports

**4–5 days · Goal: a teacher writes twenty parent notes in the time five used to take.**

Cheap to build because Phase 4 already made the data. Highest-perceived-value feature in the product — this is what a school will describe to another school.

### Build

- `integrations/anthropic.py` — thin wrapper, `claude-opus-5`, `thinking={"type": "adaptive"}`, timeouts, retries, token/cost logging per call.
- Prompts in version-controlled files, not string literals in code. Prompt version stamped on every generated draft.
- **Shorthand → draft**: teacher types "ate half lunch, cried at nap, built tall tower"; Claude expands to a warm parent-facing note grounded in that day's `ActivityEntry` records.
- **Teacher reviews and edits before publishing. Nothing generated ever auto-publishes.** This is a product rule, not a setting.
- Nightly batch drafting via the **Batch API** (50% cost) so drafts are waiting in the morning.
- Translation to Hindi or the local language, per-guardian preference, on the published note.

### Done when

- A teacher accepts most drafts with light edits.
- No path exists by which unreviewed text reaches a parent.
- Per-call cost is visible; a day of reports for 50 children costs cents.

---

## Phase 6 — Fees & UPI

**15–17 days · Goal: fees are issued, paid over UPI, and reconciled inside the app.**

The other reliably-underestimated phase. Money has edge cases: siblings, mid-term joins, concessions, partial payments, refunds.

### Models

`FeeStructure` → `FeeComponent` (tuition, transport, meals, admission) · `Discount` (sibling, staff, scholarship) · `Invoice` → `InvoiceLine` · `Payment` · `CreditNote`.

`Invoice` carries `amount_paise` and a **related set of `Payment` rows** — never a `paid: bool`. Partial and late payments are the normal case here, not the exception.

**`Payment.method` is not optional, and UPI is not the only value.** Indian preschools take a lot of **cash**, and cheques still appear for annual fees. A fee module that only understands UPI pushes a third of real payments back into a paper register, which defeats the point. Support `upi` / `cash` / `cheque` / `bank_transfer` from the start — cash needs a receipt issued at the desk and a `received_by`, cheque needs a number and a clearance date, and only UPI has a UTR. The reconciliation queue then covers UPI and cheque; cash is confirmed the moment it's recorded.

**Three more that are cheap now and painful later:**

- **`CreditNote` for refunds and withdrawals.** A child leaving mid-term is a normal event. Never model a refund as a negative `Payment` — it wrecks every sum you'll write later.
- **Overpayment becomes an advance**, not a rounding mystery. Parents pay a year up front or round up; that credit has to sit against the student and auto-apply to the next invoice.
- **Issued invoices are immutable.** Once an invoice is issued you **void and reissue**; you don't edit. Along with gapless sequential receipt numbering, this is what makes the ledger defensible when a parent disputes a figure or an auditor asks.

### GST — decided: fees are taxable

This is why the phase is 15–17 days rather than 12. A GST invoice is a statutory document, and the schema has to carry tax from the first migration — retrofitting it means migrating live financial records. The design is in [`plan.md`](./plan.md#domain-model-sketch); what it means to build:

- **`InvoiceLine` carries taxable value, SAC code, rate, CGST and SGST — stored, not computed at render time.** Per line, because tuition, transport, meals, and materials can sit at different rates and any one of them can be exempt.
- **`Branch` carries the GSTIN** and registered address; place of supply is per branch.
- **Invoice numbering is gapless and sequential, restarting each financial year** — a legal requirement here, not just tidiness.
- **The tax invoice needs its statutory fields**: supplier name, address and GSTIN; invoice number and date; recipient details; SAC; description; taxable value; rate; CGST and SGST amounts; place of supply; total.
- **Credit notes reference the original invoice** and reverse its tax.
- **Rounding, decided once and tested**: at the line to the paise, at the invoice total to the rupee. Rounding drift is how ledgers quietly stop reconciling.
- **A GSTR-1 export** — a CSV of the period's invoices in the shape the school's accountant or filing software wants. Ask what they use before designing it; every practice has a preference, and matching it turns filing from a data-entry job into an upload.

> **Seed the rates with the accountant, not from this document.** Pre-school tuition is commonly *exempt* under the education notification even where other components aren't, so "fees are taxable" may well mean *some* components are. The per-component design absorbs either answer — but someone has to state which components, at which rates, before the first invoice is issued.

### Build

- Fee structure per program per academic year; generate invoices for a period in one action, prorated for mid-term joins.
- The pay-and-reconcile flow, and why the UTR rather than the invoice reference is the join key, are specified in [`plan.md`](./plan.md#payments-upi-link-reconciled-by-hand). Build it as written; the two things easiest to get wrong are rendering only the deep link (dead on a desktop browser — the QR *is* the desktop path) and trusting the requested amount instead of the credited one.
- **Reconciliation queue** for the office: everything awaiting confirmation, matched against the bank statement, one button to confirm.
- Receipts (printable HTML, gapless numbering), fee ledger per student, overdue list, reminder emails.
- **Late fees** — most Indian schools charge them. A rule on `FeeStructure` (grace days, then a flat or per-day amount) that a scheduled task applies, with a per-invoice waiver an admin can grant and that appears in the history.
- **Sibling discounts resolve at invoicing time**, not enrolment time: the second child's discount depends on how many siblings are enrolled *when the invoice is generated*, and it has to unwind correctly when the elder child leaves.
- `django-simple-history` on `Payment` — the moment a parent disputes a reconciliation, you need it.

### Done when

- A month of invoices is issued for the whole school in one action.
- A parent pays on a phone via UPI and on a laptop via QR; both reconcile.
- **A cash payment at the desk produces a numbered receipt without anyone touching a UPI screen.**
- A partial payment leaves the correct balance and the ledger reconciles to the paise.
- A mid-term withdrawal produces a credit note, and the resulting refund reconciles.
- Voiding an issued invoice and reissuing it leaves an auditable trail; editing it in place is not possible.

> Move to Razorpay when this hurts — a few hundred students, or the first time you want auto-debit mandates. The `integrations/` boundary means that's one file.

---

## Phase 7 — Announcements, reports & dashboards

**6–8 days · Goal: the owner opens one screen each morning and knows the state of the school.**

- `Announcement` — targeted at the whole school or a classroom, published with an optional expiry; read receipts per guardian.
- **Staff dashboard**: today's attendance percentage, absent list, unpaid invoice total and count, new enquiries, recent photo activity.
- **Reports**: student roster CSV, fee ledger CSV, monthly attendance register (printable), enrolment trend.
- Parent-facing announcements feed inside the portal, feeding the same unread badge as photos.

**Done when** the owner uses the dashboard instead of asking the office.

---

## Phase 8 — Branch two

**4–5 days · Goal: a second Aaroham branch, with isolated data and a combined view for the owner.**

The schema has carried `branch` since Phase 0, so this is switching things on rather than migrating.

- Reveal the branch switcher for users with more than one `BranchMembership`.
- **Audit every selector** for branch scoping. Write a test that walks the model registry and fails on any school-data model missing a `branch` FK.
- Cross-branch reporting for `superadmin` only.
- Per-branch `SiteSettings` — address, phone, UPI VPA.
- Re-evaluate managed Postgres: by now downtime costs money.

**Done when** a `branch_admin` at branch two cannot see branch one's students by any route, including `/admin` (which stays superadmin-only).

---

## Phase 9 — Beyond (not scheduled)

Each of these is triggered by a real problem, not a date:

| Add | Trigger |
|---|---|
| WhatsApp Business API | The manual parent group stops scaling. Long lead — Meta verification needs a registered business entity. |
| Razorpay | Manual reconciliation hurts, or you want auto-debit mandates. |
| SMS / OTP login | Revenue justifies DLT registration (~₹5,000 and weeks of paperwork). |
| `django-ninja` + Expo apps | Parents miss updates because of the iOS web-push gap, or teachers want camera-first flows a browser handles badly. Parent app first. |
| Managed Postgres, Redis + Celery | Downtime costs money; the DB-backed queue genuinely hurts. |

Adding `django-ninja` is mechanical rather than archaeological **because the logic already lives in `services.py`** — which is the whole reason for the layering in `plan.md`.

---

## Cross-cutting workstreams

These run alongside the phases rather than inside one.

| Workstream | Runs during | Note |
|---|---|---|
| **Content writing** | Phase 0 → 1 | The likeliest thing to be waiting on. Programs, mission, story, testimonials all need the school. |
| **Photography** | Before Phase 1 launch | Fresh images with consent; don't reuse Udgam media. |
| **Consent & DPDP** | Phase 2 onward | `Consent` model from Phase 2; export/delete path before Phase 4 ships photos. |
| **Backups** | From Phase 2 | Nightly dump, and a **rehearsed** restore. An untested backup is not a backup. |
| **Permission tests** | Every phase | Each new parent-visible model gets a cross-family 404 test the day it's added. |

---

## Risks worth tracking

| Risk | Likelihood | Mitigation |
|---|---|---|
| Content isn't ready, blocking Phase 1 | Medium *(was high — inheriting Udgam's copy removed most of it)* | Programs, mission, story, and testimonials still need writing. Start in Phase 0; launch with fewer complete pages rather than seven thin ones. |
| GST rates seeded wrong, or on the wrong components | **High** | Get the component-by-component position from the accountant in writing before the first invoice is issued. Wrong rates on issued invoices mean credit notes and refiling, not an `UPDATE`. |
| Phase 4 photo handling overruns | **High** | Budget the full 12 days. Ship the feed before the polish; downscale client-side from day one. |
| Teachers don't adopt the daily entry | Medium | The bulk-entry path is the mitigation. Watch a real teacher use it in week one of Phase 4. |
| Single server dies | Low, high impact | Nightly dump to R2 + provider snapshots + a rehearsed restore (Phase 2). |
| Fee edge cases discovered late | Medium | Model `Payment` as a set from the start; walk one real term's fees with the office *before* building Phase 6. |
| Cross-family data leak | Low, severe | The 404 test, written per phase, never deleted. |

---

## If the schedule compresses

Cut in this order, and no other:

1. **Phase 7** — dashboards are convenience; the office already knows these numbers.
2. **Phase 5** — AI drafting is high-value but the product works without it.
3. **Phase 3** — attendance can stay on paper for one more term.
4. **Phase 6** — fees can stay in the existing register, painfully, for one term.

**Never cut Phase 4.** Without the parent photo feed there is no product a school will pay for — everything else in this list is a spreadsheet replacement, and spreadsheets are free.
