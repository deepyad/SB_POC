-- Layer 5: conversation_blobs (durable transcript store), jobs (the queue,
-- ADR-002), results (the graded output, ADR-013), plus the dead-letter view
-- and the ingest-time parse-failure table (ADR-012). Applied by
-- pipeline.migrate, tracked in schema_migrations, safe to re-run.

CREATE TABLE IF NOT EXISTS conversation_blobs (
    tenant_id        TEXT NOT NULL,
    conversation_id  TEXT NOT NULL,
    content_hash     TEXT NOT NULL,
    raw_json         JSONB NOT NULL,
    ingested_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, conversation_id)
);

CREATE TABLE IF NOT EXISTS jobs (
    tenant_id        TEXT NOT NULL,
    conversation_id  TEXT NOT NULL,
    blob_key         TEXT NOT NULL,
    content_hash     TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'queued'
                         CHECK (status IN ('queued', 'claimed', 'done', 'dead')),
    claimed_by       TEXT,
    claimed_at       TIMESTAMPTZ,
    delivery_count   INTEGER NOT NULL DEFAULT 0,
    last_error       TEXT,
    enqueued_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, conversation_id)
);

-- The claim query (ADR-002) filters on status and orders by enqueued_at.
CREATE INDEX IF NOT EXISTS idx_jobs_status_enqueued ON jobs (status, enqueued_at);

CREATE TABLE IF NOT EXISTS results (
    tenant_id             TEXT NOT NULL,
    conversation_id       TEXT NOT NULL,
    content_hash          TEXT NOT NULL,
    status                TEXT NOT NULL CHECK (status IN ('scored', 'partial', 'rejected')),
    overall_sentiment     JSONB,
    sentiment_trajectory  JSONB,
    per_turn              JSONB NOT NULL DEFAULT '[]'::jsonb,
    dropped_turns         JSONB NOT NULL DEFAULT '[]'::jsonb,
    error                 JSONB,
    schema_version        TEXT NOT NULL,
    model_name            TEXT NOT NULL,
    model_revision        TEXT NOT NULL,
    params                JSONB NOT NULL,
    scored_at             TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, conversation_id)
);

-- Ingest-time failures that never reached a conversation_id at all (brief §4,
-- ADR-012) — e.g. a file that isn't valid JSON.
CREATE TABLE IF NOT EXISTS ingest_dead_letters (
    filename   TEXT PRIMARY KEY,
    error      TEXT NOT NULL,
    seen_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The dead-letter channel is just jobs.status = 'dead' (ADR-012) — this view
-- is where a human or a replay job looks.
CREATE OR REPLACE VIEW dead_letters AS
    SELECT * FROM jobs WHERE status = 'dead';
