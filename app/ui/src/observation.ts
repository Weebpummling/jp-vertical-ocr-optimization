/**
 * Turn what the reader typed into what the API stores.
 *
 * The rule that shapes this file: **a value the machine cannot resolve is
 * flagged, never forced.** A branch that is not in the controlled vocabulary
 * does not get normalized to the nearest entry, and a seniority number that is
 * not a number does not get silently dropped — both travel to the server in
 * `field_confidence` with the raw reading and the reason, so the panel never
 * shows a clean value that nobody actually read.
 *
 * The date is the exception that proves it: it goes up exactly as printed,
 * because `reading/eradate.py` is the one place allowed to decide what
 * 明四三、一二、二六 means, and it refuses rather than guesses too.
 */
import {
  resolveVocab,
  type ObservationIn,
  type Vocab,
  type VocabEntry,
} from "./api";

export type Values = Record<string, string>;

export interface Refusal {
  raw: string;
  refused: string;
}

/** Where one officer's record stands with the server. */
export interface SaveState {
  state: "saving" | "saved" | "error";
  message?: string;
  /** Fields the server would not take as read — surfaced, never swallowed. */
  flagged?: Record<string, { raw?: string; refused?: string }>;
  /** Set when the row was already on the page before this session. */
  author?: string;
}

const trimmed = (values: Values, key: string): string =>
  (values[key] ?? "").trim();

/** True when nothing has been typed for this officer — nothing to save. */
export const isBlank = (values: Values): boolean =>
  Object.values(values ?? {}).every((v) => !v || !v.trim());

export function buildObservation(
  rowIndex: number,
  values: Values,
  vocab: Vocab | null,
): ObservationIn {
  const confidence: Record<string, Refusal> = {};

  const vocabCode = (key: string, entries: VocabEntry[] | undefined) => {
    const typed = trimmed(values, key);
    if (!typed) return null;
    const resolved = resolveVocab(entries ?? [], typed);
    if (resolved) return resolved.code;
    confidence[key] = {
      raw: typed,
      refused: "not in the controlled vocabulary",
    };
    return null;
  };

  const seniorityTyped = trimmed(values, "seniority_no");
  let seniority: number | null = null;
  if (seniorityTyped) {
    // Half-width, full-width (１２３) and kanji-digit readings all appear on the
    // page; only the first two are unambiguous enough to accept here.
    const normalized = seniorityTyped.replace(/[０-９]/g, (d) =>
      String.fromCharCode(d.charCodeAt(0) - 0xfee0),
    );
    if (/^\d+$/.test(normalized)) {
      seniority = Number(normalized);
    } else {
      confidence.seniority_no = {
        raw: seniorityTyped,
        refused: "not a plain number",
      };
    }
  }

  return {
    row_index: rowIndex,
    name_raw: trimmed(values, "name_raw") || null,
    rank_code: vocabCode("rank", vocab?.ranks),
    branch_code: vocabCode("branch", vocab?.branches),
    post: trimmed(values, "post") || null,
    seniority_no: seniority,
    commissioning_date: trimmed(values, "commissioning_date") || null,
    notes: trimmed(values, "notes") || null,
    field_confidence: confidence,
  };
}
