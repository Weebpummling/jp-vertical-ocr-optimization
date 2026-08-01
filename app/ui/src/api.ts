/**
 * Read-side client for the workstation API (app/api.py).
 *
 * Nothing here writes. Creating observations touches audited tables and needs
 * a human behind it, so those endpoints land with authentication.
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
