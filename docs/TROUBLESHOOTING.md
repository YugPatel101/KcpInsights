# Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| "Cannot reach the KcpInsights API" / pages stay on skeletons | API not running or on another port | Start `scripts/dev.sh`, or set `KCP_API_URL` for the frontend; check `curl http://127.0.0.1:8000/api/health` |
| Port 8000 or 3000 in use | another process | `KCP_API_PORT=8001 scripts/dev.sh` (`KCP_WEB_PORT` for the web port) |
| New colours/classes do not appear after editing styles | stale Next.js dev cache | stop `scripts/dev.sh`, delete `frontend/.next`, start again |
| `next build` fails or the dev server breaks after a build | both use `frontend/.next` | stop the dev server before building; delete `.next` and restart dev afterwards |
| An IPO has no financials | its prospectus is not linked yet, still queued, scanned, or failed checks | open the IPO's **Data completeness** tab: each missing field says why, and *Offer-document sources tried* lists NSE and SEBI attempts. **System health** shows queued, backing-off and dead-letter documents |
| Many prospectuses "pending" | the documents job reads ≤ 3 per hour | `cd backend && .venv/bin/python -m app.cli process-documents --limit 20` |
| A document is a "dead letter" | 5 failed attempts (e.g. HTTP 404) | check the source URL; an admin can re-process a stored original from the Documents tab; otherwise wait for a revised link from NSE or a SEBI filing |
| "pages have no text layer … install Tesseract" | OCR not available | `brew install tesseract` / `sudo apt install tesseract-ocr`; the next run reads the image-only pages (figures stay *unverified*) |
| Q shows "insufficient" | fewer than two usable annual periods, or a required component missing | the Score breakdown tab names the missing inputs; for lenders Q stays incomplete by design (SCORING_METHODOLOGY.md §4) |
| Risk shows "—" | only the data-quality component is known | by design: a risk score needs at least one substantive input |
| Sector "Unclassified" | NSE published none and the prospectus is unread, or the classifier saw no clear lead | after the prospectus is read: `python -m app.cli reclassify` |
| Scores did not change after a code or config change | scores are stored and refreshed by jobs | `python -m app.cli refresh-scores`; formula changes must bump `ENGINE_VERSION` in `quant_engine.py` |
| Times look wrong | browser time zone | absolute times are shown in your local zone (API values are UTC) |
| Listing history is short | only issues listed in the discovery window (120 days) are imported | `python -m app.cli backfill-history --days 365` |
| "BSE: blocked" on System health | BSE refuses automated requests | expected; import BSE-only issues manually |
| Demo dates look old | synthetic fixture uses relative dates | `cd backend && .venv/bin/python -m app.cli seed-demo --reset` |
| `database is locked` | a second writer (e.g. a CLI job) while the API writes | retry; long CLI jobs and the API share the database safely but serially |
| Restored database looks inconsistent | the live WAL file was copied | restore from an `sqlite3 .backup` copy with the API stopped (SECURITY.md → Backup) |
