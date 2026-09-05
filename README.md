# InfiniSaaS

Portfolio cockpit for the InfiniSaaS umbrella: a business dashboard that tracks
each product's stage and health, key metrics (revenue, signups, visits),
marketing campaigns, and — most importantly — a marketing-first experimentation
engine (hypothesis → run → result → learnings) across all projects.

Per project it also holds a structured product wiki, feature requests, customer
feedback, releases, a content calendar, product-event funnels, finance (Stripe /
costs / ad spend → CAC, ROAS, margin), ops (uptime probes + Railway deploys),
an SEO cockpit, and an agent framework (weekly brief, SEO, analytics, ads) whose
recommendations can become experiments or Devin sessions. "Send to Devin"
spawns a Devin session with project + wiki context prefilled, straight from the UI.

Seeded with getbetterat.xyz/blackjack, getbetterat.xyz/speedreading, and
SituationMonitor.

## Local dev

```sh
cp .env.example .env          # set DATABASE_URL
uv sync
uv run uvicorn src.main:app --reload   # init.sql is applied automatically on startup
```

Dashboard at http://localhost:8000. Auth is off unless `CLERK_JWKS_URL` is set;
agents and Devin run in mock mode until `ANTHROPIC_API_KEY` / `DEVIN_API_KEY`
are configured (see `.env.example`).

## Pushing metrics from apps

Each project has an ingest token (Project page → "Ingest token"):

```sh
curl -X POST https://<host>/api/v1/metrics \
  -H "Authorization: Bearer <ingest_token>" \
  -H "Content-Type: application/json" \
  -d '{"points": [{"metric": "revenue", "value": 129.0}, {"metric": "signups", "value": 4}]}'
```

Metric keys must already exist for the project (defaults: `visits`, `signups`,
`revenue`; add more in the UI).

Product events (same token) feed the analytics funnel:

```sh
curl -X POST https://<host>/api/v1/events \
  -H "Authorization: Bearer <ingest_token>" \
  -H "Content-Type: application/json" \
  -d '{"events": [{"name": "signup", "user_key": "u_123", "properties": {"plan": "free"}}]}'
```

Default funnel is `visit → signup → activate → pay`; override per project in
the Analytics tab.

## Deploy (Railway)

1. Create a Railway Postgres database.
2. Set `DATABASE_URL` and `SECRETS_KEY` (encrypts integration secrets) on the
   service. Optional: `CLERK_JWKS_URL` + `CLERK_PUBLISHABLE_KEY` +
   `ALLOWED_EMAILS` (auth), `ANTHROPIC_API_KEY` (agents), `DEVIN_API_KEY`
   (real Devin sessions), `RAILWAY_API_TOKEN` (ops panel), `PUBLIC_URL`.
3. Deploy with the Dockerfile (`railway.toml` handles healthcheck). The schema
   in `init.sql` is idempotent and applied automatically on startup.

## Lint / test

```sh
uv run ruff check .
uv run pytest
```
