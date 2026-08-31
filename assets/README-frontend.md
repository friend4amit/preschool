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
