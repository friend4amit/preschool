# Frontend build

CSS is Tailwind v4 via the **standalone CLI** — no Node, no `package.json`.
Get the binary from the Tailwind releases page (`tailwindcss-<platform>`), put
it on `PATH`, and run from the repo root:

```
# development — rebuild on save, readable output
tailwindcss -i assets/css/input.css -o static/css/app.css --watch

# production — what the Dockerfile runs
tailwindcss -i assets/css/input.css -o static/css/app.css --minify
```

Scan roots are declared with `@source` inside `input.css`, so the build does
not depend on the working directory. `static/css/app.css` is build output and
is gitignored — never edit it by hand.

## Fonts

Fraunces and Karla are **self-hosted** in `static/fonts/`, declared with `@font-face`
at the top level of `input.css`. Google Fonts was a third-party request logging the IP
of every parent who opened the site, which `docs/plan.md` rules out under the DPDP Act,
and a render-blocking cross-origin connection on the mobile networks these families
have. 176 KB of woff2 buys both faces outright.

These are the **variable** fonts — one file per subset covers the whole weight axis, so
the display headings get 700 without another request. To refresh them, ask Google for
the variable ranges (not fixed weights) with a modern browser User-Agent:

```sh
curl -s -A 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131 Safari/537.36' \
  'https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,100..900&family=Karla:wght@200..800&display=swap'
```

then download the `latin` and `latin-ext` woff2 files it names. The `url()` paths in
`input.css` are relative to the *built* stylesheet at `static/css/app.css`, and
WhiteNoise's manifest storage rewrites them to hashed names at `collectstatic` — so a
wrong path fails the deploy loudly rather than silently falling back to Georgia.
