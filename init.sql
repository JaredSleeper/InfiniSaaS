CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS projects (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug         text NOT NULL UNIQUE,
    name         text NOT NULL,
    url          text,
    stage        text NOT NULL DEFAULT 'live'
                 CHECK (stage IN ('idea', 'building', 'live', 'scaling', 'paused', 'retired')),
    health       text NOT NULL DEFAULT 'unknown'
                 CHECK (health IN ('unknown', 'healthy', 'watch', 'critical')),
    description  text NOT NULL DEFAULT '',
    accent_color text NOT NULL DEFAULT '#4C8DFF',
    ingest_token text NOT NULL UNIQUE DEFAULT encode(gen_random_bytes(24), 'hex'),
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS metrics (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    key        text NOT NULL,
    name       text NOT NULL,
    unit       text NOT NULL DEFAULT '',
    kind       text NOT NULL DEFAULT 'gauge'
               CHECK (kind IN ('gauge', 'counter', 'currency')),
    is_key     boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, key)
);

CREATE TABLE IF NOT EXISTS metric_points (
    id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    metric_id uuid NOT NULL REFERENCES metrics(id) ON DELETE CASCADE,
    ts        timestamptz NOT NULL DEFAULT now(),
    value     numeric NOT NULL,
    source    text NOT NULL DEFAULT 'manual'
);

CREATE INDEX IF NOT EXISTS metric_points_metric_ts_idx
    ON metric_points (metric_id, ts DESC);

