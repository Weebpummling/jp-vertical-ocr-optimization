/**
 * Any volume, any page - and how finished each one is.
 *
 * "What is left?" used to be answerable one frame at a time, by opening it. A
 * volume runs to ~880 frames, so the picker lists them all with their state,
 * drawn from the database (what has been recorded) and the survey sidecar (how
 * many officers each frame holds - app/volume_service.py).
 *
 * `leaf_missing` is its own state and colour, never a shade of complete: a page
 * whose left-hand leaf did not register looks finished once every officer it
 * can show is recorded, and it is not.
 */
import { useEffect, useMemo, useState } from "react";
import {
  exportUrl,
  fetchPageStatuses,
  fetchVolumes,
  type PageStatusName,
  type VolumePages,
  type VolumeSummary,
} from "../api";

export const STATUS_LABEL: Record<PageStatusName, { ja: string; en: string }> = {
  complete: { ja: "完了", en: "complete" },
  leaf_missing: { ja: "片丁未登録", en: "leaf missing" },
  in_progress: { ja: "作業中", en: "in progress" },
  not_started: { ja: "未着手", en: "not started" },
  not_roster: { ja: "名簿外", en: "not a roster page" },
  unsurveyed: { ja: "未調査", en: "not surveyed" },
};

type Chip = PageStatusName | "roster" | "workable" | "all";

const CHIPS: Chip[] = [
  "roster",
  "workable",
  "in_progress",
  "not_started",
  "leaf_missing",
  "complete",
  "unsurveyed",
  "not_roster",
  "all",
];

function countFor(pages: VolumePages, chip: Chip): number {
  if (chip === "roster") return pages.pages.filter((p) => (p.officers ?? 0) > 0).length;
  if (chip === "all") return pages.pages.length;
  if (chip === "workable") return pages.pages.length - pages.counts.not_roster;
  return pages.counts[chip] ?? 0;
}

interface Props {
  pid: string;
  frame: number;
  onOpen: (pid: string, frame: number) => void;
  onClose: () => void;
}

