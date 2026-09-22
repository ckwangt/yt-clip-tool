# Admin Dashboard — Integration Notes

This session isn't linked to your computer (no connected folder right now),
so the new/changed files are handed off for you to integrate by hand into
`C:\ClaudeWorkspace\ClaudeCodePlayground\yt-clip-tool`, following your team's
convention (test locally, show me the results, I confirm before commit;
confirm again before push).

## Design decisions (answers to the 4 questions from the brief)

1. **How to record the data** → SQLite (new `db.py`), stored at
   `data/analytics.db`. e2-micro has limited resources, and SQLite is a
   single file with zero extra services — Python's built-in `sqlite3`
   needs no new dependency, and it's safer against concurrent-write
   corruption than hand-rolled JSON accumulation, while being far
   lighter than running a separate database service.

2. **How to count "Save image as..." clicks** → **No need for an extra
   `/track/save` endpoint + JS beacon.** Your last round already changed
   the download link to a distinct URL with a query param
   (`/outputs/<filename>?dl=<download_name>`), which already hits the
   server and is served via `send_from_directory(..., as_attachment=True)`
   — it's not a purely client-side action anymore. So `serve_output()`
   just logs a `save_as` event whenever the request carries a `dl` param.
   No new endpoint, no fetch/beacon, no extra failure surface.

3. **Generate count** → Logged at the end of `/process` (success or
   failure), storing `video_title` / `youtube_url` on success. The
   "which videos" list on the dashboard only shows the successful ones.

4. **Should the dashboard require auth** → Added optional HTTP Basic Auth
   (`requires_admin_auth` decorator), credentials read from env vars
   `ADMIN_USER` / `ADMIN_PASSWORD`. If `ADMIN_PASSWORD` is unset, `/admin`
   stays open (convenient for local dev), but **set `ADMIN_PASSWORD` on
   the VM before deploying** — otherwise the dashboard is public. Also
   note: since there's no Nginx/TLS in front yet, Basic Auth credentials
   would travel in the clear — worth fixing together with the TLS TODO
   later.

Presentation is kept to "numbers + a table of videos" — no charts. The
data volume is still small, and it didn't seem worth pulling in a charting
library for an internal admin page; can add one later if actually needed.

## Files added / changed

- **New** `db.py` — SQLite init + logging/query functions
- **Changed** `app.py`:
  - `import db` + `db.init_db()` at startup
  - Logs one `generate` event at the end of `/process` (wrapped in
    try/except so a logging failure never breaks the actual feature)
  - Logs one `save_as` event in `serve_output()` whenever `dl` is present
  - New `/admin` route + `requires_admin_auth` decorator
- **New** `templates/admin.html` — the dashboard page
- **Changed** `docker-compose.yml` — added a `./data:/app/data` volume
  (so the SQLite file survives container rebuilds) and
  `ADMIN_USER` / `ADMIN_PASSWORD` env vars
- **Changed** `.gitignore` — added `data/*.db` (the DB file shouldn't be
  version-controlled)

## Integration steps

1. Diff these files against your local repo and apply them
   (`app.py`, `docker-compose.yml`, `.gitignore` are full-file replacements)
2. Confirm `app.py` doesn't carry any local-debug leftovers like
   `debug=True` or `host="127.0.0.1"` (this version keeps your original
   `app.run(host="0.0.0.0", port=5000, debug=False)` unchanged)
3. Run `restart-dev.ps1` locally to start the service
4. Run `smoke-test.sh` and confirm the existing two test cases still
   PASS (this change doesn't touch `/process` or `/outputs`'s response
   shape, so it shouldn't regress, but verify per convention anyway)
5. Manually test `/admin`:
   - With no `ADMIN_PASSWORD` set, the page should load directly
   - With `ADMIN_USER` / `ADMIN_PASSWORD` set, the browser should prompt
     for Basic Auth
6. Click "Generate" and "Save image as..." a few times, reload `/admin`,
   and confirm the counts and video list update correctly
7. Once everything checks out, let me know and we'll sort out the commit
   message — you confirm before commit, and confirm again before push

## For later (not done here, just noted)

- Remember to set `ADMIN_PASSWORD` in the GitHub Actions deploy step or
  on the VM's `.env` — otherwise the dashboard is public once deployed
- Once Nginx + TLS is in place, Basic Auth won't be sent in the clear
- `get_stats()` currently does a live `COUNT` over the whole table on
  every request — fine at this scale, but if you want a time-trend chart
  later, consider adding an index or a daily rollup table