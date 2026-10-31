# Security

## Controls in place

| Area | Control | Where |
|---|---|---|
| Passwords | Argon2id (argon2-cffi defaults), minimum 10 characters with letters and digits, must not contain the e-mail name; constant-time dummy verification for unknown e-mails | `core/security.py` |
| Sessions | Opaque 256-bit tokens stored only as SHA-256; HttpOnly, SameSite=Lax cookie (Secure in production); idle and absolute expiry; revocation on password reset | `routes/auth.py`, `api/deps.py` |
| CSRF | Per-session token required in `X-CSRF-Token` on every POST/PATCH/PUT/DELETE, compared in constant time; cross-origin state-changing requests rejected by an Origin check | `api/deps.py`, `main.py` |
| CORS | Only the configured origins (`KCP_CORS_ORIGINS`), limited methods and headers; the browser normally uses the same-origin Next.js proxy | `main.py` |
| Authorization | Admin-only: data sync, document reprocessing, configuration publishing, source fetch. Reports and watchlists are per user; another user's report answers 404. IPO edits only by the importer or an admin | routes |
| Rate limiting | Login (8 per IP+e-mail / 5 min, 30 per IP), registration, reports, imports, uploads, source fetch, re-analysis | `core/rate_limit.py` |
| SSRF | Server-side fetching only from allowlisted official hosts over HTTPS (NSE archives, SEBI); redirects not followed; streamed size caps; SEBI PDF links are re-validated against the SEBI host before download | `ingestion/http.py`, `document_service.py`, `sources/sebi.py` |
| Archives | Zip members checked for size and compression ratio (zip-bomb guard); never extracted to disk by member path; PDFs stored under their SHA-256 name | `document_service.pick_pdf` |
| PDF parsing | Text and word positions only; nothing in a document is executed or followed; page limits | `financials/*` |
| Uploads | Size limit (`KCP_MAX_UPLOAD_MB`), page limit, type check, prompt-injection-style text flagged; served by id only | `routes/data.py` |
| Files | Originals served by document id, path resolved inside the data directory, `X-Content-Type-Options: nosniff` | `routes/research.py` |
| Headers | API: `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control`, CSP `default-src 'none'`, HSTS in production. Web: nosniff, `X-Frame-Options: DENY`, strict referrer, `Permissions-Policy` | `main.py`, `next.config.ts` |
| Errors | One error envelope; unhandled exceptions logged server-side, client gets "An unexpected error occurred" — no stack traces, paths or SQL | `core/errors.py` |
| Logging | Lines containing passwords, session cookies, CSRF tokens or API keys are redacted | `main.py` |
| Database | SQLAlchemy ORM/bound parameters only; no string-built SQL | everywhere |
| Secrets | Only from environment variables (`KCP_*`); none committed; no default admin — `python -m app.cli create-admin` prompts | `config.py`, `cli.py` |
| Audit log | Logins, registrations, imports, reports, edits, configuration changes, data syncs, document reprocessing | `audit_logs` |

## Checks run (31 Oct 2026)

| Check | Result |
|---|---|
| `ruff` with flake8-bandit rules (`S`) over `backend/app` | clean (one `assert` used for control flow was replaced) |
| Backend tests for auth, CSRF, authorization, rate limits, SSRF allowlist, zip-bomb guard | pass (see TESTING.md) |
| `npm audit --omit=dev` (runtime dependencies) | 5 advisories, all in Next.js 16.2.9 and the packages it bundles — see below |
| `pip-audit` | not installed in this environment; run `pip install pip-audit && pip-audit -r backend/requirements.txt` |

### npm advisories and their applicability

* **`shadcn` CLI** (bundling an MCP server, Express, Hono): was a runtime dependency though only its
  CSS is imported at build time → moved to devDependencies; it never runs in the served app.
* **Next.js ≤ 16.4.0** — middleware/proxy bypass, Server Actions DoS and SSRF; **postcss**, **sharp**
  through Next. KcpInsights has no `middleware`/`proxy` file, no Server Actions and no `next/image`,
  so the reachable surface is small; postcss runs only on the project's own CSS at build time.
  **Remediation:** upgrade `next` and `eslint-config-next` to ≥ 16.4.3 (released 23 Oct 2026, eight
  days before this audit) once it has had time to settle, then run the build and the page checks in
  TESTING.md.
* **fast-uri** (through `@hookform/resolvers` → ajv) and **baseline-browser-mapping** (build tooling):
  `npm audit fix` resolves them without breaking changes.

## Known limitations

* Rate limiting is in-process: correct for one API process, not shared across several workers.
* No e-mail verification, self-service password reset or MFA (`python -m app.cli reset-password <email>`).
* PDF parsing (PyMuPDF, pypdf) and OCR run in the API process without a sandbox; documents come only
  from allowlisted official hosts or signed-in uploads.
* SQLite has no per-user database permissions; protect the `backend/data` directory at the OS level.

## Backup and recovery

The database is `backend/data/kcpinsights.db` (WAL mode). Never copy the file while the API runs —
use SQLite's online backup:

```bash
sqlite3 backend/data/kcpinsights.db ".backup backend/data/backup-$(date +%Y%m%d).db"
```

Restore by stopping the API, replacing `kcpinsights.db` with the backup (and removing the `-wal`/`-shm`
files), then `python -m app.cli migrate`. Original prospectuses live in `backend/data/documents/` and
can be re-downloaded by the documents job; extracted figures live in the database.

## Reporting

This is a portfolio project without a security contact. If you deploy it, add one and a
`/.well-known/security.txt`.
