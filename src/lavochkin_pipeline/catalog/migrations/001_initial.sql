BEGIN;

CREATE SCHEMA IF NOT EXISTS catalog;

CREATE TABLE catalog.schema_migrations (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE catalog.import_runs (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_path text NOT NULL,
    source_sha256 text NOT NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    status text NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'failed')),
    statistics jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE catalog.documents (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ntrs_id text NOT NULL UNIQUE CHECK (btrim(ntrs_id) <> ''),
    title text NOT NULL DEFAULT '',
    abstract text NOT NULL DEFAULT '',
    document_type text,
    source_url text,
    publication_date date,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE catalog.document_versions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id bigint NOT NULL REFERENCES catalog.documents(id),
    import_run_id bigint NOT NULL REFERENCES catalog.import_runs(id),
    record_sha256 text NOT NULL,
    has_nonempty_text boolean NOT NULL,
    full_text text NOT NULL DEFAULT '',
    page_parts jsonb,
    page_sources jsonb,
    source_record jsonb NOT NULL,
    imported_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, record_sha256)
);

CREATE TABLE catalog.document_current_versions (
    document_id bigint PRIMARY KEY REFERENCES catalog.documents(id),
    version_id bigint NOT NULL UNIQUE
        REFERENCES catalog.document_versions(id)
);

CREATE TABLE catalog.topic_models (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    model_key text NOT NULL UNIQUE,
    method text NOT NULL,
    topic_count integer NOT NULL CHECK (topic_count > 0),
    representative_seed integer,
    parameters jsonb NOT NULL DEFAULT '{}'::jsonb,
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE catalog.topics (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    model_id bigint NOT NULL REFERENCES catalog.topic_models(id),
    topic_number integer NOT NULL CHECK (topic_number >= 0),
    label text,
    interpretation_status text NOT NULL DEFAULT 'unreviewed'
        CHECK (interpretation_status IN ('unreviewed', 'draft', 'approved')),
    top_terms jsonb NOT NULL DEFAULT '[]'::jsonb,
    mean_matched_cosine double precision
        CHECK (mean_matched_cosine BETWEEN 0 AND 1),
    UNIQUE (model_id, topic_number)
);

CREATE TABLE catalog.document_topics (
    document_id bigint NOT NULL REFERENCES catalog.documents(id),
    topic_id bigint NOT NULL REFERENCES catalog.topics(id),
    relative_weight double precision NOT NULL
        CHECK (relative_weight BETWEEN 0 AND 1),
    import_run_id bigint NOT NULL REFERENCES catalog.import_runs(id),
    PRIMARY KEY (document_id, topic_id)
);

CREATE TABLE catalog.missions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    mission_key text NOT NULL UNIQUE,
    name text NOT NULL,
    description text NOT NULL DEFAULT ''
);

CREATE TABLE catalog.mission_aliases (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    mission_id bigint NOT NULL REFERENCES catalog.missions(id),
    alias text NOT NULL CHECK (btrim(alias) <> ''),
    UNIQUE (mission_id, alias)
);

CREATE TABLE catalog.document_missions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id bigint NOT NULL REFERENCES catalog.documents(id),
    mission_id bigint NOT NULL REFERENCES catalog.missions(id),
    relation_type text NOT NULL DEFAULT 'unspecified'
        CHECK (relation_type IN (
            'dedicated', 'discussion', 'mention', 'unspecified'
        )),
    UNIQUE (document_id, mission_id, relation_type)
);

CREATE TABLE catalog.mission_evidence (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    relation_id bigint NOT NULL REFERENCES catalog.document_missions(id),
    document_version_id bigint REFERENCES catalog.document_versions(id),
    method text NOT NULL,
    fragment text,
    page_number integer CHECK (page_number > 0),
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE catalog.mission_reviews (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    relation_id bigint NOT NULL REFERENCES catalog.document_missions(id),
    decision text NOT NULL
        CHECK (decision IN ('confirmed', 'rejected', 'needs_clarification')),
    reviewer text NOT NULL CHECK (btrim(reviewer) <> ''),
    comment text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE catalog.document_search (
    document_id bigint PRIMARY KEY REFERENCES catalog.documents(id),
    search_vector tsvector NOT NULL
);

CREATE INDEX document_search_gin
    ON catalog.document_search USING gin(search_vector);

CREATE INDEX document_topics_by_topic
    ON catalog.document_topics(topic_id, relative_weight DESC);

CREATE INDEX document_missions_by_mission
    ON catalog.document_missions(mission_id);

CREATE INDEX mission_reviews_by_relation
    ON catalog.mission_reviews(relation_id, created_at DESC, id DESC);

CREATE VIEW catalog.current_mission_reviews AS
SELECT DISTINCT ON (relation_id)
    relation_id, decision, reviewer, comment, created_at
FROM catalog.mission_reviews
ORDER BY relation_id, created_at DESC, id DESC;

INSERT INTO catalog.schema_migrations(version)
VALUES ('001_initial');

COMMIT;