-- ===========================================================================
-- jp-vertical-ocr-optimization — relational core
-- Phase 0 draft, from design v2.1 §15. NOT YET FROZEN.
--
-- Invariants this schema is built to enforce:
--   * Observation.person_id stays NULL until linked, so unlinked records are
--     never silently dropped.
--   * No machine-authored final values: MachineReading is a separate table and
--     can never be the source of an Observation field.
--   * ReferenceTruth is walled off from production data and carries its own
--     train/hold-out flag.
--   * Unit and UnitDeployment are temporal, so officer-year theater assignment
--     is derivable.
-- ===========================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- --------------------------------------------------------------------------
-- Controlled vocabularies
-- --------------------------------------------------------------------------

CREATE TABLE rank_vocab (
    rank_code       text PRIMARY KEY,          -- e.g. 'shoi', 'chui', 'taii'
    label_ja        text NOT NULL,             -- 少尉 / 中尉 / 大尉
    label_en        text,
    seniority_order int  NOT NULL,             -- ascending; enables rank-consistency checks
    variants        text[] DEFAULT '{}',       -- kyūjitai / orthographic variants
    valid_from      date,
    valid_to        date
);

CREATE TABLE branch_vocab (
    branch_code text PRIMARY KEY,              -- e.g. 'hohei', 'kihei', 'hohei_ho'
    label_ja    text NOT NULL,                 -- 歩兵 / 騎兵 / 砲兵
    label_en    text,
    category    text CHECK (category IN ('combat','service')),  -- 兵科 vs 各部
    variants    text[] DEFAULT '{}',
    valid_from  date,
    valid_to    date
);

-- Kanji variant equivalence, so 齋/斎 is never scored as a disagreement.
CREATE TABLE kanji_variant (
    variant_char   char(1) PRIMARY KEY,
    canonical_char char(1) NOT NULL,
    note           text
);

-- --------------------------------------------------------------------------
-- Provenance: volumes, pages, cells
-- --------------------------------------------------------------------------

CREATE TABLE source_volume (
    volume_id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    title               text NOT NULL,
    series              text,                  -- 停年名簿 / 列次名簿 / Kanpō / manual
    edition_date        date,
    pid                 text,                  -- NDL persistent identifier
    holding_institution text,
    iiif_manifest_url   text,
    source_url          text,
    retrieved_at        timestamptz,
    coverage_notes      text
);

CREATE TABLE source_page (
    page_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    volume_id   uuid NOT NULL REFERENCES source_volume(volume_id),
    frame_no    int  NOT NULL,
    template_id uuid,                          -- FK added after layout_template
    alt_scans   jsonb DEFAULT '[]'::jsonb,     -- other institutional scans of same page
    UNIQUE (volume_id, frame_no)
);

CREATE TABLE layout_template (
    template_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name         text NOT NULL,                -- e.g. 'showa-teinen-meibo-A'
    series       text,
    era          text,                         -- meiji / taisho / showa
    -- Column grid defined ONCE per layout family. Field identity comes from
    -- geometry, never from guessing cell contents.
    column_spec  jsonb NOT NULL,               -- [{field, x0, x1, ...}, ...]
    row_spec     jsonb,
    notes        text,
    created_at   timestamptz DEFAULT now()
);

ALTER TABLE source_page
    ADD CONSTRAINT source_page_template_fk
    FOREIGN KEY (template_id) REFERENCES layout_template(template_id);

CREATE TABLE roster_cell (
    cell_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    page_id      uuid NOT NULL REFERENCES source_page(page_id),
    row_index    int  NOT NULL,                -- position on page
    seniority_no int,                          -- the monotone row anchor
    crop_bbox    int[] NOT NULL,               -- [x, y, w, h]
    crop_url     text,                         -- IIIF region URL — re-checkable
    audit_status text NOT NULL DEFAULT 'ok'
        CHECK (audit_status IN ('ok','sequence_break','extra_row','missing_row','damaged')),
    UNIQUE (page_id, row_index)
);

