/**
 * Client for the workstation API (app/api.py).
 *
 * Writes carry the worker's id code in `X-Annotator`. The code is their
 * identifier on the project (docs/decision-workstation-auth.md) — typed once,
 * remembered by the browser, and never rendered back to the screen: what the UI
 * shows is the display name the server resolves it to.
 */

export type Bbox = [number, number, number, number]; // x, y, w, h in scan pixels

export interface Cell {
  field: string;
  bbox: Bbox;
  /** An edge of this cell was inferred, not seen. Demand human attention. */
  suspect: boolean;
  /** False when the field's *label* is still a reading decision. */
  confirmed_label: boolean;
  crop_url: string | null;
}

export interface Officer {
  index: number; // 0 = rightmost strip, i.e. first in reading order
  bbox: Bbox;
  crop_url: string | null;
  cells: Cell[];
}

export interface RegisteredPage {
  pid: string;
  frame: number;
  panel: number;
  template_id: string;
  skew_deg: number;
  bands_matched: number;
  bands_total: number;
  explained_frac: number;
  needs_review: boolean;
  officer_count: number;
  officers: Officer[];
  iiif_service: string | null;
}

export interface VocabEntry {
  code: string;
  ja: string;
  en: string;
  order?: number | null;
  category?: string | null;
  variants: string[];
}

export interface Vocab {
  ranks: VocabEntry[];
  branches: VocabEntry[];
  kanji_variants: { variant: string; canonical: string; note?: string }[];
}

export class PageNotRegistrable extends Error {}
/** The id code was missing or is not recognized. */
export class NotIdentified extends Error {}

const BASE = "/api";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (res.status === 422) {
    const body = await res.json().catch(() => ({ detail: "unregistrable" }));
    throw new PageNotRegistrable(body.detail);
  }
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

// --------------------------------------------------------------------------
// identity
// --------------------------------------------------------------------------

const CODE_KEY = "jpocr.id-code";

export const storedIdCode = () => localStorage.getItem(CODE_KEY) ?? "";
export const rememberIdCode = (code: string) =>
  localStorage.setItem(CODE_KEY, code.trim());
export const forgetIdCode = () => localStorage.removeItem(CODE_KEY);

export interface Worker {
  user_id: string;
  display_name: string;
}

/**
 * Every identified request goes through here.
 *
 * A 401 is surfaced as its own error type rather than a generic failure: it is
 * the one error the worker can actually fix, by entering the right code.
 */