CREATE TABLE IF NOT EXISTS experiments (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id       uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name             text NOT NULL,
    hypothesis       text NOT NULL DEFAULT '',
    channel          text NOT NULL DEFAULT 'product'
                     CHECK (channel IN ('seo', 'paid', 'social', 'content', 'email',
                                        'community', 'product', 'pricing', 'other')),
    target_metric_id uuid REFERENCES metrics(id) ON DELETE SET NULL,
    status           text NOT NULL DEFAULT 'idea'
                     CHECK (status IN ('idea', 'planned', 'running', 'concluded', 'abandoned')),
    result           text CHECK (result IN ('positive', 'negative', 'inconclusive')),
    learnings        text NOT NULL DEFAULT '',
    started_at       timestamptz,
    ended_at         timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS campaigns (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name       text NOT NULL,
    channel    text NOT NULL DEFAULT 'content'
               CHECK (channel IN ('seo', 'paid', 'social', 'content', 'email',
                                  'community', 'product', 'pricing', 'other')),
    status     text NOT NULL DEFAULT 'planned'
               CHECK (status IN ('planned', 'active', 'paused', 'done')),
    budget     numeric,
    url        text,
    notes      text NOT NULL DEFAULT '',
    started_at timestamptz,
    ended_at   timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS learnings (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id    uuid REFERENCES projects(id) ON DELETE CASCADE,
    experiment_id uuid REFERENCES experiments(id) ON DELETE SET NULL,
    content       text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- Seed the first three portfolio projects.
INSERT INTO projects (slug, name, url, stage, description, accent_color) VALUES
    ('blackjack', 'Get Better At Blackjack', 'https://getbetterat.xyz/blackjack', 'live',
     'Blackjack strategy trainer under the getbetterat.xyz umbrella.', '#3FB68B'),
    ('speedreading', 'Get Better At Speedreading', 'https://getbetterat.xyz/speedreading', 'live',
     'Speedreading trainer under the getbetterat.xyz umbrella.', '#4C8DFF'),
    ('situationmonitor', 'SituationMonitor', NULL, 'live',
     'Scheduled prompt + web data monitoring pipeline (rename pending).', '#D9A03F')
ON CONFLICT (slug) DO NOTHING;

-- Default metric set for every seeded project.
INSERT INTO metrics (project_id, key, name, unit, kind, is_key)
SELECT p.id, m.key, m.name, m.unit, m.kind, m.is_key
FROM projects p
CROSS JOIN (VALUES
    ('visits',  'Visits',  '',  'counter',  false),
    ('signups', 'Signups', '',  'counter',  false),
    ('revenue', 'Revenue', '$', 'currency', true)
) AS m(key, name, unit, kind, is_key)
WHERE p.slug IN ('blackjack', 'speedreading', 'situationmonitor')
ON CONFLICT (project_id, key) DO NOTHING;

-- ────────────────────────────────────────────────────────────────────────────
-- v2: auth-ready portfolio OS — integrations, events, costs, ops, wiki,
-- requests/feedback, releases, content, Devin sessions, agents.
-- ────────────────────────────────────────────────────────────────────────────

ALTER TABLE projects ADD COLUMN IF NOT EXISTS repo_url text;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS settings jsonb NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS integrations (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id     uuid REFERENCES projects(id) ON DELETE CASCADE,
    provider       text NOT NULL
                   CHECK (provider IN ('stripe', 'github', 'railway', 'gsc', 'slack', 'custom')),
    config         jsonb NOT NULL DEFAULT '{}'::jsonb,
    secret_enc     bytea,
    status         text NOT NULL DEFAULT 'unverified'
                   CHECK (status IN ('unverified', 'ok', 'error')),
    status_detail  text NOT NULL DEFAULT '',
    last_synced_at timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (project_id, provider)
);

CREATE TABLE IF NOT EXISTS events (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name       text NOT NULL,
    user_key   text,
    ts         timestamptz NOT NULL DEFAULT now(),
    properties jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS events_project_ts_idx ON events (project_id, ts DESC);
CREATE INDEX IF NOT EXISTS events_project_name_idx ON events (project_id, name);

CREATE TABLE IF NOT EXISTS costs (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id   uuid REFERENCES projects(id) ON DELETE CASCADE,
    category     text NOT NULL DEFAULT 'other'
                 CHECK (category IN ('infra', 'ads', 'tools', 'llm', 'contractors', 'other')),
    amount       numeric NOT NULL,
    period_start date NOT NULL,
    period_end   date NOT NULL,
    note         text NOT NULL DEFAULT '',
    source       text NOT NULL DEFAULT 'manual',
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ad_spend (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id  uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    campaign_id uuid REFERENCES campaigns(id) ON DELETE SET NULL,
    platform    text NOT NULL DEFAULT 'other'
                CHECK (platform IN ('google', 'meta', 'reddit', 'x', 'tiktok', 'linkedin', 'other')),
    day         date NOT NULL,
    spend       numeric NOT NULL DEFAULT 0,
    impressions integer NOT NULL DEFAULT 0,
    clicks      integer NOT NULL DEFAULT 0,
    conversions integer NOT NULL DEFAULT 0,
    source      text NOT NULL DEFAULT 'manual',
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (project_id, platform, campaign_id, day)
);

CREATE TABLE IF NOT EXISTS uptime_checks (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id  uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    ts          timestamptz NOT NULL DEFAULT now(),
    ok          boolean NOT NULL,
    status_code integer,
    latency_ms  integer,
    error       text NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS uptime_checks_project_ts_idx ON uptime_checks (project_id, ts DESC);

CREATE TABLE IF NOT EXISTS metric_targets (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    metric_id    uuid NOT NULL REFERENCES metrics(id) ON DELETE CASCADE,
    target_value numeric NOT NULL,
    due_date     date,
    label        text NOT NULL DEFAULT '',
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS alert_rules (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    metric_id     uuid NOT NULL REFERENCES metrics(id) ON DELETE CASCADE,
    condition     text NOT NULL
                  CHECK (condition IN ('below', 'above', 'drop_pct', 'stale_days')),
    threshold     numeric NOT NULL,
    window_days   integer NOT NULL DEFAULT 7,
    enabled       boolean NOT NULL DEFAULT true,
    last_fired_at timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS wiki_pages (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    slug       text NOT NULL,
    title      text NOT NULL,
    content    text NOT NULL DEFAULT '',
    sort_order integer NOT NULL DEFAULT 100,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, slug)
);

CREATE TABLE IF NOT EXISTS feature_requests (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id    uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title         text NOT NULL,
    description   text NOT NULL DEFAULT '',
    status        text NOT NULL DEFAULT 'inbox'
                  CHECK (status IN ('inbox', 'considering', 'planned', 'building',
                                    'shipped', 'declined')),
    priority      text NOT NULL DEFAULT 'medium'
                  CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    votes         integer NOT NULL DEFAULT 0,
    experiment_id uuid REFERENCES experiments(id) ON DELETE SET NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS feedback (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id         uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source             text NOT NULL DEFAULT 'other'
                       CHECK (source IN ('email', 'in_app', 'social', 'interview', 'support',
                                         'review', 'other')),
    author             text NOT NULL DEFAULT '',
    content            text NOT NULL,
    sentiment          text NOT NULL DEFAULT 'neutral'
                       CHECK (sentiment IN ('positive', 'neutral', 'negative')),
    feature_request_id uuid REFERENCES feature_requests(id) ON DELETE SET NULL,
    created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS releases (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title       text NOT NULL,
    body        text NOT NULL DEFAULT '',
    url         text,
    external_id text,
    source      text NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'github')),
    released_at timestamptz NOT NULL DEFAULT now(),
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS releases_external_idx
    ON releases (project_id, source, external_id) WHERE external_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS content_items (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title       text NOT NULL,
    channel     text NOT NULL DEFAULT 'content'
                CHECK (channel IN ('seo', 'paid', 'social', 'content', 'email',
                                   'community', 'product', 'pricing', 'other')),
    status      text NOT NULL DEFAULT 'idea'
                CHECK (status IN ('idea', 'drafting', 'scheduled', 'published')),
    publish_at  timestamptz,
    url         text,
    notes       text NOT NULL DEFAULT '',
    campaign_id uuid REFERENCES campaigns(id) ON DELETE SET NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS devin_sessions (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  uuid REFERENCES projects(id) ON DELETE SET NULL,
    session_id  text NOT NULL UNIQUE,
    url         text NOT NULL,
    title       text NOT NULL DEFAULT '',
    prompt      text NOT NULL,
    status      text NOT NULL DEFAULT 'unknown',
    pr_url      text,
    source_type text NOT NULL DEFAULT 'manual'
                CHECK (source_type IN ('manual', 'feature_request', 'recommendation',
                                       'experiment')),
    source_id   uuid,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS seo_keywords (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    keyword     text NOT NULL,
    target_url  text,
    position    numeric,
    clicks      integer,
    impressions integer,
    ctr         numeric,
    source      text NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'gsc')),
    checked_at  timestamptz,
    notes       text NOT NULL DEFAULT '',
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, keyword)
);
ALTER TABLE seo_keywords ADD COLUMN IF NOT EXISTS ctr numeric;
ALTER TABLE seo_keywords ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'manual';

CREATE TABLE IF NOT EXISTS seo_audits (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    url        text NOT NULL,
    ts         timestamptz NOT NULL DEFAULT now(),
    score      integer NOT NULL DEFAULT 0,
    findings   jsonb NOT NULL DEFAULT '[]'::jsonb,
    page       jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS agents (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id   uuid REFERENCES projects(id) ON DELETE CASCADE,
    kind         text NOT NULL
                 CHECK (kind IN ('weekly_brief', 'seo', 'ads', 'analytics', 'custom')),
    name         text NOT NULL,
    instructions text NOT NULL DEFAULT '',
    schedule     text NOT NULL DEFAULT 'manual'
                 CHECK (schedule IN ('manual', 'daily', 'weekly')),
    enabled      boolean NOT NULL DEFAULT true,
    config       jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_run_at  timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id      uuid NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    status        text NOT NULL DEFAULT 'queued'
                  CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    trigger       text NOT NULL DEFAULT 'manual',
    started_at    timestamptz,
    finished_at   timestamptz,
    summary       text NOT NULL DEFAULT '',
    context       jsonb NOT NULL DEFAULT '{}'::jsonb,
    error         text NOT NULL DEFAULT '',
    input_tokens  integer NOT NULL DEFAULT 0,
    output_tokens integer NOT NULL DEFAULT 0,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agent_runs_agent_idx ON agent_runs (agent_id, created_at DESC);

CREATE TABLE IF NOT EXISTS recommendations (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_run_id     uuid REFERENCES agent_runs(id) ON DELETE SET NULL,
    agent_id         uuid REFERENCES agents(id) ON DELETE SET NULL,
    project_id       uuid REFERENCES projects(id) ON DELETE CASCADE,
    title            text NOT NULL,
    body             text NOT NULL DEFAULT '',
    kind             text NOT NULL DEFAULT 'task'
                     CHECK (kind IN ('experiment', 'task', 'content', 'alert', 'insight')),
    impact           text NOT NULL DEFAULT 'medium' CHECK (impact IN ('low', 'medium', 'high')),
    effort           text NOT NULL DEFAULT 'medium' CHECK (effort IN ('low', 'medium', 'high')),
    status           text NOT NULL DEFAULT 'open'
                     CHECK (status IN ('open', 'accepted', 'dismissed', 'done')),
    experiment_id    uuid REFERENCES experiments(id) ON DELETE SET NULL,
    devin_session_id uuid REFERENCES devin_sessions(id) ON DELETE SET NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS recommendations_status_idx ON recommendations (status, created_at DESC);

-- Default wiki pages for every project (idempotent).
INSERT INTO wiki_pages (project_id, slug, title, sort_order, content)
SELECT p.id, w.slug, w.title, w.sort_order, w.content
FROM projects p
CROSS JOIN (VALUES
    ('overview',    'Overview',               10, E'## What it is\n\n## Who it is for\n\n## Current status\n'),
    ('positioning', 'Positioning & ICP',      20, E'## Ideal customer\n\n## Core value proposition\n\n## Messaging pillars\n\n## Personas\n'),
    ('pricing',     'Pricing & packaging',    30, E'## Plans\n\n## Pricing history\n\n## Open questions\n'),
    ('competitors', 'Competitors',            40, E'| Competitor | Positioning | Price | Notes |\n|---|---|---|---|\n'),
    ('tech',        'Tech & infrastructure',  50, E'## Repo\n\n## Hosting / Railway\n\n## Domains & DNS\n\n## Key dependencies\n'),
    ('marketing',   'Marketing playbook',     60, E'## Channels that work\n\n## Channels tried\n\n## Assets & links\n'),
    ('ops',         'Accounts & ops',         70, E'## Accounts of record (no secrets here)\n\n## Runbooks\n')
) AS w(slug, title, sort_order, content)
ON CONFLICT (project_id, slug) DO NOTHING;
