/**
 * Pane 2 - structured entry for one officer.
 *
 * Two requirements from app/README.md drive the whole design:
 *
 * **Keyboard-first.** A whole officer is enterable without the mouse: Enter
 * advances a field and rolls onto the next officer at the end; Alt+Arrow jumps
 * officers from anywhere.
 *
 * **IME-aware.** While an IME is composing, Enter and Escape belong to the
 * IME - they select a candidate or cancel conversion. Acting on them would
 * advance the field mid-word and is the classic way a Japanese entry form
 * becomes unusable. Every handler checks `isComposing` first, and we track
 * composition ourselves as well because some IMEs fire keydown after
 * compositionend with isComposing already false.
 */
import { useEffect, useRef, useState } from "react";
import type { Cell, CellReading, FieldProposal, Vocab, VocabEntry } from "../api";
import { resolveVocab, suggestVocab } from "../api";
import { DITTO, GETA, type SaveState, type Values } from "../observation";
import { DifficultCharacter } from "./DifficultCharacter";

export interface FieldSpec {
  key: string;
  label: string;
  /** Template field this binds to, or null when it is not on the page as a cell. */
  cell: string | null;
  vocab?: "ranks" | "branches";
  hint?: string;
}

export const FIELDS: FieldSpec[] = [
  { key: "seniority_no", label: "序列番号", cell: "seniority_no" },
  { key: "name_raw", label: "氏名", cell: "name_raw", hint: "name and birth date share the cell" },
  {
    key: "branch",
    label: "兵科",
    cell: null,
    vocab: "branches",
    hint: "from the section header, not this officer's cell",
  },
  {
    key: "rank",
    label: "階級",
    cell: null,
    vocab: "ranks",
    hint: "from the section header, not this officer's cell",
  },
  { key: "post", label: "職名", cell: "post" },
  {
    key: "commissioning_date",
    label: "任官年月日",
    cell: "commissioning_date",
    hint: "Taishō pages: the line tagged 少尉 in the 任官ノ年月日 cell (machine readings, right)",
  },
  { key: "notes", label: "備考", cell: null },
];

const KIND_TEXT: Record<string, string> = {
  section_label: "a section label",
  legend: "the column legend",
  blank: "an unused slot",
};

export type { Values };

/** What a field could take in place: NDL's reading, and the zoomed re-reading. */
export interface FieldSuggestion {
  ndl?: FieldProposal;
  reading?: CellReading;
}

/** One officer on the page, for the strip. */
export interface OfficerState {
  recorded: boolean;
  typed: boolean;
  failed: boolean;
  /** The two machine readings disagree somewhere on this officer. */
  differs: boolean;
  /** A reader marked this column as holding no officer. */
  marked: boolean;
  /** The machine reads this column as holding no officer. */
  suggested: { kind: string; evidence?: string } | null;
}

interface Props {
  officerIndex: number;
  officerCount: number;
  cells: Cell[];
  vocab: Vocab | null;
  values: Values;
  onChange: (key: string, value: string) => void;
  activeField: string;
  onFocusField: (key: string) => void;
  onOfficer: (delta: number) => void;
  /** Record this officer as a draft. Safe to call twice: unchanged is a no-op. */
  onCommit: () => void;
  saveState?: SaveState;
  /** True on the last officer of the page, so the reader is told the page is done. */
  isLastOfficer?: boolean;
  /** Set when what is on screen is a reading already on record, not this session's typing. */
  recordedBy?: string;
  suggestions: Record<string, FieldSuggestion>;
  /** Take a machine reading into a field; `source` is "ndl" or "ndlocr-lite". */
  onTake: (key: string, fill: string, source: string) => void;
  officerStates: OfficerState[];
  /** Record the officer in hand, then open officer `index`. */
  onJump: (index: number) => void;
  /** Changes whenever focus should return to the active field. */
  focusTick: number;
  pageComplete: boolean;
  nextPageLabel: string | null;
  onNextPage: () => void;
  /** This column is marked as holding no officer. */
  marked: boolean;
  columnKind: { kind: string; evidence?: string } | null;
  onMark: (notOfficer: boolean) => void;
}

