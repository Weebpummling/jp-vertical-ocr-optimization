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
import type { Cell, Vocab, VocabEntry } from "../api";
import { resolveVocab, suggestVocab } from "../api";

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
  { key: "commissioning_date", label: "任官年月日", cell: "commissioning_date" },
  { key: "notes", label: "備考", cell: null },
];

export type Values = Record<string, string>;

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
}: Props) {
  const inputs = useRef<Record<string, HTMLInputElement | null>>({});
  const composing = useRef(false);
  const [openList, setOpenList] = useState<string | null>(null);

  useEffect(() => {
    inputs.current[activeField]?.focus();
  }, [activeField, officerIndex]);

  const cellFor = (spec: FieldSpec) =>
    spec.cell ? cells.find((c) => c.field === spec.cell) : undefined;

  const move = (delta: number) => {
    const i = FIELDS.findIndex((f) => f.key === activeField);
    const next = i + delta;
    if (next < 0) return;
    if (next >= FIELDS.length) {
      onOfficer(1); // rolled off the end: next officer, back to the top field
      onFocusField(FIELDS[0].key);
      return;
    }
    onFocusField(FIELDS[next].key);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>, spec: FieldSpec) => {
    // The IME owns these keys while it is converting. Never pre-empt it.
    if (composing.current || e.nativeEvent.isComposing) return;

    if (e.altKey && (e.key === "ArrowDown" || e.key === "ArrowRight")) {
      e.preventDefault();
      onOfficer(1);
      return;
    }
    if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowLeft")) {
      e.preventDefault();
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

  const vocabEntries = (spec: FieldSpec): VocabEntry[] =>
    spec.vocab ? (vocab?.[spec.vocab] ?? []) : [];

  return (
    <section className="pane pane--form">
      <header className="pane__head">
        <h2>
          Officer {officerIndex + 1}
          <span className="muted"> / {officerCount}</span>
        </h2>
        <p className="keys">
          <kbd>Enter</kbd> next field · <kbd>Alt</kbd>+<kbd>↓</kbd>/<kbd>↑</kbd> next/prev officer
        </p>
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
        <p className="muted">
          Nothing is saved yet — the write side lands with authentication, since
          no code path may author a value without a human behind it.
        </p>
      </footer>
    </section>
  );
}
