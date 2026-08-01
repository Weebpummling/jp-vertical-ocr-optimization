/**
 * Pane 3 - the crop under the cursor, and machine proposals against it.
 *
 * The proposal list is empty by design: Layer 4 (NDL OCR / our own engine /
 * VLM) is not built. The pane exists now because the *styling contract* has to
 * exist before proposals do - a suggestion must never look like a confirmed
 * value. That visual independence is the entire statistical basis for treating
 * machine agreement as corroboration, so it is not a detail to bolt on later.
 */
import type { Cell } from "../api";

interface Props {
  field: string;
  cell: Cell | undefined;
  /** Local crop for the current cell; the institution's copy is provenance only. */
  localCropUrl: string | null;
  officerCropUrl: string | null;
}

export function Candidates({ field, cell, localCropUrl, officerCropUrl }: Props) {
  return (
    <section className="pane pane--candidates">
      <header className="pane__head">
        <h2>{field}</h2>
      </header>

      <div className="crop">
        {localCropUrl ? (
          <img src={localCropUrl} alt={`crop of ${field}`} />
        ) : officerCropUrl ? (
          <img src={officerCropUrl} alt="officer strip" />
        ) : (
          <p className="muted">No crop for this field.</p>
        )}
      </div>

      {cell && (
        <dl className="meta">
          <dt>bbox</dt>
          <dd>{cell.bbox.join(", ")}</dd>
          <dt>label</dt>
          <dd>{cell.confirmed_label ? "confirmed" : "provisional"}</dd>
          <dt>geometry</dt>
          <dd>{cell.suspect ? "edge inferred — verify" : "rulings observed"}</dd>
          {cell.crop_url && (
            <>
              <dt>provenance</dt>
              <dd>
                <a href={cell.crop_url} target="_blank" rel="noreferrer">
                  IIIF region at NDL
                </a>
              </dd>
            </>
          )}
        </dl>
      )}

      <div className="proposals">
        <h3>Machine proposals</h3>
        <p className="muted">
          None. Layer 4 is not built — when it is, proposals appear here styled
          distinctly from anything you have confirmed, and never pre-filled into
          the form.
        </p>
      </div>
    </section>
  );
}