export function EntryForm({
  officerIndex,
  officerCount,
  cells,
  vocab,
  values,
  onChange,
  activeField,
  onFocusField,
  onOfficer,
  onCommit,
  saveState,
  isLastOfficer,
  recordedBy,
  suggestions,
  onTake,
  officerStates,
  onJump,
  focusTick,
  pageComplete,
  nextPageLabel,
  onNextPage,
  marked,
  columnKind,
  onMark,
}: Props) {
  const inputs = useRef<Record<string, HTMLInputElement | null>>({});
  const composing = useRef(false);
  const [openList, setOpenList] = useState<string | null>(null);

  const pendingCaret = useRef<{ key: string; pos: number } | null>(null);

  useEffect(() => {
    inputs.current[activeField]?.focus();
  }, [activeField, officerIndex, focusTick]);

  // Restore the caret after a toolkit insert, once the new value is on screen.
  useEffect(() => {
    const pending = pendingCaret.current;
    if (!pending) return;
    pendingCaret.current = null;
    const input = inputs.current[pending.key];
    input?.focus();
    input?.setSelectionRange(pending.pos, pending.pos);
  });

  const cellFor = (spec: FieldSpec) =>
    spec.cell ? cells.find((c) => c.field === spec.cell) : undefined;

  /**
   * Put the geta mark where the caret is, not at the end.
   *
   * A reader hits the unreadable character partway through a name — 平岩〓一 —
   * so appending would put the mark in the wrong place and quietly misrecord
   * which character was lost.
   */
  const insertGeta = (key: string) => {
    const input = inputs.current[key];
    const current = values[key] ?? "";
    const start = input?.selectionStart ?? current.length;
    const end = input?.selectionEnd ?? start;
    onChange(key, current.slice(0, start) + GETA + current.slice(end));
    // Applied in an effect, not here and not in requestAnimationFrame: the
    // value on screen is React's, so the caret can only be placed after the
    // re-render has committed. rAF raced it and left the caret at the end.
    pendingCaret.current = { key, pos: start + GETA.length };
  };

  const move = (delta: number) => {
    const i = FIELDS.findIndex((f) => f.key === activeField);
    const next = i + delta;
    if (next < 0) return;
    if (next >= FIELDS.length) {
      // Rolled off the end: this officer is finished, so record them before
      // moving on. Keyboard-first means the common path never needs the mouse -
      // and never needs the reader to remember to save.
      onCommit();
      onOfficer(1);
      onFocusField(FIELDS[0].key);
      return;
    }
    onFocusField(FIELDS[next].key);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>, spec: FieldSpec) => {
    // The IME owns these keys while it is converting. Never pre-empt it.
    if (composing.current || e.nativeEvent.isComposing) return;

    if (e.altKey && (e.key === "d" || e.key === "D")) {
      e.preventDefault();      // this cell is 同 - same as the entry above
      onChange(spec.key, DITTO);
      return;
    }
    if (e.altKey && (e.key === "g" || e.key === "G")) {
      e.preventDefault();      // a character that cannot be read
      insertGeta(spec.key);
      return;
    }
    // Taking a reading from the keyboard. Alt+Enter is the check-and-move-on key:
    // the settled reading for this field (NDL's, or the zoomed one where only it
    // is settled), then the next field - so a correct officer is a run of
    // Alt+Enter. Alt+Shift is avoided: on Windows it switches input language.
    if (e.altKey && e.key === "Enter") {
      e.preventDefault();
      const sug = suggestions[spec.key];
      if (sug?.ndl?.wholesale && sug.ndl.fill != null) {
        onTake(spec.key, sug.ndl.fill, "ndl");
      } else if (
        sug?.reading?.status === "alternative" &&
        sug.reading.rerun.wholesale &&
        sug.reading.rerun.fill != null
      ) {
        onTake(spec.key, sug.reading.rerun.fill, "ndlocr-lite");
      }
      move(1);
      return;
    }
    if (e.altKey && (e.key === "1" || e.key === "2")) {
      const sug = suggestions[spec.key];
      const pick =
        e.key === "1"
          ? sug?.ndl
          : sug?.reading?.status === "alternative"
            ? sug.reading.rerun
            : undefined;
      if (pick?.fill != null) {
        e.preventDefault();
        onTake(spec.key, pick.fill, e.key === "1" ? "ndl" : "ndlocr-lite");
      }
      return;
    }
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();      // record without leaving the field
      onCommit();
      return;
    }
    // Leaving an officer records them: an unsaved officer left behind by a
    // keystroke is transcription work quietly thrown away.
    if (e.altKey && (e.key === "ArrowDown" || e.key === "ArrowRight")) {
      e.preventDefault();
      onCommit();
      onOfficer(1);
      return;
    }
    if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowLeft")) {
      e.preventDefault();
      onCommit();
      onOfficer(-1);
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      if (spec.vocab && openList === spec.key) {
        const entries = vocab?.[spec.vocab] ?? [];
        const best = suggestVocab(entries, values[spec.key] ?? "")[0];
        if (best) {
          onChange(spec.key, best.ja);
          setOpenList(null);
          return;
        }
      }
      move(1);
      return;
    }
    if (e.key === "Escape") {
      setOpenList(null);
    }
  };

  // The machine readings for a field, where the eye already is. A click takes one
  // without taking the keyboard away from the form.
  const chips = (spec: FieldSpec) => {
    const sug = suggestions[spec.key];
    if (!sug) return null;
    const typed = values[spec.key] ?? "";
    const ndlFill = sug.ndl?.fill ?? null;
    const alt = sug.reading?.status === "alternative" ? sug.reading.rerun : null;
    if (ndlFill == null && alt?.fill == null) return null;
    return (
      <div className="chips-inline">
        {ndlFill != null && (
          <button
            type="button"
            className={
              "sug sug--ndl" +
              (sug.ndl?.wholesale ? "" : " sug--unsettled") +
              (typed === ndlFill ? " sug--taken" : "")
            }
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => onTake(spec.key, ndlFill, "ndl")}
            title={
              sug.ndl?.wholesale
                ? "NDL's reading - click or Alt+1 to take it"
                : `NDL's reading, not accepted: ${sug.ndl?.note ?? ""} (Alt+1)`
            }
          >
            <span className="sug__src">NDL</span>
            {ndlFill}
            {sug.reading?.status === "agrees" && (
              <span
                className="sug__agree"
                title={
                  sug.reading.variant_only
                    ? "NDLOCR-Lite reads the same, in the modern form"
                    : "NDLOCR-Lite, zoomed in, reads the same"
                }
              >
                ✓
              </span>
            )}
          </button>
        )}
        {alt?.fill != null && (
          <button
            type="button"
            className={"sug sug--alt" + (typed === alt.fill ? " sug--taken" : "")}
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => onTake(spec.key, alt.fill as string, "ndlocr-lite")}
            title="NDLOCR-Lite's zoomed reading, which differs - click or Alt+2 to take it"
          >
            <span className="sug__src">zoom</span>
            {alt.fill}
          </button>
        )}
      </div>
    );
  };

  const vocabEntries = (spec: FieldSpec): VocabEntry[] =>
    spec.vocab ? (vocab?.[spec.vocab] ?? []) : [];

  return (
    <section className="pane pane--form">
      <header className="pane__head">
        <h2>
          Officer {officerIndex + 1}
          <span className="muted"> / {officerCount}</span>
        </h2>
        {officerStates.length > 1 && (
          <ol className="strip" aria-label="Officers on this page">
            {officerStates.map((state, i) => (
              <li key={i}>
                <button
                  type="button"
                  className={[
                    "strip__o",
                    i === officerIndex ? "strip__o--here" : "",
                    state.recorded ? "strip__o--done" : "",
                    state.typed ? "strip__o--typed" : "",
                    state.failed ? "strip__o--failed" : "",
                    state.marked ? "strip__o--marked" : "",
                    state.suggested ? "strip__o--suggested" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => onJump(i)}
                  aria-current={i === officerIndex ? "true" : undefined}
                  title={
                    `Officer ${i + 1}` +
                    (state.recorded ? " · recorded" : state.typed ? " · typed, not recorded" : "") +
                    (state.failed ? " · last save failed" : "") +
                    (state.marked
                      ? " · marked not an officer"
                      : state.suggested
                        ? ` · looks like ${KIND_TEXT[state.suggested.kind] ?? state.suggested.kind}`
                        : "") +
                    (state.differs ? " · the two machine readings differ" : "")
                  }
                >
                  {i + 1}
                  {state.differs && <span className="strip__dot" aria-hidden="true" />}
                </button>
              </li>
            ))}
          </ol>
        )}
        {marked ? (
          <p className="notofficer">
            <span>
              Marked <strong>not an officer</strong> — it no longer counts toward this page.
            </span>
            <button type="button" className="linkish" onClick={() => onMark(false)}>
              undo
            </button>
          </p>
        ) : columnKind && columnKind.kind !== "officer" ? (
          <p className="notofficer">
            <span>
              This column looks like {KIND_TEXT[columnKind.kind] ?? columnKind.kind}
              {columnKind.evidence ? ` (${columnKind.evidence})` : ""}.
            </span>
            <button type="button" onClick={() => onMark(true)}>
              not an officer <kbd>Alt</kbd>+<kbd>X</kbd>
            </button>
          </p>
        ) : null}
        <p className="keys">
          <kbd>Alt</kbd>+<kbd>Enter</kbd> take reading &amp; next ·{" "}
          <kbd>Alt</kbd>+<kbd>1</kbd>/<kbd>2</kbd> take NDL / zoom · <kbd>Enter</kbd> next
          field · <kbd>Alt</kbd>+<kbd>↓</kbd>/<kbd>↑</kbd> officer ·{" "}
          <kbd>Alt</kbd>+<kbd>PgDn</kbd>/<kbd>PgUp</kbd> page · <kbd>Alt</kbd>+<kbd>G</kbd>{" "}
          can’t read a character
        </p>
        {recordedBy && (
          <p className="already">
            Already recorded by <strong>{recordedBy}</strong> — this is their
            reading. Editing it records a new one rather than replacing theirs.
          </p>
        )}
        {isLastOfficer && (
          <p className="already">
            Last officer on this page. <kbd>Alt</kbd>+<kbd>PgDn</kbd> for the next
            page.
          </p>
        )}
      </header>

      <div className="fields">
        {FIELDS.map((spec) => {
          const cell = cellFor(spec);
          const entries = vocabEntries(spec);
          const typed = values[spec.key] ?? "";
          const resolved = spec.vocab ? resolveVocab(entries, typed) : null;
          const unresolved = Boolean(spec.vocab && typed && !resolved);
          return (
            <div
              className={
                "field" +
                (activeField === spec.key ? " field--active" : "") +
                (cell?.suspect ? " field--suspect" : "")
              }
              key={spec.key}
            >
              <label htmlFor={`f-${spec.key}`}>
                {spec.label}
                {cell && !cell.confirmed_label && (
                  <span className="tag tag--provisional" title="This field's label is a provisional reading">
                    provisional label
                  </span>
                )}
                {cell?.suspect && (
                  <span className="tag tag--suspect" title="An edge of this cell was inferred, not seen">
                    check crop
                  </span>
                )}
                {!spec.cell && <span className="tag tag--nocell">no cell</span>}
              </label>

              <input
                id={`f-${spec.key}`}
                ref={(el) => {
                  inputs.current[spec.key] = el;
                }}
                value={typed}
                autoComplete="off"
                spellCheck={false}
                className={unresolved ? "input input--unresolved" : "input"}
                onFocus={() => {
                  onFocusField(spec.key);
                  if (spec.vocab) setOpenList(spec.key);
                }}
                onBlur={() => setOpenList((k) => (k === spec.key ? null : k))}
                onCompositionStart={() => {
                  composing.current = true;
                }}
                onCompositionEnd={() => {
                  composing.current = false;
                }}
                onChange={(e) => onChange(spec.key, e.target.value)}
                onKeyDown={(e) => onKeyDown(e, spec)}
              />

              {chips(spec)}

              {activeField === spec.key && (
                <DifficultCharacter
                  value={typed}
                  vocab={vocab}
                  onChange={(next) => onChange(spec.key, next)}
                  onGeta={() => insertGeta(spec.key)}
                  onDitto={() => onChange(spec.key, DITTO)}
                />
              )}

              {spec.hint && <p className="hint">{spec.hint}</p>}
              {resolved && (
                <p className="resolved">
                  → <code>{resolved.code}</code> {resolved.en}
                </p>
              )}
              {unresolved && (
                <p className="unresolved">
                  not in the controlled vocabulary — flag rather than force
                </p>
              )}

              {spec.vocab && openList === spec.key && (
                <ul className="options">
                  {suggestVocab(entries, typed).map((entry) => (
                    <li key={entry.code}>
                      <button
                        type="button"
                        onMouseDown={(e) => {
                          e.preventDefault();
                          onChange(spec.key, entry.ja);
                          setOpenList(null);
                        }}
                      >
                        <span className="opt-ja">{entry.ja}</span>
                        <span className="opt-en">{entry.en}</span>
                        {entry.variants.length > 0 && (
                          <span className="opt-var">{entry.variants.join(" ")}</span>
                        )}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </div>

      <footer className="pane__foot">
        <div className="save">
          <button
            type="button"
            className="save__btn"
            onClick={onCommit}
            disabled={saveState?.state === "saving"}
          >
            {saveState?.state === "saving" ? "recording…" : "record officer"}
          </button>
          <span className="keys">
            <kbd>Ctrl</kbd>+<kbd>Enter</kbd>, or <kbd>Enter</kbd> off the last field
          </span>
        </div>

        {pageComplete && nextPageLabel && (
          <button type="button" className="save__next" onClick={onNextPage}>
            page complete — {nextPageLabel} ›
          </button>
        )}
        {saveState?.state === "saved" && (
          <p className="save__ok">
            recorded as a draft
            {saveState.author && ` by ${saveState.author}`} — confirmation is a
            separate act
          </p>
        )}
        {saveState?.inherited && Object.keys(saveState.inherited).length > 0 && (
          <div className="save__inherited">
            <p>Taken from the officer above — check that is the right row:</p>
            <ul>
              {Object.entries(saveState.inherited).map(([column, from]) => (
                <li key={column}>
                  <code>{column}</code> <b>{from.value}</b>{" "}
                  <span className="muted">from officer {from.from_row + 1}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {saveState?.state === "error" && (
          <p className="save__err">not recorded: {saveState.message}</p>
        )}
        {saveState?.flagged && Object.keys(saveState.flagged).length > 0 && (
          <div className="save__flags">
            <p>Saved without these — the server would not read them for you:</p>
            <ul>
              {Object.entries(saveState.flagged).map(([field, why]) => (
                <li key={field}>
                  {/* The label the reader typed into, not the storage key: being
                      told "commissioning_date" was refused means translating it
                      back to 任官年月日 before you can look at the right box. */}
                  <strong>{FIELDS.find((f) => f.key === field)?.label ?? field}</strong>{" "}
                  {why.raw && <b>{why.raw}</b>} — {why.refused}
                </li>
              ))}
            </ul>
          </div>
        )}
      </footer>
    </section>
  );
}