-- --------------------------------------------------------------------------
-- Units (temporal) and deployments
-- --------------------------------------------------------------------------

CREATE TABLE unit (
    unit_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_name text NOT NULL,
    echelon        text,                       -- division / brigade / regiment / battalion
    parent_unit_id uuid REFERENCES unit(unit_id),
    home_garrison  text,                       -- 衛戍地
    valid_from     date,
    valid_to       date
);

CREATE TABLE unit_deployment (
    deploy_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    unit_id        uuid NOT NULL REFERENCES unit(unit_id),
    interval_start date NOT NULL,
    interval_end   date,
    location       text,
    theater        text NOT NULL
        CHECK (theater IN ('home','korea','manchuria','china','taiwan','other')),
    source_refs    jsonb DEFAULT '[]'::jsonb,  -- citations are mandatory in practice
    confidence     text NOT NULL DEFAULT 'medium'
        CHECK (confidence IN ('high','medium','low')),
    CHECK (interval_end IS NULL OR interval_end >= interval_start)
);

-- --------------------------------------------------------------------------
-- People and observations
-- --------------------------------------------------------------------------

CREATE TABLE person (
    person_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_name    text NOT NULL,
    name_readings     text[] DEFAULT '{}',     -- furigana
    aliases           text[] DEFAULT '{}',     -- mid-career name changes
    birthplace        text,
    social_class      text,
    cohort_no         int,
    commissioning_date date,
    academy_dataset_id text                    -- link to the existing academy dataset
);

CREATE TABLE observation (
    obs_id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- NULL until linked. Unlinked observations are kept, never dropped.
    person_id        uuid REFERENCES person(person_id),
    page_id          uuid NOT NULL REFERENCES source_page(page_id),
    cell_id          uuid NOT NULL REFERENCES roster_cell(cell_id),
    name_raw         text,
    rank_code        text REFERENCES rank_vocab(rank_code),
    branch_code      text REFERENCES branch_vocab(branch_code),
    post             text,                     -- 職名
    unit_id          uuid REFERENCES unit(unit_id),
    seniority_no     int,
    commissioning_date date,                   -- 任官年月日
    as_of_date       date NOT NULL,            -- the volume's snapshot date
    field_confidence jsonb DEFAULT '{}'::jsonb,
    -- Provenance of the human decision. A machine may never populate this.
    author_user_id   uuid,
    status           text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft','confirmed','flagged','adjudicated')),
    propagated_from  uuid REFERENCES observation(obs_id),
    created_at       timestamptz DEFAULT now()
);

-- --------------------------------------------------------------------------
-- Kanpō events
-- --------------------------------------------------------------------------

CREATE TABLE kanpo_event (
    event_id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id             uuid REFERENCES person(person_id),
    event_type            text NOT NULL
        CHECK (event_type IN ('commission','promote','assign','reserve','death')),
    name_raw              text NOT NULL,
    old_rank_code         text REFERENCES rank_vocab(rank_code),
    new_rank_code         text REFERENCES rank_vocab(rank_code),
    branch_code           text REFERENCES branch_vocab(branch_code),
    unit_ref              text,
    event_date            date NOT NULL,
    gazette_ref           text NOT NULL,       -- issue / page / section
    extraction_confidence real,
    -- Every event is a PROPOSAL until validated against roster continuity.
    validation_status     text NOT NULL DEFAULT 'proposed'
        CHECK (validation_status IN ('proposed','validated','rank_inconsistent','rejected'))
);

-- --------------------------------------------------------------------------
-- Machine readings — second opinions only, never authoritative
-- --------------------------------------------------------------------------

