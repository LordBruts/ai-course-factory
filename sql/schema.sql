-- GymRamp AI Course Factory — database schema
--
-- Plain PostgreSQL 13+ with no extensions, so the SAME file runs on:
--   * the local stack   (docker exec -i postgres-db psql -U gymramp -d gymramp -f - < schema.sql)
--   * Supabase          (SQL editor, or psql against the pooler connection string)
-- gen_random_uuid() is built in from PG13 and is also what Supabase uses.
--
-- Idempotent: every statement is IF NOT EXISTS / ON CONFLICT, so re-running is safe.
--
-- On Supabase, Row Level Security is OFF for these tables by default when created via SQL.
-- n8n connects with a server-side role, so that is fine; if the Lovable frontend ever reads
-- these tables with the anon key, enable RLS and add policies first.

-- ------------------------------------------------------------------ sources ---
-- Every piece of evidence the system has EVER seen. The unique keys are the
-- "don't reprocess research" mechanism: an insert that conflicts returns nothing,
-- so only genuinely new sources flow onward.
CREATE TABLE IF NOT EXISTS sources (
  id              bigserial PRIMARY KEY,
  source_key      text NOT NULL UNIQUE,          -- doi:..., pmid:..., nct:..., url:... (first stable id wins)
  source_type     text NOT NULL,                 -- literature | clinical_trial | regulatory | industry
  doi             text,
  pmid            text,
  pmcid           text,
  nct_id          text,
  title           text NOT NULL,
  authors         jsonb NOT NULL DEFAULT '[]',   -- [{last, initials}]
  journal         text,
  year            int,
  pub_types       jsonb NOT NULL DEFAULT '[]',
  abstract        text,
  url             text,
  is_open_access  boolean NOT NULL DEFAULT false,
  first_seen_at   timestamptz NOT NULL DEFAULT now(),
  first_topic     text
);
CREATE UNIQUE INDEX IF NOT EXISTS sources_doi_uq  ON sources (lower(doi)) WHERE doi IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS sources_pmid_uq ON sources (pmid)       WHERE pmid IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS sources_nct_uq  ON sources (nct_id)     WHERE nct_id IS NOT NULL;

