/**
 * Layer 3 - the three-pane transcription workstation.
 *
 * A worker identifies themselves with their id code, reads officers off the
 * page, and each committed officer becomes a draft `observation` recorded to
 * them. Nothing is confirmed here: confirmation is a separate, deliberate act,
 * and the machine's job is to place the cell, not to decide what it says.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  createCells,
  fetchObservations,
  fetchPage,
  forgetIdCode,
  NotIdentified,
  pageImageUrl,
  PageNotRegistrable,
  regionUrl,
  saveObservation,
  storedIdCode,
  whoami,
  type RegisteredPage,
  type Vocab,
  type Worker,
} from "./api";
import { fetchVocab } from "./api";
import {
  buildObservation,
  isBlank,
  type SaveState,
  type Values,
} from "./observation";
import { IdentityGate } from "./components/IdentityGate";
import { Viewer } from "./components/Viewer";
import { EntryForm, FIELDS } from "./components/EntryForm";
import { Candidates } from "./components/Candidates";
import "./styles.css";

const DEFAULT_PID = "1449426"; // 昭和8年9月1日調
const DEFAULT_FRAME = 100;

export default function App() {
  const [worker, setWorker] = useState<Worker | null>(null);
  const [identityChecked, setIdentityChecked] = useState(false);
  const [gateNotice, setGateNotice] = useState<string | null>(null);

  const [pid, setPid] = useState(DEFAULT_PID);
  const [frame, setFrame] = useState(DEFAULT_FRAME);
  const [page, setPage] = useState<RegisteredPage | null>(null);
  const [vocab, setVocab] = useState<Vocab | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dbWarning, setDbWarning] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const [officerIndex, setOfficerIndex] = useState(0);
  const [activeField, setActiveField] = useState(FIELDS[0].key);
  const [entries, setEntries] = useState<Record<number, Values>>({});
  const [saves, setSaves] = useState<Record<number, SaveState>>({});

  // What was on screen when each officer was last saved. Tabbing back through a
  // finished officer must not post a second draft; editing one deliberately
  // should.
  const savedSnapshot = useRef<Record<number, string>>({});
  // `roster_cell` rows are a per-page precondition for saving, and the endpoint
  // is idempotent, so it runs once per page rather than once per officer.
  const cellsEnsured = useRef<Set<string>>(new Set());

  // A stored code is checked before the workstation opens: a code that has been
  // rotated should fail here, not after an hour of transcription.
  useEffect(() => {
    if (!storedIdCode()) {
      setIdentityChecked(true);
      return;
    }
    whoami()
      .then(setWorker)
      .catch((e) => {
        forgetIdCode();
        if (e instanceof NotIdentified) {
          setGateNotice("The code stored in this browser is no longer recognized.");
        } else {
          setGateNotice(`Could not reach the workstation API: ${e}`);
        }
      })
      .finally(() => setIdentityChecked(true));
  }, []);

  useEffect(() => {
    if (!worker) return;
    fetchVocab()
      .then(setVocab)
      .catch((e) => setError(String(e)));
  }, [worker]);

  const load = useCallback(async (p: string, f: number) => {
    setLoading(true);
    setError(null);
    setDbWarning(null);
    try {
      const data = await fetchPage(p, f);
      setPage(data);
      setOfficerIndex(0);
      setActiveField(FIELDS[0].key);
      setEntries({});
      setSaves({});
      savedSnapshot.current = {};

      // What has already been read on this page, so a second worker does not
      // re-transcribe rows that are done. A 404 here means the volume is not
      // registered in the database - worth saying now rather than at the first
      // save.
      try {
        const { observations } = await fetchObservations(p, f);
        const existing: Record<number, SaveState> = {};
        for (const obs of observations) {
          existing[obs.row_index] = { state: "saved", author: obs.author };
        }
        setSaves(existing);
      } catch {
        setDbWarning(
          `${p} frame ${f} is not registered in the database, so nothing can be ` +
            `saved yet. Run: python ingestion/iiif_client.py register ${p}`,
        );
      }
    } catch (e) {
      setPage(null);
      setError(
        e instanceof PageNotRegistrable
          ? `This page matches no template, so it has no officer grid. ${e.message}`
          : String(e),
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (worker) load(DEFAULT_PID, DEFAULT_FRAME);
  }, [worker, load]);

  const officer = page?.officers[officerIndex];
  const activeCell = useMemo(
    () => officer?.cells.find((c) => c.field === activeField),
    [officer, activeField],
  );

  const moveOfficer = (delta: number) => {
    if (!page) return;
    setOfficerIndex((i) =>
      Math.min(Math.max(i + delta, 0), page.officers.length - 1),
    );
  };

  const setValue = (key: string, value: string) =>
    setEntries((prev) => ({
      ...prev,
      [officerIndex]: { ...(prev[officerIndex] ?? {}), [key]: value },
    }));

  const signOut = useCallback((notice?: string) => {
    forgetIdCode();
    setWorker(null);
    setPage(null);
    setGateNotice(notice ?? null);
  }, []);

  const commit = useCallback(
    async (index: number) => {
      if (!page) return;
      const values = entries[index];
      if (!values || isBlank(values)) return; // nothing typed: nothing to record
      const snapshot = JSON.stringify(values);
      if (savedSnapshot.current[index] === snapshot) return; // already recorded, unchanged

      setSaves((s) => ({ ...s, [index]: { state: "saving" } }));
      const pageKey = `${page.pid}:${page.frame}:${page.panel}`;
      try {
        if (!cellsEnsured.current.has(pageKey)) {
          await createCells(page.pid, page.frame, page.panel);
          cellsEnsured.current.add(pageKey);
        }
        // Where each field was read from, so a character marked unreadable can
        // be re-checked against the image instead of re-transcribed. Fields with
        // no cell of their own (branch, rank) fall back to the officer strip.
        const officerCells = page.officers[index]?.cells ?? [];
        const cropUrls: Record<string, string | null> = {};
        for (const spec of FIELDS) {
          const cell = spec.cell
            ? officerCells.find((c) => c.field === spec.cell)
            : undefined;
          cropUrls[spec.key] = cell?.crop_url ?? page.officers[index]?.crop_url ?? null;
        }

        const saved = await saveObservation(
          page.pid,
          page.frame,
          buildObservation(index, values, vocab, cropUrls),
        );
        savedSnapshot.current[index] = snapshot;
        setSaves((s) => ({
          ...s,
          [index]: { state: "saved", flagged: saved.flagged },
        }));
      } catch (e) {
        if (e instanceof NotIdentified) {
          signOut("Your id code stopped being recognized. Enter it again.");
          return;
        }
        setSaves((s) => ({
          ...s,
          [index]: { state: "error", message: (e as Error).message ?? String(e) },
        }));
      }
    },
    [page, entries, vocab, signOut],
  );

  // The viewer follows the cursor: the current cell if the field has one,
  // otherwise the whole officer strip (branch and rank live in the section
  // header, not in any cell).
  const focus = activeCell?.bbox ?? officer?.bbox ?? null;

  if (!identityChecked) return <div className="gate" />;
  if (!worker)
    return <IdentityGate onIdentified={setWorker} notice={gateNotice} />;

  const savedCount = Object.values(saves).filter((s) => s.state === "saved").length;

  return (
    <div className="app">
      <header className="topbar">
        <h1>停年名簿 transcription</h1>
        <form
          className="loader"
          onSubmit={(e) => {
            e.preventDefault();
            load(pid, frame);
          }}
        >
          <label>
            pid
            <input value={pid} onChange={(e) => setPid(e.target.value)} size={9} />
          </label>
          <label>
            frame
            <input
              type="number"
              value={frame}
              onChange={(e) => setFrame(Number(e.target.value))}
              size={5}
            />
          </label>
          <button type="submit" disabled={loading}>
            {loading ? "loading…" : "load"}
          </button>
        </form>
        {page && (
          <p className="status">
            <code>{page.template_id}</code> · {page.officer_count} officers ·{" "}
            {savedCount} recorded · {page.bands_matched}/{page.bands_total} bands ·
            skew {page.skew_deg}°
            {page.needs_review && (
              <span className="tag tag--suspect">needs review</span>
            )}
          </p>
        )}
        <p className="whoami">
          recording as <strong>{worker.display_name}</strong>
          <button type="button" className="linkish" onClick={() => signOut()}>
            not you?
          </button>
        </p>
      </header>

      {error && <div className="error">{error}</div>}
      {dbWarning && <div className="warning">{dbWarning}</div>}

      {page && officer && (
        <main className="panes">
          <Viewer imageUrl={pageImageUrl(page.pid, page.frame)} focus={focus} />
          <EntryForm
            officerIndex={officerIndex}
            officerCount={page.officers.length}
            cells={officer.cells}
            vocab={vocab}
            values={entries[officerIndex] ?? {}}
            onChange={setValue}
            activeField={activeField}
            onFocusField={setActiveField}
            onOfficer={moveOfficer}
            onCommit={() => commit(officerIndex)}
            saveState={saves[officerIndex]}
          />
          <Candidates
            field={activeField}
            cell={activeCell}
            localCropUrl={
              activeCell ? regionUrl(page.pid, page.frame, activeCell.bbox) : null
            }
            officerCropUrl={regionUrl(page.pid, page.frame, officer.bbox)}
          />
        </main>
      )}
    </div>
  );
}