CREATE TABLE machine_reading (
    reading_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cell_id      uuid NOT NULL REFERENCES roster_cell(cell_id),
    -- Three proposal sources per reading/README.md, named per the NDL family
    -- convention in docs/ndl-prior-work.md. 'ndl_fulltext' is kept distinct from
    -- the engines we run ourselves: it is NDL's precomputed FY2021 NDLOCR text,
    -- retrieved rather than produced, and is the zero-cost first engine.
    engine       text NOT NULL CHECK (engine IN (
                     'ndl_fulltext',    -- NDL precomputed text via fulltext-json
                     'ndlocr_lite',     -- NDLOCR-Lite, modern typeset, run by us
                     'ndlkoten_lite',   -- NDLkotenOCR-Lite, classical, run by us
                     'vlm'              -- VLM / OCR-free extractor
                 )),
    field        text NOT NULL,
    value        text,
    confidence   real,
    agree_status text CHECK (agree_status IN ('agree','disagree','variant_equal','no_human_value')),
    created_at   timestamptz DEFAULT now()
);

-- --------------------------------------------------------------------------
-- Ground truth — walled off, split fixed before first use
-- --------------------------------------------------------------------------

CREATE TABLE reference_truth (
    truth_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    scope            text NOT NULL,            -- 'year:1925' / 'page:<pid>:<frame>'
    verified_records jsonb NOT NULL,
    provenance       text NOT NULL,
    use_flag         text NOT NULL CHECK (use_flag IN ('train','holdout')),
    registered_at    timestamptz DEFAULT now()
);

-- --------------------------------------------------------------------------
-- Linkage, workflow, audit
-- --------------------------------------------------------------------------

CREATE TABLE linkage_decision (
    decision_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    obs_id      uuid REFERENCES observation(obs_id),
    event_id    uuid REFERENCES kanpo_event(event_id),
    person_id   uuid NOT NULL REFERENCES person(person_id),
    score       real,
    method      text NOT NULL CHECK (method IN ('propagation','splink_auto','adjudicated')),
    decider     uuid,
    rationale   text,
    decided_at  timestamptz DEFAULT now(),
    CHECK (num_nonnulls(obs_id, event_id) = 1)
);

CREATE TABLE app_user (
    user_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    login   text UNIQUE NOT NULL,
    display_name text,
    role    text NOT NULL CHECK (role IN ('annotator','reviewer','adjudicator','admin'))
);

CREATE TABLE task (
    task_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    task_type   text NOT NULL
        CHECK (task_type IN ('transcribe','review_flag','adjudicate_kanji',
                             'adjudicate_linkage','resolve_disappearance',
                             'validate_event','curate_deployment')),
    subject_id  uuid,
    assigned_to uuid REFERENCES app_user(user_id),
    status      text NOT NULL DEFAULT 'open'
        CHECK (status IN ('open','in_progress','done','wontfix')),
    created_at  timestamptz DEFAULT now()
);

CREATE TABLE audit_log (
    audit_id    bigserial PRIMARY KEY,
    table_name  text NOT NULL,
    row_id      uuid NOT NULL,
    action      text NOT NULL CHECK (action IN ('insert','update','delete')),
    before_val  jsonb,
    after_val   jsonb,
    actor       uuid,
    occurred_at timestamptz DEFAULT now()
);

-- --------------------------------------------------------------------------
-- Indexes
-- --------------------------------------------------------------------------

CREATE INDEX observation_person_idx    ON observation (person_id);
CREATE INDEX observation_asof_idx      ON observation (as_of_date);
CREATE INDEX observation_unlinked_idx  ON observation (obs_id) WHERE person_id IS NULL;
CREATE INDEX kanpo_event_person_idx    ON kanpo_event (person_id);
CREATE INDEX kanpo_event_date_idx      ON kanpo_event (event_date);
CREATE INDEX kanpo_event_pending_idx   ON kanpo_event (event_id) WHERE validation_status = 'proposed';
CREATE INDEX roster_cell_page_idx      ON roster_cell (page_id);
CREATE INDEX roster_cell_flagged_idx   ON roster_cell (cell_id) WHERE audit_status <> 'ok';
CREATE INDEX unit_deployment_unit_idx  ON unit_deployment (unit_id, interval_start);
CREATE INDEX audit_log_row_idx         ON audit_log (table_name, row_id);

