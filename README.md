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

## Control Token
Set `CONTROL_TOKEN` in Render's Environment settings to require `X-Control-Token` (or `Authorization: Bearer ...`) for `/api/run`, `/api/keywords/refresh`, and `/api/drafts/{id}/status`. Read endpoints and the live dashboard remain viewable without the token.