-- ------------------------------------------------------------------ courses ---
CREATE TABLE IF NOT EXISTS courses (
  id               bigserial PRIMARY KEY,
  slug             text NOT NULL UNIQUE,
  title            text NOT NULL,
  topic            text NOT NULL,
  audience         text,
  status           text NOT NULL DEFAULT 'draft',
  -- draft | researching | analysing | writing | producing | in_review
  -- | approved | published | needs_revision | no_action | failed
  current_version  int NOT NULL DEFAULT 0,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS course_versions (
  id               bigserial PRIMARY KEY,
  course_id        bigint NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  version          int NOT NULL,
  status           text NOT NULL DEFAULT 'draft',
  n8n_execution_id text,
  analysis         jsonb,            -- decision, rationale, evidence levels
  outline          jsonb,
  slides           jsonb,            -- [{title, bullets[], notes}] with citations resolved
  worksheet        jsonb,
  quiz             jsonb,
  exam             jsonb,
  gate_report      jsonb,            -- citation + claim gate result
  media_job_id     text,
  failure          text,             -- last error message when status = failed
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (course_id, version)
);

-- Upgrade path for databases created before the column existed.
ALTER TABLE course_versions ADD COLUMN IF NOT EXISTS failure text;

-- Which sources a version cites, and under which marker (E01...).
CREATE TABLE IF NOT EXISTS course_sources (
  version_id  bigint NOT NULL REFERENCES course_versions(id) ON DELETE CASCADE,
  source_id   bigint NOT NULL REFERENCES sources(id),
  marker      text NOT NULL,
  cited       boolean NOT NULL DEFAULT false,
  evidence_level text,
  PRIMARY KEY (version_id, source_id)
);

-- Every factual claim the course makes, traceable to its sources.
CREATE TABLE IF NOT EXISTS claims (
  id          bigserial PRIMARY KEY,
  version_id  bigint NOT NULL REFERENCES course_versions(id) ON DELETE CASCADE,
  slide_no    int,
  text        text NOT NULL,
  markers     jsonb NOT NULL DEFAULT '[]',   -- ["E03","E07"]
  status      text NOT NULL DEFAULT 'cited'  -- cited | uncited | blocked
);

CREATE TABLE IF NOT EXISTS assets (
  id               bigserial PRIMARY KEY,
  version_id       bigint NOT NULL REFERENCES course_versions(id) ON DELETE CASCADE,
  kind             text NOT NULL,             -- pptx | mp4 | worksheet | exam | answer_key | sources
  filename         text NOT NULL,
  url              text NOT NULL,
  bytes            bigint,
  duration_seconds numeric,
  storage_backend  text NOT NULL DEFAULT 'local',   -- local | supabase
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (version_id, kind, storage_backend)
);

CREATE TABLE IF NOT EXISTS reviews (
  id          bigserial PRIMARY KEY,
  version_id  bigint NOT NULL REFERENCES course_versions(id) ON DELETE CASCADE,
  channel     text NOT NULL,                 -- gmail | slack
  decision    text NOT NULL,                 -- approved | rejected
  comments    text,
  decided_at  timestamptz NOT NULL DEFAULT now()
);

-- Stand-in for the GymRamp LMS until the real endpoint exists.
CREATE TABLE IF NOT EXISTS lms_publications (
  id            bigserial PRIMARY KEY,
  version_id    bigint NOT NULL UNIQUE REFERENCES course_versions(id) ON DELETE CASCADE,
  target        text NOT NULL DEFAULT 'mock-lms',
  payload       jsonb NOT NULL,
  published_at  timestamptz NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------ research radar ---
CREATE TABLE IF NOT EXISTS watch_topics (
  id            bigserial PRIMARY KEY,
  topic         text NOT NULL UNIQUE,
  search_hint   text,
  active        boolean NOT NULL DEFAULT true,
  last_run_at   timestamptz
);

CREATE TABLE IF NOT EXISTS research_runs (
  id            bigserial PRIMARY KEY,
  topic         text NOT NULL,
  trigger       text NOT NULL,               -- radar | course_factory
  found         int NOT NULL DEFAULT 0,
  new_sources   int NOT NULL DEFAULT 0,
  started_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS research_findings (
  id            bigserial PRIMARY KEY,
  run_id        bigint REFERENCES research_runs(id) ON DELETE SET NULL,
  topic         text NOT NULL,
  decision      text NOT NULL,               -- new_course | update_course | flag_review | no_action
  rationale     text,
  course_id     bigint REFERENCES courses(id),
  source_ids    jsonb NOT NULL DEFAULT '[]',
  status        text NOT NULL DEFAULT 'open', -- open | actioned | dismissed
  created_at    timestamptz NOT NULL DEFAULT now()
);

-- Seed: the modalities named in the GymRamp brief.
INSERT INTO watch_topics (topic, search_hint) VALUES
  ('Red light therapy / photobiomodulation', 'photobiomodulation OR "red light therapy" OR "low-level laser therapy"'),
  ('Sauna and thermal therapy',              'sauna OR "heat therapy" OR "thermal therapy"'),
  ('Cryotherapy and cold water immersion',   '"whole-body cryotherapy" OR "cold water immersion"'),
  ('Hyperbaric oxygen therapy',              '"hyperbaric oxygen"'),
  ('PEMF therapy',                           '"pulsed electromagnetic field"'),
  ('IV vitamin and hydration therapy',       '"intravenous micronutrient" OR "IV hydration"'),
  ('Peptide therapies',                      '"BPC-157" OR "peptide therapy" OR collagen peptides'),
  ('Metabolic and weight-management therapies', 'GLP-1 AND (exercise OR "resistance training")'),
  ('Recovery and compression devices',       '"pneumatic compression" OR "percussive massage"'),
  ('Longevity and rejuvenation',             'longevity AND (exercise OR "healthy aging") AND intervention')
ON CONFLICT (topic) DO NOTHING;
