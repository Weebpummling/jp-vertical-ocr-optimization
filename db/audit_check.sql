-- Functional check for the audit triggers. Run against a database that has
-- schema.sql applied; raises (non-zero psql exit with ON_ERROR_STOP) if any
-- guarantee does not hold. Everything is rolled back, so it is safe to run
-- against a live database: the rollback removes the probe rows and, because
-- the audit rows are written in the same transaction, their audit entries too.
BEGIN;

DO $$
DECLARE
    v_vol   uuid;
    v_page  uuid;
    n       int;
    v_actor uuid := gen_random_uuid();
BEGIN
    -- 1. insert / update / delete each produce exactly one audit row
    PERFORM set_config('app.user_id', v_actor::text, true);

    INSERT INTO source_volume (title) VALUES ('audit-check') RETURNING volume_id INTO v_vol;
    UPDATE source_volume SET title = 'audit-check-renamed' WHERE volume_id = v_vol;
    DELETE FROM source_volume WHERE volume_id = v_vol;

    SELECT count(*) INTO n FROM audit_log WHERE table_name = 'source_volume' AND row_id = v_vol;
    IF n <> 3 THEN
        RAISE EXCEPTION 'expected 3 audit rows for source_volume probe, found %', n;
    END IF;

    -- 2. the actor session setting is captured
    SELECT count(*) INTO n FROM audit_log WHERE row_id = v_vol AND actor = v_actor;
    IF n <> 3 THEN
        RAISE EXCEPTION 'actor not captured: expected 3 rows with actor, found %', n;
    END IF;

    -- 3. before/after images are populated on the right actions
    SELECT count(*) INTO n FROM audit_log
     WHERE row_id = v_vol
       AND ((action = 'insert' AND before_val IS NULL AND after_val IS NOT NULL)
         OR (action = 'update' AND before_val IS NOT NULL AND after_val IS NOT NULL)
         OR (action = 'delete' AND before_val IS NOT NULL AND after_val IS NULL));
    IF n <> 3 THEN
        RAISE EXCEPTION 'before/after images wrong on the source_volume probe';
    END IF;

    -- 4. a second audited table, exercising the per-table pk argument
    INSERT INTO source_volume (title) VALUES ('audit-check-2') RETURNING volume_id INTO v_vol;
    INSERT INTO source_page (volume_id, frame_no) VALUES (v_vol, 1) RETURNING page_id INTO v_page;
    SELECT count(*) INTO n FROM audit_log WHERE table_name = 'source_page' AND row_id = v_page;
    IF n <> 1 THEN
        RAISE EXCEPTION 'source_page insert not audited';
    END IF;

    -- 5. audit_log is append-only
    BEGIN
        UPDATE audit_log SET action = 'insert' WHERE row_id = v_page;
        RAISE EXCEPTION 'audit_log UPDATE was not rejected';
    EXCEPTION WHEN SQLSTATE 'AUD01' THEN
        NULL;  -- expected
    END;
    BEGIN
        DELETE FROM audit_log WHERE row_id = v_page;
        RAISE EXCEPTION 'audit_log DELETE was not rejected';
    EXCEPTION WHEN SQLSTATE 'AUD01' THEN
        NULL;  -- expected
    END;

    -- 6. TRUNCATE is refused on audited tables
    BEGIN
        TRUNCATE machine_reading;
        RAISE EXCEPTION 'TRUNCATE on an audited table was not rejected';
    EXCEPTION WHEN SQLSTATE 'AUD02' THEN
        NULL;  -- expected
    END;

    RAISE NOTICE 'audit_check: all guarantees hold';
END $$;

ROLLBACK;
