/**
 * Pane 3 - the crop under the cursor, and two machine readings of the officer.
 *
 * NDL's reading is the volume OCR binned into the template's cells
 * (app/proposal_service.py). The zoomed re-reading runs NDLOCR-Lite on each
 * cell on its own (app/cell_ocr.py) and is compared with it: where the two
 * agree the row says so, and where they differ the re-reading is offered as an
 * alternative. The reader takes one, or types their own - a person's reading is
 * always the last word.
 *
 * The styling contract predates both engines and is kept exactly: a suggestion
 * must never look like a confirmed value, and nothing reaches the form until the
 * reader takes it. "Take all" takes NDL's settled readings only; an alternative
 * is always a choice made by hand.
 */
import type {
  Cell,
  CellOcrJob,
  CellReading,
  FieldProposal,
  OcrEngine,
  OfficerProposals,
} from "../api";
import type { Values } from "../observation";

/** Template fields in the order they sit down an officer's strip. */
const ORDER: { field: string; ja: string }[] = [
  { field: "seniority_no", ja: "序列番号" },
  { field: "name_raw", ja: "氏名" },
  { field: "cohort", ja: "期" },
  { field: "post", ja: "職名" },
  { field: "commissioning_date", ja: "少尉任官" },
  { field: "rank_date", ja: "現階級任官" },
  { field: "prev_rank_date", ja: "前階級任官" },
  // The Taishō volumes print every appointment in one cell, each date tagged
  // with its rank; the schema's 任官年月日 is the line tagged 少尉 inside it.
  { field: "appointment_dates", ja: "任官ノ年月日" },
  { field: "service_in_rank", ja: "実役停年" },
  { field: "court_rank_decorations", ja: "位階勲等" },
];

const METHOD: Record<FieldProposal["method"], string> = {
  "ndl-ocr": "NDL OCR",
  digits: "NDL OCR · number",
  eradate: "NDL OCR · date read",
  inherited: "printed ditto · resolves from the row above",
  refused: "not accepted",
  blank: "nothing read",
};

/** Proposals "take all" may use: NDL's settled ones, bound to an empty form field. */
export function wholesaleTakes(
  proposals: OfficerProposals | undefined,
  values: Values,
): FieldProposal[] {
  if (!proposals) return [];
  return Object.values(proposals.fields).filter(
    (p) =>
      p.form_key != null &&
      p.fill != null &&
      p.wholesale &&
      !(values[p.form_key] ?? "").trim(),
  );
}

function shown(p: FieldProposal): string {
  switch (p.method) {
    case "blank":
      return "—";
    case "inherited":
      return `${p.raw || "同"} → ${p.value ?? ""}`;
    case "eradate":
      return p.raw && p.raw !== p.value ? `${p.raw} → ${p.value}` : (p.value ?? "");
    case "refused":
      return p.raw || "—";
    default:
      return p.value ?? p.raw;
  }
}

interface Props {
  field: string;
  cell: Cell | undefined;
  /** Local crop for the current cell; the institution's copy is provenance only. */
  localCropUrl: string | null;
  officerCropUrl: string | null;
  proposals: OfficerProposals | undefined;
  /** Why the page has no NDL proposals, when it has none. */
  unavailable: string | null;
  loading: boolean;
  values: Values;
  onTake: (formKey: string, fill: string, source: string) => void;
  onTakeAll: () => void;
  officerIndex: number;
  /** Zoomed re-readings for the page, keyed "officerIndex:field". */
  readings: Record<string, CellReading>;
  ocrJob: CellOcrJob | null;
  engine: OcrEngine | null;
  ocrError: string | null;
  /** The cell being re-read right now, as "officerIndex:field". */
  rereading: string | null;
  onStartPageOcr: () => void;
  onReread: (field: string) => void;
  /** Start a zoom-read of every page as it is opened. */
  autoZoom: boolean;
  onAutoZoom: (on: boolean) => void;
}

