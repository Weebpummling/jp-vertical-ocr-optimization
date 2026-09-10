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
  fetchProposals,
  fetchCellOcr,
  rereadCell,
  startCellOcr,
  setRowAudit,
  type PageObservation,
  type PageProposals,
  type CellOcrStatus,
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
import {
  EntryForm,
  FIELDS,
  type FieldSuggestion,
  type OfficerState,
} from "./components/EntryForm";
import { Candidates, wholesaleTakes } from "./components/Candidates";
import { PagePicker } from "./components/PagePicker";
import "./styles.css";

const DEFAULT_PID = "1449426"; // 昭和8年9月1日調
const DEFAULT_FRAME = 100;

// Where this browser was last working. A volume runs to hundreds of frames, so
// reopening at a fixed frame meant every session began by remembering a number
// that only existed on the annotator's notepad.
const PLACE_KEY = "jpocr.place";
// Whether this browser starts a zoom-read on every page it opens.
const AUTO_ZOOM_KEY = "jpocr.auto-zoom";

// A link from the reading worksheet (/?pid=1449426&frame=100&officer=11) opens
// that officer directly: the spreadsheet is where a reader spots something, and
// the workstation is where the image sits beside the form to settle it.
function urlPlace(): { pid: string; frame: number; officer: number | null } | null {
  try {
    const q = new URLSearchParams(window.location.search);
    const pid = q.get("pid");
    const frame = Number(q.get("frame"));
    if (!pid || !Number.isInteger(frame) || frame < 1) return null;
    const officer = Number(q.get("officer"));
    return {
      pid,
      frame,
      officer: Number.isInteger(officer) && officer > 0 ? officer - 1 : null,
    };
  } catch {
    return null;
  }
}

