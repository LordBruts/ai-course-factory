-- GymRamp HyperFrame — video production schema (applied ON TOP of schema.sql)
--
-- Same rules as the base schema: plain PostgreSQL, no extensions, idempotent, and
-- Supabase-compatible. Every query written against these tables must still return
-- exactly one row, so an empty result never stops an n8n branch.
--
--   docker exec -i postgres-db psql -U gymramp_hf -d gymramp_hf -f - < sql/video-schema.sql

-- ------------------------------------------------------- course_versions ---
-- The chosen presentation style lives on the version, so a style change never
-- touches research, analysis or course content.
ALTER TABLE course_versions ADD COLUMN IF NOT EXISTS video_template text NOT NULL DEFAULT 'not_selected';
ALTER TABLE course_versions ADD COLUMN IF NOT EXISTS video_render_id bigint;

DO $$ BEGIN
  ALTER TABLE course_versions ADD CONSTRAINT course_versions_video_template_ck
    CHECK (video_template IN ('not_selected', 'faceless', 'face'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ----------------------------------------------------------- video_renders ---
-- One row per render attempt. An approved render is never overwritten: a new
-- template or a regeneration inserts the next video_version instead.
CREATE TABLE IF NOT EXISTS video_renders (
  id                bigserial PRIMARY KEY,
  version_id        bigint NOT NULL REFERENCES course_versions(id) ON DELETE CASCADE,
  template          text NOT NULL CHECK (template IN ('faceless', 'face')),
  video_version     int  NOT NULL,                   -- 1, 2, 3 … per (version_id, template)
  job_id            text,                            -- worker job id
  status            text NOT NULL DEFAULT 'queued',
  stage             text,                            -- queued|preparing|transcribing|storyboarding|
                                                     -- generating_assets|composing|rendering|quality_check
  source_version    text,                            -- hash of the approved package the render was built from
  presenter_source  jsonb,                           -- PresenterVideoSource (face template only)
  storyboard_id     bigint,
  duration_seconds  numeric,
  width             int,
  height            int,
  fps               numeric,
  bytes             bigint,
  qa                jsonb,                           -- video_qa.json
  qa_passed         boolean,
  attempts          int NOT NULL DEFAULT 0,          -- self-evaluation loop, capped at 3
  failure_stage     text,
  failure_reason    text,
  retryable         boolean,
  cost              jsonb,                           -- { scribe_seconds, tts_characters, llm_calls, heygen_credits }
  rendered_at       timestamptz,
  approved_at       timestamptz,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (version_id, template, video_version)
);
CREATE INDEX IF NOT EXISTS video_renders_version_idx ON video_renders (version_id, template, video_version DESC);
CREATE INDEX IF NOT EXISTS video_renders_status_idx  ON video_renders (status);

DO $$ BEGIN
  ALTER TABLE course_versions ADD CONSTRAINT course_versions_video_render_fk
    FOREIGN KEY (video_render_id) REFERENCES video_renders(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ------------------------------------------------------------- storyboards ---
-- A storyboard is a production artifact, kept so a render can be explained and
-- reproduced: which visual treatment each narration beat received, and why.
CREATE TABLE IF NOT EXISTS storyboards (
  id              bigserial PRIMARY KEY,
  version_id      bigint NOT NULL REFERENCES course_versions(id) ON DELETE CASCADE,
  template        text NOT NULL CHECK (template IN ('faceless', 'face')),
  content_hash    text NOT NULL,                    -- narration + template + rules version + prompt version
  segments        jsonb NOT NULL,                   -- Storyboard.segments[]
  decided_by      text NOT NULL DEFAULT 'rules',    -- rules | rules+llm | agent
  model           text,
  reasoning_notes text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (version_id, template, content_hash)
);

-- ----------------------------------------------------------- video_assets ---
-- Every visual asset that reaches a frame, with provenance and licence. An asset
-- with no licence recorded is not usable in a render.
CREATE TABLE IF NOT EXISTS video_assets (
  id            bigserial PRIMARY KEY,
  asset_id      text NOT NULL UNIQUE,               -- stable content id
  version_id    bigint REFERENCES course_versions(id) ON DELETE CASCADE,
  render_id     bigint REFERENCES video_renders(id) ON DELETE SET NULL,
  segment_id    text,
  type          text NOT NULL,                      -- scene | b_roll | image | icon | chart | presenter | audio
  source        text NOT NULL,                      -- hyperframes | heygen | human_upload | generated | library
  license       text NOT NULL DEFAULT 'internal',
  path          text,
  url           text,
  bytes         bigint,
  duration_seconds numeric,
  content_hash  text,                               -- cache key: identical input reuses the render
  status        text NOT NULL DEFAULT 'approved',
  meta          jsonb,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS video_assets_hash_idx   ON video_assets (content_hash);
CREATE INDEX IF NOT EXISTS video_assets_render_idx ON video_assets (render_id);

-- -------------------------------------------------------------- transcripts ---
-- Word-level transcripts are cached by audio hash: Scribe is billed per minute,
-- so the same audio is never transcribed twice.
CREATE TABLE IF NOT EXISTS video_transcripts (
  id           bigserial PRIMARY KEY,
  audio_hash   text NOT NULL UNIQUE,
  source_kind  text NOT NULL,                       -- narration | presenter
  provider     text NOT NULL DEFAULT 'elevenlabs_scribe',
  duration_seconds numeric,
  words        jsonb NOT NULL,                      -- [{ word, start, end, speaker }]
  text         text,
  billed_seconds numeric,
  created_at   timestamptz NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------ review actions ---
-- Style changes and regenerations are review decisions in their own right and
-- belong in the audit trail beside approvals.
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS action        text;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS video_template text;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS render_id      bigint REFERENCES video_renders(id) ON DELETE SET NULL;