async function send<T>(
  path: string,
  init: { method?: string; body?: unknown; code?: string } = {},
): Promise<T> {
  const code = init.code ?? storedIdCode();
  if (!code) throw new NotIdentified("no id code entered");
  const res = await fetch(`${BASE}${path}`, {
    method: init.method ?? "GET",
    headers: {
      "X-Annotator": code,
      ...(init.body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  });
  if (res.status === 401) {
    const body = await res.json().catch(() => ({ detail: "unrecognized id code" }));
    throw new NotIdentified(body.detail);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

/** Resolve an id code to the worker it belongs to; the identity gate's check. */
export const whoami = (code?: string) => send<Worker>("/whoami", { code });

export const fetchVocab = () => get<Vocab>("/vocab");

/**
 * Pixels come from our cache, never from the institution.
 *
 * An annotator stepping through cells would otherwise fire a request at NDL per
 * crop and a tile storm per page — which is exactly what returned HTTP 429
 * during development. `crop_url` on a cell still points at the public IIIF
 * copy; that is provenance, not the display path.
 */
export const pageImageUrl = (pid: string, frame: number) =>
  `${BASE}/volumes/${encodeURIComponent(pid)}/pages/${frame}/image`;

export const regionUrl = (pid: string, frame: number, [x, y, w, h]: Bbox) =>
  `${BASE}/volumes/${encodeURIComponent(pid)}/pages/${frame}/region` +
  `?x=${x}&y=${y}&w=${w}&h=${h}`;

export const fetchPage = (pid: string, frame: number, panel = 0) =>
  get<RegisteredPage>(
    `/volumes/${encodeURIComponent(pid)}/pages/${frame}?panel=${panel}&crop_urls=true`,
  );

// --------------------------------------------------------------------------
// write side
// --------------------------------------------------------------------------

export interface ObservationIn {
  row_index: number;
  name_raw?: string | null;
  rank_code?: string | null;
  branch_code?: string | null;
  post?: string | null;
  seniority_no?: number | null;
  /** As printed (明四三、一二、二六). The server normalizes, or refuses. */
  commissioning_date?: string | null;
  field_confidence?: Record<string, unknown>;
  notes?: string | null;
}

export interface SavedObservation {
  obs_id: string;
  status: string;
  as_of_date: string;
  commissioning_date: string | null;
  /** Fields the server would not accept as read — shown, never hidden. */
  flagged: Record<string, { raw?: string; refused?: string }>;
}

export interface PageObservation {
  obs_id: string;
  row_index: number;
  name_raw: string | null;
  seniority_no: number | null;
  /** Vocabulary codes, not the printed forms — resolve through `Vocab` to display. */
  rank_code: string | null;
  branch_code: string | null;
  post: string | null;
  /** Already normalized by the server (1923-08-01), not as printed. */
  commissioning_date: string | null;
  status: string;
  created_at: string;
  /** Display name of whoever read it. */
  author: string;
}

/**
 * Materialize the page's officer geometry as `roster_cell` rows.
 *
 * Idempotent, and a precondition for saving: an observation hangs off a cell,
 * so the first save on a page does this once.
 */
export const createCells = (pid: string, frame: number, panel = 0) =>
  send<{ page_id: string; cells: unknown[] }>(
    `/volumes/${encodeURIComponent(pid)}/pages/${frame}/cells?panel=${panel}`,
    { method: "POST" },
  );

export const saveObservation = (pid: string, frame: number, body: ObservationIn) =>
  send<SavedObservation>(
    `/volumes/${encodeURIComponent(pid)}/pages/${frame}/observations`,
    { method: "POST", body },
  );

export const fetchObservations = (pid: string, frame: number) =>
  get<{ page_id: string; observations: PageObservation[] }>(
    `/volumes/${encodeURIComponent(pid)}/pages/${frame}/observations`,
  );

/** One frame of a volume that has been read. Unread frames are not returned. */
export interface FrameProgress {
  frame_no: number;
  /** Readings, which are append-only — a re-read row counts twice. */
  observations: number;
  /** Distinct officer rows touched on that frame. */
  rows_read: number;
  last_touched: string;
}

export interface VolumeProgress {
  pid: string;
  frames_with_readings: number;
  observations: number;
  frames: FrameProgress[];
}

export const fetchVolumeProgress = (pid: string) =>
  get<VolumeProgress>(`/volumes/${encodeURIComponent(pid)}/progress`);

/**
 * Resolve a printed form to its controlled-vocabulary entry.
 *
 * Matches the canonical label first, then any recorded variant, so an
 * annotator can type what is actually on the page (步兵) and still land on the
 * canonical code (hohei). Deliberately not a fuzzy match: a near-miss should
 * fail and be flagged, not be silently normalized to the closest thing.
 */
export function resolveVocab(
  entries: VocabEntry[],
  typed: string,
): VocabEntry | null {
  const q = typed.trim();
  if (!q) return null;
  return (
    entries.find((e) => e.ja === q || e.code === q) ??
    entries.find((e) => e.variants.includes(q)) ??
    null
  );
}

/** Entries whose label, code or variants start with what has been typed. */
export function suggestVocab(
  entries: VocabEntry[],
  typed: string,
  limit = 8,
): VocabEntry[] {
  const q = typed.trim().toLowerCase();
  if (!q) return entries.slice(0, limit);
  return entries
    .filter(
      (e) =>
        e.ja.startsWith(q) ||
        e.code.toLowerCase().startsWith(q) ||
        e.en.toLowerCase().startsWith(q) ||
        e.variants.some((v) => v.startsWith(q)),
    )
    .slice(0, limit);
}