-- --------------------------------------------------------------------------
-- Audit triggers — database-level, so no write path can bypass them
--
-- Every row written to a data table is recorded in audit_log by an AFTER
-- trigger, with the full before/after images. The actor is read from the
-- app.user_id session setting when the application has set one; direct psql
-- writes are still audited, just with a NULL actor.
--
-- The three vocab tables (text PKs) are not row-audited: they are loaded from
-- version-controlled CSVs by scripts/load_vocab.py, so their provenance is the
-- git history. audit_log.row_id stays uuid NOT NULL for everything audited.
--
-- Idempotent (CREATE OR REPLACE / DROP IF EXISTS) so the section can be
-- re-applied to a live database that predates it.
-- --------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION audit_row() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_row   uuid;
    v_actor uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_row := (to_jsonb(OLD) ->> TG_ARGV[0])::uuid;
    ELSE
        v_row := (to_jsonb(NEW) ->> TG_ARGV[0])::uuid;
    END IF;
    v_actor := NULLIF(current_setting('app.user_id', true), '')::uuid;
    INSERT INTO audit_log (table_name, row_id, action, before_val, after_val, actor)
    VALUES (
        TG_TABLE_NAME,
        v_row,
        lower(TG_OP),
        CASE WHEN TG_OP IN ('UPDATE','DELETE') THEN to_jsonb(OLD) END,
        CASE WHEN TG_OP IN ('INSERT','UPDATE') THEN to_jsonb(NEW) END,
        v_actor
    );
    RETURN NULL;
END $$;

-- audit_log itself is append-only: history that can be edited is not history.
CREATE OR REPLACE FUNCTION audit_log_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only' USING ERRCODE = 'AUD01';
END $$;

-- TRUNCATE fires no row triggers, so it would be an unaudited mass delete.
CREATE OR REPLACE FUNCTION forbid_truncate() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'TRUNCATE is forbidden on audited tables' USING ERRCODE = 'AUD02';
END $$;

DO $$
DECLARE
    t record;
BEGIN
    FOR t IN
        SELECT * FROM (VALUES
            ('person',           'person_id'),
            ('observation',      'obs_id'),
            ('roster_cell',      'cell_id'),
            ('source_page',      'page_id'),
            ('source_volume',    'volume_id'),
            ('layout_template',  'template_id'),
            ('unit',             'unit_id'),
            ('unit_deployment',  'deploy_id'),
            ('kanpo_event',      'event_id'),
            ('machine_reading',  'reading_id'),
            ('reference_truth',  'truth_id'),
            ('linkage_decision', 'decision_id'),
            ('task',             'task_id'),
            ('app_user',         'user_id')
        ) AS v(tbl, pk)
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I', t.tbl || '_audit', t.tbl);
        EXECUTE format(
            'CREATE TRIGGER %I AFTER INSERT OR UPDATE OR DELETE ON %I
                 FOR EACH ROW EXECUTE FUNCTION audit_row(%L)',
            t.tbl || '_audit', t.tbl, t.pk);
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I', t.tbl || '_no_truncate', t.tbl);
        EXECUTE format(
            'CREATE TRIGGER %I BEFORE TRUNCATE ON %I
                 FOR EACH STATEMENT EXECUTE FUNCTION forbid_truncate()',
            t.tbl || '_no_truncate', t.tbl);
    END LOOP;
END $$;

DROP TRIGGER IF EXISTS audit_log_append_only ON audit_log;
CREATE TRIGGER audit_log_append_only
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();

DROP TRIGGER IF EXISTS audit_log_no_truncate ON audit_log;
CREATE TRIGGER audit_log_no_truncate
    BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_truncate();
