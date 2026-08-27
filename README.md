# InfiniSaaS

Portfolio cockpit for the InfiniSaaS umbrella: a business dashboard that tracks
each product's stage and health, key metrics (revenue, signups, visits),
marketing campaigns, and — most importantly — a marketing-first experimentation
engine (hypothesis → run → result → learnings) across all projects.

Seeded with getbetterat.xyz/blackjack, getbetterat.xyz/speedreading, and
SituationMonitor.

## Local dev

```sh
cp .env.example .env          # set DATABASE_URL
uv sync
uv run uvicorn src.main:app --reload   # init.sql is applied automatically on startup
```

Dashboard at http://localhost:8000. No auth (private deploy).

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

## Deploy (Railway)

1. Create a Railway Postgres database.
2. Set `DATABASE_URL` on the service.
3. Deploy with the Dockerfile (`railway.toml` handles healthcheck). The schema
   in `init.sql` is idempotent and applied automatically on startup.

## Lint / test

```sh
uv run ruff check .
uv run pytest
```
