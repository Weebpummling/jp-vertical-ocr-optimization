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
  fetchVolumeProgress,
  type PageObservation,
  type RegisteredPage,
  type VolumeProgress,
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

// Where this browser was last working. A volume runs to hundreds of frames, so
// reopening at a fixed frame meant every session began by remembering a number
// that only existed on the annotator's notepad.
const PLACE_KEY = "jpocr.place";

function lastPlace(): { pid: string; frame: number } {
  try {
    const raw = localStorage.getItem(PLACE_KEY);
    if (raw) {
      const p = JSON.parse(raw);
      if (typeof p?.pid === "string" && Number.isInteger(p?.frame)) return p;
    }
  } catch {
    // A corrupt or unreadable entry is not worth failing to start over.
  }
  return { pid: DEFAULT_PID, frame: DEFAULT_FRAME };
}

export default function App() {
  const [worker, setWorker] = useState<Worker | null>(null);
  const [identityChecked, setIdentityChecked] = useState(false);
  const [gateNotice, setGateNotice] = useState<string | null>(null);

  const [pid, setPid] = useState(() => lastPlace().pid);
  const [frame, setFrame] = useState(() => lastPlace().frame);
  const [page, setPage] = useState<RegisteredPage | null>(null);
  const [vocab, setVocab] = useState<Vocab | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dbWarning, setDbWarning] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const [officerIndex, setOfficerIndex] = useState(0);
  const [activeField, setActiveField] = useState(FIELDS[0].key);
  const [entries, setEntries] = useState<Record<number, Values>>({});
  const [saves, setSaves] = useState<Record<number, SaveState>>({});
  // What is already on record for this page, keyed by row. Kept apart from
  // `entries`, which is what *this* session typed: an officer someone else read
  // should show their reading without it being mistaken for the current worker's.
  const [recorded, setRecorded] = useState<Record<number, PageObservation>>({});
  // Which frames of this volume have been read at all — the "what is left?"
  // question, which the page-level counter cannot answer.
  const [progress, setProgress] = useState<VolumeProgress | null>(null);

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
      setRecorded({});
      savedSnapshot.current = {};
      // Only a page that actually loaded is worth returning to.
      try {
        localStorage.setItem(PLACE_KEY, JSON.stringify({ pid: p, frame: f }));
      } catch {
        // Private-mode or a full quota: not remembering where we were is a
        // smaller problem than refusing to open the page.
      }

      // What has already been read on this page, so a second worker does not
      // re-transcribe rows that are done. A 404 here means the volume is not
      // registered in the database - worth saying now rather than at the first
      // save.
      try {
        const { observations } = await fetchObservations(p, f);
        const existing: Record<number, SaveState> = {};
        const byRow: Record<number, PageObservation> = {};
        for (const obs of observations) {
          existing[obs.row_index] = { state: "saved", author: obs.author };
          byRow[obs.row_index] = obs;
        }
        setSaves(existing);
        setRecorded(byRow);
        // Volume coverage, refreshed per page load so it reflects other workers
        // too. Its own failure must not take the page down with it.
        fetchVolumeProgress(p)
          .then(setProgress)
          .catch(() => setProgress(null));
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
    // Open where this browser left off, not at a fixed frame — and read it here
    // rather than from `pid`/`frame`, so that editing those boxes never
    // re-triggers a load behind the reader's back.
    if (!worker) return;
    const place = lastPlace();
    load(place.pid, place.frame);
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

  // 兵科 and 階級 come from the section header, not the officer's own cell, so
  // they are the same for every officer under that heading — a 24-officer page
  // otherwise costs ~48 keystrokes' worth of values that never change. Carry the
  // nearest earlier reading forward as a starting point. It is a suggestion, not
  // a value: typing over it is an ordinary edit, an officer already recorded is
  // left exactly as recorded, and nothing is carried into what gets saved unless
  // it is on screen when the reader commits.
  const valuesFor = useCallback(
    (index: number): Values => {
      const typed = entries[index] ?? {};
      // An officer already recorded shows exactly what was recorded — including
      // when it was recorded by someone else in an earlier session, which used
      // to render as an empty form beside a "1 recorded" counter.
      if (saves[index]?.state === "saved") {
        const was = recorded[index];
        if (!was || entries[index]) return typed;
        const ja = (kind: "ranks" | "branches", code: string | null) =>
          (code && vocab?.[kind].find((v) => v.code === code)?.ja) || "";
        return {
          seniority_no: was.seniority_no == null ? "" : String(was.seniority_no),
          name_raw: was.name_raw ?? "",
          branch: ja("branches", was.branch_code),
          rank: ja("ranks", was.rank_code),
          post: was.post ?? "",
          // Stored normalized rather than as printed; showing it as-is would
          // invite someone to "correct" the page to match the database.
          commissioning_date: was.commissioning_date ?? "",
          notes: "",
        };
      }
      const carried: Values = {};
      for (let i = index - 1; i >= 0; i--) {
        const prev = entries[i];
        if (!prev) continue;
        if (!carried.branch && prev.branch) carried.branch = prev.branch;
        if (!carried.rank && prev.rank) carried.rank = prev.rank;
        if (carried.branch && carried.rank) break;
      }
      return { ...carried, ...typed };
    },
    [entries, saves, recorded, vocab],
  );

  const values = valuesFor(officerIndex);

  // Page-to-page movement, from the keyboard. A volume is hundreds of frames, so
  // the page boundary was the one place the reader had to stop and use the mouse.
  const goFrame = useCallback(
    (delta: number) => {
      const next = frame + delta;
      if (next < 1 || loading) return;
      setFrame(next);
      load(pid, next);
    },
    [frame, loading, load, pid],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.isComposing) return; // the IME owns the keyboard while converting
      if (!e.altKey || e.ctrlKey || e.metaKey) return;
      if (e.key === "PageDown") {
        e.preventDefault();
        goFrame(1);
      } else if (e.key === "PageUp") {
        e.preventDefault();
        goFrame(-1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [goFrame]);

  const signOut = useCallback((notice?: string) => {
    forgetIdCode();
    setWorker(null);
    setPage(null);
    setGateNotice(notice ?? null);
  }, []);

  const commit = useCallback(
    async (index: number) => {
      if (!page) return;
      // Blankness is judged on what the reader actually typed, never on what was
      // carried forward for them: otherwise stepping through officers nobody has
      // read yet would record each one on the strength of an inherited 兵科
      // alone. A suggestion is not a reading.
      if (isBlank(entries[index] ?? {})) return;
      // Recorded values are what was on screen, so a carried 兵科/階級 the reader
      // left standing rides along with the officer they did read.
      const values = valuesFor(index);
      const snapshot = JSON.stringify(values);
      if (savedSnapshot.current[index] === snapshot) return; // already recorded, unchanged
      // Materialize it, so stepping back to this officer shows what was saved
      // rather than re-deriving a suggestion.
      setEntries((prev) => ({ ...prev, [index]: values }));

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
    [page, entries, valuesFor, vocab, signOut],
  );

  // The viewer follows the cursor: the current cell if the field has one,
  // otherwise the whole officer strip (branch and rank live in the section
  // header, not in any cell).
  const focus = activeCell?.bbox ?? officer?.bbox ?? null;

  if (!identityChecked) return <div className="gate" />;
  if (!worker)
    return <IdentityGate onIdentified={setWorker} notice={gateNotice} />;

  const savedCount = Object.values(saves).filter((s) => s.state === "saved").length;

  // Where to go next: the first frame after this one that nobody has recorded
  // anything on. Walking the read set beats "current + 1", which is right only
  // until you have worked through a run of pages.
  const readFrames = new Set(progress?.frames.map((f) => f.frame_no) ?? []);
  let nextUnread = frame + 1;
  while (readFrames.has(nextUnread)) nextUnread++;

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
          <button
            type="button"
            onClick={() => goFrame(-1)}
            disabled={loading || frame <= 1}
            title="Previous page (Alt+PageUp)"
          >
            ‹ prev
          </button>
          <button
            type="button"
            onClick={() => goFrame(1)}
            disabled={loading}
            title="Next page (Alt+PageDown)"
          >
            next ›
          </button>
        </form>
        {/* While a page is in flight the previous page's numbers are still in
            state. Leaving them under a frame box that already shows the new
            number reads as "this page is done" — so say what is happening
            instead. An uncached frame is fetched from NDL, which is not instant. */}
        {loading && <p className="status">loading frame {frame}…</p>}
        {page && !loading && (
          <p className="status">
            <code>{page.template_id}</code> · {page.officer_count} officers ·{" "}
            {savedCount} recorded · {page.bands_matched}/{page.bands_total} bands ·
            skew {page.skew_deg}°
            {page.needs_review && (
              <span className="tag tag--suspect">needs review</span>
            )}
            {savedCount >= page.officer_count && page.officer_count > 0 && (
              <span className="tag tag--done">
                page complete — Alt+PageDown for the next
              </span>
            )}
          </p>
        )}
        {progress && !loading && (
          <p className="coverage">
            volume: <strong>{progress.frames_with_readings}</strong>{" "}
            {progress.frames_with_readings === 1 ? "page" : "pages"} read ·{" "}
            {progress.observations} readings
            {readFrames.has(frame) && (
              <span className="tag tag--done">this page has readings</span>
            )}
            {nextUnread !== frame + 1 && (
              <button
                type="button"
                className="linkish"
                onClick={() => {
                  setFrame(nextUnread);
                  load(pid, nextUnread);
                }}
              >
                next unread: {nextUnread}
              </button>
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
            values={values}
            onChange={setValue}
            activeField={activeField}
            onFocusField={setActiveField}
            onOfficer={moveOfficer}
            onCommit={() => commit(officerIndex)}
            saveState={saves[officerIndex]}
            isLastOfficer={officerIndex === page.officers.length - 1}
            recordedBy={entries[officerIndex] ? undefined : recorded[officerIndex]?.author}
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