export function Candidates({
  field,
  cell,
  localCropUrl,
  officerCropUrl,
  proposals,
  unavailable,
  loading,
  values,
  onTake,
  onTakeAll,
  officerIndex,
  readings,
  ocrJob,
  engine,
  ocrError,
  rereading,
  onStartPageOcr,
  onReread,
  autoZoom,
  onAutoZoom,
}: Props) {
  const takeable = wholesaleTakes(proposals, values);
  const running = ocrJob?.state === "running";
  const engineDown = engine?.available === false;
  const tally = { agrees: 0, alternative: 0, unreadable: 0 };
  for (const r of Object.values(readings)) tally[r.status] += 1;
  const readCount = tally.agrees + tally.alternative + tally.unreadable;
  const mine = (name: string): CellReading | undefined => readings[`${officerIndex}:${name}`];
  const activeBusy = cell != null && rereading === `${officerIndex}:${cell.field}`;
  const hasRows = Boolean(proposals) || ORDER.some(({ field: name }) => mine(name));

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
        {cell && !engineDown && (
          <button
            type="button"
            className="crop__reread"
            onClick={() => onReread(cell.field)}
            disabled={activeBusy}
            title="Read this cell again with NDLOCR-Lite, zoomed in, and compare it with NDL's reading (Alt+R)"
          >
            {activeBusy ? (
              "reading this cell…"
            ) : (
              <>
                zoom-read this cell <kbd>Alt</kbd>+<kbd>R</kbd>
              </>
            )}
          </button>
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
        <header className="proposals__head">
          <h3>Machine readings</h3>
          {takeable.length > 0 && (
            <button
              type="button"
              onClick={onTakeAll}
              title="Take every settled NDL reading into an empty field (Alt+A)"
            >
              take {takeable.length} <kbd>Alt</kbd>+<kbd>A</kbd>
            </button>
          )}
        </header>

        <div className="zoomocr">
          {engineDown ? (
            <p className="muted">Zoomed re-reading is unavailable: {engine?.reason}</p>
          ) : (
            <p className="zoomocr__line">
              <button
                type="button"
                onClick={onStartPageOcr}
                disabled={running}
                title="Re-read every cell on this page with NDLOCR-Lite, one zoomed cell at a time, this officer first (Alt+O)"
              >
                {running ? (
                  `zoom-reading cells ${ocrJob?.done ?? 0}/${ocrJob?.total || "…"}`
                ) : (
                  <>
                    zoom-read whole page <kbd>Alt</kbd>+<kbd>O</kbd>
                  </>
                )}
              </button>
              {readCount > 0 && (
                <span className="muted">
                  {tally.agrees} agree · {tally.alternative} differ · {tally.unreadable}{" "}
                  unread
                </span>
              )}
              <label className="zoomocr__auto" title="Start the zoom-read by itself on every page you open">
                <input
                  type="checkbox"
                  checked={autoZoom}
                  onChange={(e) => onAutoZoom(e.target.checked)}
                />
                every page I open
              </label>
            </p>
          )}
          {ocrJob?.state === "failed" && (
            <p className="unresolved">zoom-reading stopped: {ocrJob.error}</p>
          )}
          {ocrError && <p className="unresolved">{ocrError}</p>}
        </div>

        {loading && <p className="muted">reading NDL's OCR for this page…</p>}
        {!loading && unavailable && (
          <p className="muted">No NDL reading for this page: {unavailable}</p>
        )}

        {hasRows && (
          <ol className="proplist">
            {ORDER.map(({ field: name, ja }) => {
              const p = proposals?.fields[name];
              const again = mine(name);
              if (!p && !again) return null;
              const formKey = p?.form_key ?? again?.rerun.form_key ?? null;
              const taken = (fill: string | null) =>
                formKey != null && fill != null && (values[formKey] ?? "") === fill;
              const busy = rereading === `${officerIndex}:${name}`;
              const classes = [
                "prop",
                `prop--${p?.method ?? "blank"}`,
                formKey != null && formKey === field ? "prop--active" : "",
                p?.suspect ? "prop--suspect" : "",
              ]
                .filter(Boolean)
                .join(" ");
              return (
                <li key={name} className={classes}>
                  <span className="prop__label">{ja}</span>
                  <span className="prop__value">{p ? shown(p) : "—"}</span>
                  {formKey != null && p?.fill != null ? (
                    <button
                      type="button"
                      className="prop__take"
                      disabled={taken(p.fill)}
                      onClick={() => onTake(formKey, p.fill as string, "ndl")}
                    >
                      {taken(p.fill) ? "taken" : "take"}
                    </button>
                  ) : (
                    <span className="prop__ctx">{formKey == null ? "context" : ""}</span>
                  )}
                  <span className="prop__method">
                    {p ? METHOD[p.method] : "no NDL reading"}
                    {p?.suspect ? " · cell edge inferred" : ""}
                  </span>
                  <button
                    type="button"
                    className="prop__reread linkish"
                    onClick={() => onReread(name)}
                    disabled={busy || engineDown}
                    title="Read this cell again, zoomed in, with NDLOCR-Lite"
                  >
                    {busy ? "reading…" : "zoom-read"}
                  </button>
                  {p?.method === "refused" && p.note && (
                    <span className="prop__why">{p.note}</span>
                  )}
                  {name === "name_raw" && proposals?.birth_raw && (
                    <span className="prop__note">born (as read): {proposals.birth_raw}</span>
                  )}
                  {again?.status === "agrees" && (
                    <span className="prop__agree">
                      ✓ NDLOCR-Lite, zoomed in, reads the same
                      {again.variant_only ? " (in the modern form — NDL keeps the printed one)" : ""}
                    </span>
                  )}
                  {again?.status === "alternative" && (
                    <span className="prop__alt">
                      <span className="prop__alt-label">NDLOCR-Lite</span>
                      <span className="prop__alt-value">{shown(again.rerun)}</span>
                      {formKey != null && again.rerun.fill != null ? (
                        <button
                          type="button"
                          className="prop__take"
                          disabled={taken(again.rerun.fill)}
                          onClick={() => onTake(formKey, again.rerun.fill as string, "ndlocr-lite")}
                        >
                          {taken(again.rerun.fill) ? "taken" : "take"}
                        </button>
                      ) : (
                        <span className="prop__ctx">context</span>
                      )}
                    </span>
                  )}
                  {again?.status === "unreadable" && (
                    <span className="prop__note">
                      NDLOCR-Lite could not read it
                      {again.rerun.raw ? ` (saw ${again.rerun.raw})` : ""}
                    </span>
                  )}
                </li>
              );
            })}
          </ol>
        )}

        <p className="proposals__foot muted">
          Nothing here is recorded until you take it and record the officer. If neither
          reading is right, type what the page says.
        </p>
      </div>
    </section>
  );
}