export function PagePicker({ pid, frame, onOpen, onClose }: Props) {
  const [volumes, setVolumes] = useState<VolumeSummary[] | null>(null);
  const [selected, setSelected] = useState(pid);
  const [pages, setPages] = useState<VolumePages | null>(null);
  const [filter, setFilter] = useState<Chip>("workable");
  const [onMachine, setOnMachine] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchVolumes()
      .then((v) => setVolumes(v.volumes))
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    let live = true;
    setPages(null);
    setError(null);
    fetchPageStatuses(selected)
      .then((p) => {
        if (!live) return;
        setPages(p);
        // Open on the pages that hold officers once any are known. A volume is
        // mostly unsurveyed at first, and 800 "not surveyed" rows bury them.
        setFilter(p.pages.some((x) => (x.officers ?? 0) > 0) ? "roster" : "workable");
      })
      .catch((e) => {
        if (live) setError(String(e));
      });
    return () => {
      live = false;
    };
  }, [selected]);

  const shown = useMemo(() => {
    if (!pages) return [];
    return pages.pages.filter((p) => {
      if (onMachine && !p.cached) return false;
      if (filter === "roster") return (p.officers ?? 0) > 0;
      if (filter === "all") return true;
      if (filter === "workable") return p.status !== "not_roster";
      return p.status === filter;
    });
  }, [pages, filter, onMachine]);

  // Where to pick up: a page somebody started comes before a fresh one.
  const next =
    pages?.pages.find((p) => p.status === "in_progress") ??
    pages?.pages.find((p) => p.status === "not_started");
  const volume = volumes?.find((v) => v.pid === selected);
  const rosterPages = pages?.pages.filter((p) => p.officers).length ?? 0;

  return (
    <aside className="picker" aria-label="Pages">
      <header className="picker__head">
        <h2>Pages</h2>
        <button type="button" className="linkish" onClick={onClose}>
          close <kbd>Esc</kbd>
        </button>
      </header>

      <div className="picker__body">
        <label className="picker__vol">
          volume
          <select value={selected} onChange={(e) => setSelected(e.target.value)}>
            {!volumes?.some((v) => v.pid === selected) && (
              <option value={selected}>{selected}</option>
            )}
            {(volumes ?? []).map((v) => (
              <option key={v.pid} value={v.pid}>
                {v.edition_date ?? "????"} · {v.pid} · {v.frames_with_readings} of{" "}
                {v.pages} pages read
              </option>
            ))}
          </select>
        </label>
        {volume && <p className="picker__title">{volume.title}</p>}
        {error && <p className="unresolved">{error}</p>}
        {pages && (
          <p className="picker__summary">
            {pages.rows_read} officers recorded of {pages.officers_known} known ·{" "}
            {pages.surveyed} of {pages.frames_total} pages surveyed · {pages.cached} on
            this machine
          </p>
        )}
        {pages && (
          <div className="chips" role="group" aria-label="Filter by state">
            {CHIPS.map((chip) => (
              <button
                key={chip}
                type="button"
                className={`chip chip--${chip}`}
                aria-pressed={filter === chip}
                onClick={() => setFilter(chip)}
              >
                {chip === "all"
                  ? "all"
                  : chip === "roster"
                    ? "roster pages"
                    : chip === "workable"
                      ? "roster & unknown"
                      : STATUS_LABEL[chip].en}{" "}
                <span className="chip__n">{countFor(pages, chip)}</span>
              </button>
            ))}
          </div>
        )}
        <label className="picker__toggle">
          <input
            type="checkbox"
            checked={onMachine}
            onChange={(e) => setOnMachine(e.target.checked)}
          />
          only pages already on this machine
        </label>
        {next && (
          <button
            type="button"
            className="picker__next"
            onClick={() => onOpen(selected, next.frame)}
          >
            next to work: frame {next.frame} ({STATUS_LABEL[next.status].en})
          </button>
        )}
      </div>

      {!pages && !error && <p className="muted picker__loading">loading pages…</p>}

      <ol className="pagelist">
        {shown.map((p) => {
          const here = selected === pid && p.frame === frame;
          const label = STATUS_LABEL[p.status];
          return (
            <li key={p.frame}>
              <button
                type="button"
                className={`pg pg--${p.status}${here ? " pg--current" : ""}`}
                onClick={() => onOpen(selected, p.frame)}
                aria-current={here ? "page" : undefined}
                title={p.reason ?? label.en}
              >
                <span className="pg__frame">{p.frame}</span>
                <span className="pg__status">
                  {label.ja}
                  <small>{label.en}</small>
                </span>
                <span className="pg__count">
                  {p.officers == null
                    ? p.rows_read
                      ? `${p.rows_read} read`
                      : ""
                    : `${p.rows_read}/${p.officers}`}
                </span>
                <span className="pg__flags">
                  {/* Shown whatever the status: a missing leaf matters before a
                      page is started, not only once it looks finished. */}
                  {p.leaf_missing && p.status !== "leaf_missing" && (
                    <span className="tag tag--suspect" title="A leaf of this scan did not register: its officers cannot be read here">
                      leaf missing
                    </span>
                  )}
                  {p.needs_review && <span className="tag tag--suspect">review</span>}
                  {!p.cached && (
                    <span
                      className="pg__net"
                      title="Not on this machine: opening it fetches the scan from NDL"
                    >
                      NDL
                    </span>
                  )}
                </span>
              </button>
            </li>
          );
        })}
      </ol>

      <footer className="picker__foot">
        export to Excel:{" "}
        {selected === pid && (
          <>
            <a href={exportUrl(selected, String(frame))}>this page</a> ·{" "}
            <a href={exportUrl(selected, String(frame), true)}>with name images</a> ·{" "}
          </>
        )}
        {rosterPages > 0 ? (
          <a href={exportUrl(selected, "surveyed")}>
            every surveyed page ({rosterPages})
          </a>
        ) : (
          <span className="muted">survey the volume to export it whole</span>
        )}
      </footer>
    </aside>
  );
}
