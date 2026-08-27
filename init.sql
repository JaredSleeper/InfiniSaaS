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
