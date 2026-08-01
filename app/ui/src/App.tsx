/**
 * Layer 3 - the three-pane transcription workstation.
 *
 * Read-only so far: it places officers and cells from the API and lets a
 * reader move through them by keyboard. Values are held in memory; persistence
 * lands with the write side and authentication.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  fetchPage,
  fetchVocab,
  pageImageUrl,
  PageNotRegistrable,
  regionUrl,
  type RegisteredPage,
  type Vocab,
} from "./api";
import { Viewer } from "./components/Viewer";
import { EntryForm, FIELDS, type Values } from "./components/EntryForm";
import { Candidates } from "./components/Candidates";
import "./styles.css";

const DEFAULT_PID = "1449426"; // 昭和8年9月1日調
const DEFAULT_FRAME = 100;

export default function App() {
  const [pid, setPid] = useState(DEFAULT_PID);
  const [frame, setFrame] = useState(DEFAULT_FRAME);
  const [page, setPage] = useState<RegisteredPage | null>(null);
  const [vocab, setVocab] = useState<Vocab | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const [officerIndex, setOfficerIndex] = useState(0);
  const [activeField, setActiveField] = useState(FIELDS[0].key);
  const [entries, setEntries] = useState<Record<number, Values>>({});

  useEffect(() => {
    fetchVocab()
      .then(setVocab)
      .catch((e) => setError(String(e)));
  }, []);

  const load = useCallback(async (p: string, f: number) => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchPage(p, f);
      setPage(data);
      setOfficerIndex(0);
      setActiveField(FIELDS[0].key);
      setEntries({});
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
    load(DEFAULT_PID, DEFAULT_FRAME);
  }, [load]);

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

  // The viewer follows the cursor: the current cell if the field has one,
  // otherwise the whole officer strip (branch and rank live in the section
  // header, not in any cell).
  const focus = activeCell?.bbox ?? officer?.bbox ?? null;

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
            {page.bands_matched}/{page.bands_total} bands · skew {page.skew_deg}°
            {page.needs_review && (
              <span className="tag tag--suspect">needs review</span>
            )}
          </p>
        )}
      </header>

      {error && <div className="error">{error}</div>}

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
