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

/**
 * The geta mark, 〓 — centuries of Japanese typesetting practice for "a
 * character belongs here and could not be set". Using it rather than a guess or
 * a blank is the point: the reader records what they could see, marks what they
 * could not, and the record says so out loud.
 */
export const GETA = "〓";

export interface Refusal {
  raw: string;
  refused: string;
}

/** A field the reader could not fully read: saved, but flagged for a second look. */
export interface Unreadable {
  raw: string;
  unreadable: number;
  crop_url?: string | null;
}

export interface Swap {
  from: string;
  to: string;
  note?: string;
}

/**
 * Kyūjitai↔shinjitai swaps for the characters actually typed, both directions.
 *
 * Rosters are printed in kyūjitai — 齋, 澤, 邊, 步, 戰 — and a modern IME offers
 * the shinjitai, so the reader types what they can and swaps to what is printed.
 * Both directions, because which form is hard to type depends on the machine.
 *
 * Offering all 28 pairs at all times would be a wall of chips to read past on
 * every field; offering the ones present in what was just typed is a short list
 * that can be acted on.
 */
export function swapsFor(value: string, vocab: Vocab | null): Swap[] {
  const table = vocab?.kanji_variants ?? [];
  const seen = new Set<string>();
  const out: Swap[] = [];
  for (const char of value) {
    for (const entry of table) {
      const pair =
        char === entry.canonical
          ? { from: char, to: entry.variant, note: entry.note }
          : char === entry.variant
            ? { from: char, to: entry.canonical, note: entry.note }
            : null;
      if (!pair) continue;
      const key = `${pair.from}->${pair.to}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(pair);
    }
  }
  return out;
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
  /** field key → IIIF URL of the crop it was read from, for re-checking. */
  cropUrls: Record<string, string | null> = {},
): ObservationIn {
  const confidence: Record<string, Refusal | Unreadable> = {};

  // A value containing 〓 is saved as read. What travels with it is where to
  // look: the count of unread characters and the crop they are in.
  for (const [key, value] of Object.entries(values ?? {})) {
    const marks = (value ?? "").split(GETA).length - 1;
    if (marks > 0) {
      confidence[key] = {
        raw: value.trim(),
        unreadable: marks,
        crop_url: cropUrls[key] ?? null,
      };
    }
  }

  // A value already marked unreadable keeps that reason. "not in the controlled
  // vocabulary" is true of 步〓 but tells a reviewer nothing they can act on,
  // whereas "one character could not be read, here is the crop" does.
  const alreadyExplained = (key: string) => key in confidence;

  const vocabCode = (key: string, entries: VocabEntry[] | undefined) => {
    const typed = trimmed(values, key);
    if (!typed) return null;
    const resolved = resolveVocab(entries ?? [], typed);
    if (resolved) return resolved.code;
    if (!alreadyExplained(key)) {
      confidence[key] = {
        raw: typed,
        refused: "not in the controlled vocabulary",
      };
    }
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
    } else if (!alreadyExplained("seniority_no")) {
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
