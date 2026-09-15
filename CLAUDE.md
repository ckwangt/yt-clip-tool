# CLAUDE.md

This file gives Claude Code context for working in this repository.

## Project overview

A small Flask web app: paste a YouTube URL and a time range, get back a
screenshot from the start second plus all subtitle text within that range,
merged into one block. Portfolio / side project, not a commercial product.

## Architecture

- `app.py` — Flask routes only. `/` (GET) renders the form, `/process`
  (POST) runs the extraction and re-renders the page with results or an
  error, `/outputs/<filename>` serves generated screenshots.
- `core.py` — all the actual logic: resolving the video via yt-dlp,
  picking/downloading subtitles, parsing VTT, merging YouTube's "rolling"
  auto-caption duplication (word/char-level diff), and capturing a frame
  with ffmpeg. `process_clip()` is the single entry point `app.py` calls.
- `i18n.py` — static EN/ZH translation dict for all UI-facing strings.
  `app.py` reads `?lang=` (GET) or a hidden `lang` form field (POST) to
  pick the language; defaults to `en`.
- `templates/index.html` — single page, renders everything through the
  `t` dict passed from `app.py`. No other templates.
- `.github/workflows/deploy.yml` — on push to `main`, SSHes into the
  production VM and runs `git pull && docker compose up -d --build`.

## Tech stack

Flask, yt-dlp, ffmpeg (system binary, not a Python package), Flask-Limiter
for rate limiting, gunicorn in production, Docker/Docker Compose for
packaging and deployment.

## Common commands

```bash
# Local run (dev)
python3 app.py                      # serves on :5000

# Local run (prod-like)
gunicorn -w 4 -b 0.0.0.0:5000 --timeout 120 app:app

# Docker
docker compose up -d --build        # build + run
docker compose logs -f              # tail logs
docker compose down                 # stop

# Syntax/sanity check after editing app.py or core.py
python3 -m py_compile app.py core.py
```

No automated test suite yet. When adding one, prefer `pytest` and put
fixtures/sample VTT content inline rather than fetching real YouTube URLs
in tests — network calls to YouTube should never be part of the test path.

## Conventions

- **All code, comments, docstrings, and UI strings are English.** User-
  facing text goes through `i18n.py`, not hardcoded in `templates/` or
  `app.py` — if you add a new UI string, add it to both `en` and `zh` in
  `TRANSLATIONS` and reference it via `t["key"]`, don't inline English
  text in the template.
- Keep `core.py` free of Flask imports — it should stay usable/testable
  standalone. `app.py` is the only place that touches `request`,
  `render_template`, etc.
- Any function that fetches an external URL based on user input must go
  through `validate_youtube_url()` first (see the domain allowlist in
  `core.py`) — don't add a new fetch path that bypasses it.
- Rate limits live in `app.py` via Flask-Limiter. If you add a new route
  that calls yt-dlp/ffmpeg, apply a `@limiter.limit(...)` decorator
  consistent with the existing `/process` limit (resource-intensive
  routes are limited more tightly than the default).

## Deployment

Production runs on a GCP `e2-micro` VM (`us-west1`, Always Free tier —
stay within e2-micro / standard persistent disk / ≤30GB to keep it free).
Deploys are automatic: push to `main` → GitHub Actions SSHes in and
rebuilds via Docker Compose (see `.github/workflows/deploy.yml`). No
manual deploy step should be needed for normal changes.

Nginx + Let's Encrypt (TLS termination) sit in front of the container on
the VM, outside of this repo's Docker setup — see `README.md` for that
config if it needs changing.

## Things to be careful about

- Never remove or weaken `validate_youtube_url()`'s domain allowlist —
  it's the main defense against the service being used as an open proxy.
- Don't lower the `/process` rate limit below what's reasonable for a
  route that shells out to ffmpeg; this runs on a 1GB-RAM free-tier VM.
- `README.md` should stay accurate to whatever deployment method is
  actually in use — update it in the same change if deployment steps
  change.