function startPlace(): { pid: string; frame: number } {
  const linked = urlPlace();
  return linked ? { pid: linked.pid, frame: linked.frame } : lastPlace();
}

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

  const [pid, setPid] = useState(() => startPlace().pid);
  const [frame, setFrame] = useState(() => startPlace().frame);
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
  // Machine proposals for the page on screen - NDL's OCR binned into the
  // template. Offered in the third pane, never pre-filled into the form.
  const [proposals, setProposals] = useState<PageProposals | null>(null);
  const [proposalsLoading, setProposalsLoading] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  // Zoomed re-reading - NDLOCR-Lite on each cell - for the page on screen.
  const [cellOcr, setCellOcr] = useState<CellOcrStatus | null>(null);
  const [ocrError, setOcrError] = useState<string | null>(null);
  const [rereading, setRereading] = useState<string | null>(null);
  // Machine readings the reader took, per officer and field, with what was taken.
  const [takenFrom, setTakenFrom] = useState<
    Record<number, Record<string, { source: string; fill: string }>>
  >({});
  // Bumped to hand the keyboard back to the form after a take from the pane.
  const [focusTick, setFocusTick] = useState(0);
  // Rows of this page with an audit status - "extra_row" is a column a reader
  // marked as holding no officer.
  const [rowAudit, setRowAuditState] = useState<Record<number, string>>({});
  const [autoZoom, setAutoZoom] = useState(() => {
    try {
      return localStorage.getItem(AUTO_ZOOM_KEY) === "1";
    } catch {
      return false;
    }
  });
  const autoZoomRef = useRef(autoZoom);
  autoZoomRef.current = autoZoom;
  // Pages load asynchronously; a slow answer for a page already left behind
  // must not land on the page now on screen.
  const loadToken = useRef(0);
  // An officer named by a worksheet link, applied once its page has loaded.
  const pendingOfficer = useRef<number | null>(urlPlace()?.officer ?? null);

  // What was on screen when each officer was last saved. Tabbing back through a
  // finished officer must not post a second draft; editing one deliberately
  // should.
  const savedSnapshot = useRef<Record<number, string>>({});
  // `roster_cell` rows are a per-page precondition for saving, and the endpoint
  // is idempotent, so it runs once per page rather than once per officer.
  const cellsEnsured = useRef<Set<string>>(new Set());
  // Lets page navigation record the officer in hand without `goFrame` having to
  // depend on `commit`, which would recreate the window key handler on every
  // keystroke.
  const commitRef = useRef<(() => Promise<void>) | null>(null);

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
    const token = ++loadToken.current;
    setLoading(true);
    setError(null);
    setDbWarning(null);
    setProposals(null);
    setCellOcr(null);
    setOcrError(null);
    setTakenFrom({});
    setRowAuditState({});
    try {
      const data = await fetchPage(p, f);
      if (token !== loadToken.current) return;
      setPage(data);
      // The first page of a volume reads its whole OCR document, so proposals
      // follow the page rather than hold it up.
      setProposalsLoading(true);
      fetchProposals(p, f)
        .then((got) => {
          if (token === loadToken.current) setProposals(got);
        })
        .catch((e) => {
          if (token === loadToken.current)
            setProposals({ pid: p, frame: f, available: false, reason: String(e), officers: [] });
        })
        .finally(() => {
          if (token === loadToken.current) setProposalsLoading(false);
        });
      // Re-readings already made for this page, and any job still running.
      fetchCellOcr(p, f)
        .then((got) => {
          if (token !== loadToken.current) return;
          setCellOcr(got);
          // Opted in: every page opened starts its own zoom-read. Cells already
          // read are skipped, so reopening a finished page costs a second or two.
          if (autoZoomRef.current && got.engine?.available && got.job?.state !== "running") {
            startCellOcr(p, f, 0)
              .then((started) => {
                if (token === loadToken.current) setCellOcr(started);
              })
              .catch(() => undefined);
          }
        })
        .catch(() => undefined);
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
        const { observations, row_audit } = await fetchObservations(p, f);
        if (token !== loadToken.current) return;
        const audit: Record<number, string> = {};
        for (const [row, status] of Object.entries(row_audit ?? {})) audit[Number(row)] = status;
        setRowAuditState(audit);
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

        // Resume where the page was left, rather than at an officer already
        // done. Half-finished pages are the normal case once more than one
        // person works a volume, and re-reading a finished officer to find the
        // edge of the work is pure waste.
        const nextOpen = data.officers.findIndex(
          (o) => !(o.index in existing) && audit[o.index] !== "extra_row",
        );
        if (nextOpen > 0) setOfficerIndex(nextOpen);
      } catch {
        setDbWarning(
          `${p} frame ${f} is not registered in the database, so nothing can be ` +
            `saved yet. Run: python ingestion/iiif_client.py register ${p}`,
        );
      }
      const linked = pendingOfficer.current;
      if (linked != null) {
        pendingOfficer.current = null;
        if (linked < data.officers.length) setOfficerIndex(linked);
        // Followed once: a reload resumes where the reader is, not at the link.
        window.history.replaceState(null, "", window.location.pathname);
      }
    } catch (e) {
      setPage(null);
      setError(
        e instanceof PageNotRegistrable
          ? `This page matches no template, so it has no officer grid. ${e.message}`
          : String(e),
      );
    } finally {
      if (token === loadToken.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Open where this browser left off, not at a fixed frame — and read it here
    // rather than from `pid`/`frame`, so that editing those boxes never
    // re-triggers a load behind the reader's back.
    if (!worker) return;
    const place = startPlace();
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

  const officerProposals = useMemo(
    () => proposals?.officers.find((o) => o.index === officer?.index),
    [proposals, officer],
  );

  // Taking a proposal is typing it: it becomes this session's entry for the
  // field, editable like anything typed and recorded with the officer.
  // Taking a reading is typing it - editable like anything typed - but where it
  // came from is kept, and recorded with the officer if it is still what is on
  // screen. The viewer moves to the field taken, so it is checked against the
  // page, and the keyboard goes back to the form.
  const take = (key: string, fill: string, source: string) => {
    setValue(key, fill);
    setTakenFrom((prev) => ({
      ...prev,
      [officerIndex]: { ...(prev[officerIndex] ?? {}), [key]: { source, fill } },
    }));
    setActiveField(key);
    setFocusTick((n) => n + 1);
  };

  // Every settled proposal into every empty field at once - readings the rules
  // accepted, and printed ditto marks, which the server resolves against the
  // human reading above. Never over something already on screen.
  const takeAll = useCallback(() => {
    const picks = wholesaleTakes(officerProposals, values);
    if (!picks.length) return;
    setEntries((prev) => {
      const next = { ...(prev[officerIndex] ?? {}) };
      for (const p of picks) next[p.form_key as string] = p.fill as string;
      return { ...prev, [officerIndex]: next };
    });
    setTakenFrom((prev) => {
      const next = { ...(prev[officerIndex] ?? {}) };
      for (const p of picks)
        next[p.form_key as string] = { source: "ndl", fill: p.fill as string };
      return { ...prev, [officerIndex]: next };
    });
  }, [officerProposals, values, officerIndex]);
  const takeAllRef = useRef(takeAll);
  takeAllRef.current = takeAll;

  // What each form field could take in place: NDL's reading, and the zoomed
  // re-reading where there is one.
  const suggestions = useMemo(() => {
    const out: Record<string, FieldSuggestion> = {};
    if (!officer) return out;
    for (const spec of FIELDS) {
      if (!spec.cell) continue;
      out[spec.key] = {
        ndl: officerProposals?.fields[spec.cell],
        reading: cellOcr?.results[`${officer.index}:${spec.cell}`],
      };
    }
    return out;
  }, [officer, officerProposals, cellOcr]);

  // The page at a glance, for the officer strip. "Differs" counts only fields the
  // form can take: counted over every field, the dot sat on 19 of 21 officers on
  // frame 101 - decorations, where the zoomed reading usually drops a character -
  // and a mark on nearly everything tells the reader nothing.
  const officerStates = useMemo<OfficerState[]>(
    () =>
      (page?.officers ?? []).map((o) => {
        const marked = rowAudit[o.index] === "extra_row";
        const kind = proposals?.officers.find((p) => p.index === o.index)?.column_kind;
        return {
          recorded: saves[o.index]?.state === "saved",
          failed: saves[o.index]?.state === "error",
          typed: !isBlank(entries[o.index] ?? {}) && saves[o.index]?.state !== "saved",
          differs: Object.values(cellOcr?.results ?? {}).some(
            (r) =>
              r.index === o.index && r.status === "alternative" && r.rerun.form_key != null,
          ),
          marked,
          suggested: !marked && kind && kind.kind !== "officer" ? kind : null,
        };
      }),
    [page, saves, entries, cellOcr, rowAudit, proposals],
  );

  // The page job reports by polling. Results land in the pane as each cell is
  // read, the officer in hand first.
  const ocrRunning = cellOcr?.job?.state === "running";
  useEffect(() => {
    if (!ocrRunning || !page) return;
    const token = loadToken.current;
    const { pid: p, frame: f } = page;
    const timer = window.setInterval(() => {
      fetchCellOcr(p, f)
        .then((got) => {
          if (token === loadToken.current) setCellOcr(got);
        })
        .catch(() => undefined);
    }, 1500);
    return () => window.clearInterval(timer);
  }, [ocrRunning, page]);

  const startPageOcr = useCallback(() => {
    if (!page) return;
    const token = loadToken.current;
    setOcrError(null);
    startCellOcr(page.pid, page.frame, officer?.index ?? 0)
      .then((got) => {
        if (token === loadToken.current) setCellOcr(got);
      })
      .catch((e) => {
        if (token === loadToken.current) setOcrError(String(e));
      });
  }, [page, officer]);

  const rereadField = useCallback(
    (field: string) => {
      if (!page || !officer) return;
      const token = loadToken.current;
      const key = `${officer.index}:${field}`;
      setRereading(key);
      setOcrError(null);
      rereadCell(page.pid, page.frame, officer.index, field)
        .then((reading) => {
          if (token !== loadToken.current) return;
          setCellOcr((prev) => ({
            pid: page.pid,
            frame: page.frame,
            engine: prev?.engine ?? null,
            job: prev?.job ?? null,
            results: { ...(prev?.results ?? {}), [key]: reading },
          }));
        })
        .catch((e) => {
          if (token === loadToken.current) setOcrError(String(e));
        })
        .finally(() => {
          if (token === loadToken.current) setRereading(null);
        });
    },
    [page, officer],
  );
  const ocrKeysRef = useRef({ page: startPageOcr, cell: () => {} });
  const rowKeysRef = useRef<() => void>(() => {});
  ocrKeysRef.current = {
    page: startPageOcr,
    cell: () => {
      if (activeCell) rereadField(activeCell.field);
    },
  };

  // Typing that has not been recorded yet. Moving between officers records them,
  // but closing the tab is the same loss by a different route — and this state
  // lives only in memory.
  const unsaved = useMemo(
    () =>
      Object.keys(entries).filter(
        (k) =>
          !isBlank(entries[Number(k)] ?? {}) &&
          savedSnapshot.current[Number(k)] !== JSON.stringify(entries[Number(k)]) &&
          saves[Number(k)]?.state !== "saved",
      ).length,
    [entries, saves],
  );

  useEffect(() => {
    if (!unsaved) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [unsaved]);

  // Page-to-page movement, from the keyboard. A volume is hundreds of frames, so
  // the page boundary was the one place the reader had to stop and use the mouse.
  const goFrame = useCallback(
    async (delta: number) => {
      const next = frame + delta;
      if (next < 1 || loading) return;
      // Leaving a page records the officer in hand, exactly as leaving an
      // officer does: `load` clears the typed values, so anything not committed
      // first would be discarded without a word.
      await commitRef.current?.();
      setFrame(next);
      load(pid, next);
    },
    [frame, loading, load, pid],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.isComposing) return; // the IME owns the keyboard while converting
      if (e.key === "Escape") setPickerOpen(false);
      if (!e.altKey || e.ctrlKey || e.metaKey) return;
      if (e.key === "PageDown") {
        e.preventDefault();
        goFrame(1);
      } else if (e.key === "PageUp") {
        e.preventDefault();
        goFrame(-1);
      } else if (e.key === "a" || e.key === "A") {
        e.preventDefault();
        takeAllRef.current();
      } else if (e.key === "p" || e.key === "P") {
        e.preventDefault();
        setPickerOpen((open) => !open);
      } else if (e.key === "o" || e.key === "O") {
        e.preventDefault();
        ocrKeysRef.current.page();
      } else if (e.key === "r" || e.key === "R") {
        e.preventDefault();
        ocrKeysRef.current.cell();
      } else if (e.key === "x" || e.key === "X") {
        e.preventDefault();
        rowKeysRef.current();
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
      const pageKey = `${page.pid}:${page.frame}`;
      try {
        if (!cellsEnsured.current.has(pageKey)) {
          await createCells(page.pid, page.frame);
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
          buildObservation(
            index,
            values,
            vocab,
            cropUrls,
            Object.fromEntries(
              Object.entries(takenFrom[index] ?? {})
                .filter(([key, took]) => values[key] === took.fill)
                .map(([key, took]) => [key, took.source]),
            ),
          ),
        );
        savedSnapshot.current[index] = snapshot;
        setSaves((s) => ({
          ...s,
          [index]: { state: "saved", flagged: saved.flagged,
                     inherited: saved.inherited },
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
    [page, entries, valuesFor, vocab, signOut, takenFrom],
  );

  // Kept current so page navigation can flush the officer in hand.
  commitRef.current = () => commit(officerIndex);

  // Jumping to an officer records the one in hand first, as every other way of
  // leaving an officer does.
  const jumpTo = (index: number) => {
    if (index === officerIndex) return;
    void commit(officerIndex);
    setOfficerIndex(index);
  };

  // A column of the grid that holds no officer - a section label, the column
  // legend, an unused slot - marked by the reader, so the page can be finished.
  const markRow = async (index: number, notOfficer: boolean) => {
    if (!page) return;
    try {
      const saved = await setRowAudit(page.pid, page.frame, index, notOfficer ? "extra_row" : "ok");
      cellsEnsured.current.add(`${page.pid}:${page.frame}`);
      setRowAuditState((prev) => {
        const next = { ...prev };
        if (saved.audit_status === "ok") delete next[index];
        else next[index] = saved.audit_status;
        return next;
      });
      // Marking the officer in hand moves on to the next one still to read.
      if (notOfficer && index === officerIndex && saved.audit_status === "extra_row") {
        const after = page.officers.findIndex(
          (o) =>
            o.index > index &&
            saves[o.index]?.state !== "saved" &&
            rowAudit[o.index] !== "extra_row",
        );
        if (after >= 0) setOfficerIndex(after);
      }
    } catch (e) {
      if (e instanceof NotIdentified) {
        signOut("Your id code stopped being recognized. Enter it again.");
        return;
      }
      setError(`Could not mark officer ${index + 1}: ${(e as Error).message ?? String(e)}`);
    }
  };
  const suggestedNotOfficers = officerStates
    .map((state, i) => (state.suggested && !state.recorded ? i : -1))
    .filter((i) => i >= 0);
  const markSuggested = async () => {
    for (const i of suggestedNotOfficers) await markRow(i, true);
  };
  rowKeysRef.current = () => {
    if (officer) void markRow(officerIndex, rowAudit[officerIndex] !== "extra_row");
  };

  const changeAutoZoom = (on: boolean) => {
    setAutoZoom(on);
    try {
      localStorage.setItem(AUTO_ZOOM_KEY, on ? "1" : "0");
    } catch {
      // Not remembered across sessions; it still applies to this one.
    }
  };

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

  const openFrame = async (target: number) => {
    await commitRef.current?.();
    setFrame(target);
    load(page?.pid ?? pid, target);
  };
  const markedCount = Object.values(rowAudit).filter((status) => status === "extra_row").length;
  const liveOfficers = (page?.officer_count ?? 0) - markedCount;
  const pageComplete =
    Boolean(page) &&
    liveOfficers > 0 &&
    savedCount >= liveOfficers &&
    (page?.panels_missing.length ?? 0) === 0;

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
          <button
            type="button"
            onClick={() => setPickerOpen((open) => !open)}
            aria-expanded={pickerOpen}
            title="Every page of every volume, and how finished each is (Alt+P)"
          >
            pages
          </button>
        </form>
        {/* While a page is in flight the previous page's numbers are still in
            state. Leaving them under a frame box that already shows the new
            number reads as "this page is done" — so say what is happening
            instead. An uncached frame is fetched from NDL, which is not instant. */}
        {loading && <p className="status">loading frame {frame}…</p>}
        {page && !loading && (
          <p className="status">
            <code>{page.template_id}</code> · {liveOfficers} officers
            {markedCount > 0 && ` (${markedCount} column${markedCount === 1 ? "" : "s"} marked not an officer)`}
            {page.panels_total > 1 &&
              ` across ${page.panels_registered.length} of ${page.panels_total} leaves`}{" "}
            · {savedCount} recorded · {page.bands_matched}/{page.bands_total} bands ·
            skew {page.skew_deg}°
            {page.needs_review && (
              <span className="tag tag--suspect">needs review</span>
            )}
            {suggestedNotOfficers.length > 0 && (
              <button
                type="button"
                className="tag tag--provisional tag--action"
                onClick={markSuggested}
                title="Columns read as a section label, the column legend or an unused slot"
              >
                mark {suggestedNotOfficers.length} column
                {suggestedNotOfficers.length === 1 ? "" : "s"} not an officer
              </button>
            )}
            {/* A leaf that matched no template carries officers nobody can
                reach from here. Saying so is the whole point: a scan whose
                left-hand page failed looks identical to a scan that only ever
                had one page, and the counter below would call it finished. */}
            {page.panels_missing.length > 0 && (
              <span className="tag tag--suspect">
                {page.panels_missing.length === 1
                  ? `the ${page.panels_missing[0] === 0 ? "right" : "left"}-hand leaf did not register — its officers are NOT on this page`
                  : `${page.panels_missing.length} leaves did not register — their officers are NOT on this page`}
              </span>
            )}
            {savedCount >= liveOfficers &&
              liveOfficers > 0 &&
              (page.panels_missing.length === 0 ? (
                <button
                  type="button"
                  className="tag tag--done tag--action"
                  onClick={() => openFrame(nextUnread)}
                  title="Record anything in hand and open the next page nobody has read"
                >
                  page complete — next unread page {nextUnread} ›
                </button>
              ) : (
                <span className="tag tag--suspect">
                  every officer this page can show is recorded — but a leaf is
                  missing, so the page is not done
                </span>
              ))}
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
            suggestions={suggestions}
            onTake={take}
            officerStates={officerStates}
            onJump={jumpTo}
            focusTick={focusTick}
            pageComplete={pageComplete}
            nextPageLabel={pageComplete ? `next unread page ${nextUnread}` : null}
            onNextPage={() => openFrame(nextUnread)}
            marked={rowAudit[officerIndex] === "extra_row"}
            columnKind={officerProposals?.column_kind ?? null}
            onMark={(notOfficer) => markRow(officerIndex, notOfficer)}
          />
          <Candidates
            field={activeField}
            cell={activeCell}
            localCropUrl={
              activeCell ? regionUrl(page.pid, page.frame, activeCell.bbox) : null
            }
            officerCropUrl={regionUrl(page.pid, page.frame, officer.bbox)}
            proposals={officerProposals}
            unavailable={
              proposals && !proposals.available ? (proposals.reason ?? "unavailable") : null
            }
            loading={proposalsLoading}
            values={values}
            onTake={take}
            onTakeAll={takeAll}
            officerIndex={officer.index}
            readings={cellOcr?.results ?? {}}
            ocrJob={cellOcr?.job ?? null}
            engine={cellOcr?.engine ?? null}
            ocrError={ocrError}
            rereading={rereading}
            onStartPageOcr={startPageOcr}
            onReread={rereadField}
            autoZoom={autoZoom}
            onAutoZoom={changeAutoZoom}
          />
        </main>
      )}

      {pickerOpen && (
        <PagePicker
          pid={page?.pid ?? pid}
          frame={page?.frame ?? frame}
          onClose={() => setPickerOpen(false)}
          onOpen={async (p, f) => {
            setPickerOpen(false);
            await commitRef.current?.();
            setPid(p);
            setFrame(f);
            load(p, f);
          }}
        />
      )}
    </div>
  );
}
