/**
 * The difficult-character toolkit.
 *
 * app/README.md's non-negotiable: *an unreadable character must never block a
 * record*. Two things stop a reader, and this handles both.
 *
 * **The character is on the page but the IME will not produce it.** Rosters are
 * printed in kyūjitai — 齋, 澤, 邊, 步, 戰 — and a modern IME offers the
 * shinjitai. So the reader types what they can (斎) and swaps it for what is
 * printed (齋) in one click, from the project's own variant table. The swap runs
 * both directions because which one is hard to type depends on the machine.
 *
 * **The character cannot be read at all** — damaged, sealed, or simply
 * illegible. Then it becomes 〓, the geta mark, which is what Japanese
 * typesetting has always used for "a character belongs here and could not be
 * set". The record saves with everything the reader *could* see, and carries the
 * count of unread characters and the crop they sit in, so it can be re-checked
 * from the image rather than re-transcribed from scratch.
 *
 * What is deliberately not here: radical / IDS lookup. It needs an external
 * character-decomposition dataset, and nothing has yet shown a reading that the
 * variant palette and the geta mark together cannot get past. It can be added
 * the first time one does.
 */
import type { Vocab } from "../api";
import { GETA, swapsFor } from "../observation";

interface Props {
  /** Current text of the focused field. */
  value: string;
  vocab: Vocab | null;
  onChange: (next: string) => void;
  /** Insert the geta mark where the caret is. */
  onGeta: () => void;
}

export function DifficultCharacter({ value, vocab, onChange, onGeta }: Props) {
  const swaps = swapsFor(value, vocab);
  const unread = value.split(GETA).length - 1;

  return (
    <div className="toolkit">
      <div className="toolkit__row">
        <button
          type="button"
          className="toolkit__geta"
          // Same reason as the swaps below: keep focus (and the caret) in the
          // field, so the mark lands where the reader was looking.
          onMouseDown={(e) => {
            e.preventDefault();
            onGeta();
          }}
          title="Insert 〓 for a character that cannot be read (Alt+G)"
        >
          {GETA} can’t read this one
        </button>
        {unread > 0 && (
          <span className="toolkit__count">
            {unread} unread — saved and flagged for a second look
          </span>
        )}
      </div>

      {swaps.length > 0 && (
        <div className="toolkit__row toolkit__swaps">
          <span className="toolkit__label">printed as</span>
          {swaps.map((swap) => (
            <button
              key={`${swap.from}-${swap.to}`}
              type="button"
              className="toolkit__swap"
              title={swap.note || `Replace ${swap.from} with ${swap.to}`}
              // onMouseDown, not onClick: the field's onBlur would otherwise
              // fire first and move the active field out from under the swap.
              onMouseDown={(e) => {
                e.preventDefault();
                onChange(value.split(swap.from).join(swap.to));
              }}
            >
              <span className="toolkit__from">{swap.from}</span>
              <span className="toolkit__arrow">→</span>
              <span className="toolkit__to">{swap.to}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
