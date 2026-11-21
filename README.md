# GeneMeal SEO Bot

A lightweight, honest SEO auditing bot and live animated control dashboard for [`genemeal.onrender.com`](https://genemeal.onrender.com).

## What It Does
- **Polite robots-safe crawling**: Fetches `/robots.txt` and `/sitemap.xml`, respects `Disallow` rules, and crawls public routes with polite delays.
- **Technical & On-Page Audits**: Measures HTTP status, response time, page weight, `<title>`, `<meta name="description">`, `<h1>`/`<h2>` structure, canonical links, Open Graph / Twitter tags, JSON-LD structured data, image `alt` coverage, and broken internal links.
- **Deterministic SEO Score & CTR Rewrites**: Computes a 0–100 score across 5 dimensions and suggests higher-CTR title/meta rewrites tailored to GeneMeal's positioning ($34.97/mo real-time meal-planning subscription with weekly nutrigenomic updates; not a DNA test, not medical advice).
- **Keyword Opportunity Discovery**: Queries Google Autocomplete politely across nutrigenomic meal-planning seeds (no fabricated search volume or ranking numbers).
- **Draft Approval Queue**: Generates structured blog post outlines stored locally in SQLite (`pending` / `approved` / `rejected`). Approving a draft updates local queue state only and never publishes anywhere.
- **Live SSE Dashboard**: Streams real-time activity logs over Server-Sent Events (`/api/events`) with animated SVG gauge, Chart.js visualizations, and optional `CONTROL_TOKEN` protection on mutation endpoints.

## Running Locally
```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

## Console Login
The operator dashboard at `/` and its read APIs require a signed-in session. Sign in at `/login` with the username in `CONSOLE_USERNAME` (default `michael`) and the password that matches `CONSOLE_PASSWORD_HASH`. Sessions use a signed httpOnly `SameSite=Lax` cookie (`SESSION_SECRET`). Check **Remember me** (on by default) for a 30-day cookie, or uncheck it for a browser-session cookie that expires on the server after 12 hours. `/healthz`, `/robots.txt`, and `/sitemap.xml` stay public. If `CONSOLE_PASSWORD_HASH` is unset, the console stays locked and the login page shows `login not configured`.

Hash a password without printing the plaintext:

```bash
python scripts/hash_password.py CONSOLE_PASSWORD
```

Set the printed hash as `CONSOLE_PASSWORD_HASH` in Render. Never put the plaintext password in the environment.

## Control Token
Set `CONTROL_TOKEN` in Render's Environment settings to require `X-Control-Token` (or `Authorization: Bearer ...`) for `/api/run`, `/api/keywords/refresh`, `/api/drafts/{id}/status`, and `/api/gsc/ingest`. A signed-in console session can use those control buttons without pasting the token. Machine callers, such as the Search Console ingest routine, should keep sending the control token.

## Google Search Console Ingest
Token-protected endpoint (requires `X-Control-Token` / `CONTROL_TOKEN`):

```
POST /api/gsc/ingest
```

Payload shape:

```json
{
  "site": "https://genemeal.onrender.com/",
  "start_date": "2026-11-01",
  "end_date": "2026-11-20",
  "totals": { "clicks": 0, "impressions": 0, "ctr": 0, "position": 0 },
  "queries": [{ "query": "dna meal plan", "clicks": 0, "impressions": 0, "ctr": 0, "position": 0 }],
  "pages": [{ "page": "https://genemeal.onrender.com/", "clicks": 0, "impressions": 0, "ctr": 0, "position": 0 }]
}
```

The dashboard shows impressions, clicks, CTR, average position, top queries/pages, and last-synced time. When no rows have been ingested, it shows: "Search Console connected; Google is still collecting data, usually 2-3 days after verification".

Latest snapshots are stored in SQLite, a JSON cache file (`GSC_CACHE_PATH`, default `/tmp/gsc_latest.json`), and process memory. On Render's free plan all three are ephemeral and reset on spin-down, redeploy, or restart.

## Traction (`/app`)
Traction is a free-plan prototype for auditing additional public websites:

- Sign up / log in: `/app/signup`, `/app/login` (email + password, bcrypt, httpOnly session cookie, CSRF, rate limits)
- Add up to 3 public http(s) sites, then open `/app/sites/{id}` and run a robots-safe audit (25-page cap)
- Generic CTR title/meta rewrites for non-GeneMeal sites (GeneMeal's own rewrite behavior is unchanged)
- Displayed plans (preview only, no payment collected):
  - Free: 1 site, 1 audit per month, 25 pages per audit
  - Starter: $12/month, 1 site, weekly or on-demand audits
  - Pro: $24/month, up to 3 sites
  - One-time audit: $39–$49
  Traction still allows up to 3 sites and 25-page audits; plan limits are not enforced and payment is not enabled.

**Storage is ephemeral:** SQLite lives in `/tmp` on Render's free plan, so accounts and audits can reset on spin-down or redeploy.
