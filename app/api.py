"""Layer 3 - HTTP surface for the transcription workstation.

Deliberately thin: every decision lives in `app/page_service.py`, which is
testable without a server. This module only routes, fetches, and serialises.

Run it:
    pip install -r requirements.txt
    uvicorn app.api:app --reload      # from the repository root

The read side answers where every officer and every field sits on the page; the
write side records what a human read there. Every write is attributed to the id
code the caller presented (docs/decision-workstation-auth.md) - no code path may
author a value without a person behind it.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "ingestion"))
sys.path.insert(0, str(ROOT / "reading"))

import page_service as ps  # noqa: E402
import db  # noqa: E402
import ditto  # noqa: E402
import eradate  # noqa: E402
import proposal_service as props  # noqa: E402
import volume_service as vs  # noqa: E402
import cell_ocr  # noqa: E402

app = FastAPI(
    title="jp-vertical-ocr-optimization workstation",
    description="Read-side API for the transcription workstation (Layer 3).",
)


# --------------------------------------------------------------------------
# identity
# --------------------------------------------------------------------------
#
# Each worker is issued an id code; entering it is how they identify themselves,
# and the code *is* their identifier on the project (decided 2 Aug 2026 -
# docs/decision-workstation-auth.md). It arrives in `X-Annotator` and resolves
# against `app_user.login`, so the frozen schema needs no credential column.
#
# Two consequences the code below is responsible for:
#
#   * the code is a bearer secret - it must not come back in a response or an
#     error string, because those end up in logs and on other people's screens;
#   * codes are minted by scripts/issue_access_code.py, never chosen. ~59 bits
#     of `secrets` entropy is what makes guessing a non-issue if the workstation
#     ever leaves this machine.
#
# Roles are deliberately not enforced: the requirement is that work is recorded
# to the person who did it, not that the software police who may do what.

def current_user(x_annotator: str | None = Header(default=None)) -> dict:
    """Resolve the caller's id code to an app_user row, or refuse.

    The refusal never repeats the submitted code back: a 401 body is exactly the
    place a secret gets copied into a log file or a screenshot.
    """
    if not x_annotator:
        raise HTTPException(status_code=401, detail="id code required (X-Annotator header)")
    user = db.find_user(x_annotator.strip())
    if not user:
        raise HTTPException(status_code=401, detail="unrecognized id code")
    return user


@app.get("/whoami")
def whoami(user: dict = Depends(current_user)) -> dict:
    """Who this code belongs to. Deliberately does not echo the code itself."""
    return {"user_id": str(user["user_id"]),
            "display_name": user["display_name"] or "(unnamed)"}


@app.get("/health")
def health() -> dict:
    templates = ps.R.load_library(ps.TEMPLATE_DIR)
    return {"status": "ok", "templates": [t.template_id for t in templates]}


@app.get("/templates")
def templates() -> dict:
    """The template library, as the UI needs it to label fields."""
    import json
    out = []
    for path in sorted(ps.TEMPLATE_DIR.glob("*.json")):
        spec = json.loads(path.read_text(encoding="utf-8"))
        out.append({
            "template_id": spec["template_id"],
            "layout_family": spec["layout_family"],
            "era": spec.get("era"),
            "fields": [
                {
                    "name": f["name"],
                    "confirmed": f.get("confirmed", False),
                    "evidence": f.get("evidence"),
                    "maps_to": f.get("maps_to"),
                }
                for f in spec.get("fields", [])
            ],
        })
    return {"templates": out}


@app.get("/vocab")
def vocab() -> dict:
    """Controlled vocabularies for the entry form's autocomplete.

    Frozen 31 Jul 2026 (11 ranks / 14 branches / 28 variants; 29 variants from
    10 Sep 2026, see data/vocab/README.md). Typing a printed
    variant must resolve to the canonical code in a keystroke or two - that is
    what keeps normalization from becoming a separate cleanup pass.
    """
    return ps.vocabularies()


@app.get("/volumes/{pid}/pages/{frame}")
def page(pid: str, frame: int,
         panel: int | None = Query(
             None, ge=0,
             description="One leaf only (0 = right-hand). Omit for the whole spread."),
         crop_urls: bool = Query(False,
                                 description="Build IIIF region URLs (costs a manifest fetch)")) -> dict:
    """Officer strips and field rectangles for one scan.

    Defaults to the **whole spread**, both leaves, numbered in reading order.
    This used to default to panel 0 and there was no way to ask for the other
    one, so the left-hand leaf of every scan went unread - see
    `page_service.register_spread`. Passing `panel` explicitly still serves a
    single leaf, for diagnosing one that will not register.

    404 if the frame cannot be retrieved; 422 if no panel registers against any
    template - an index page or a badly degraded scan is a human task, not a
    grid to be guessed at.
    """
    import iiif_client

    try:
        path = iiif_client.fetch_page(pid, frame)
    except SystemExit as exc:          # iiif_client exits on a bad frame/pid
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502,
                            detail=f"retrieval failed: {exc}") from exc

    url_for = iiif_client.region_url if crop_urls else None
    try:
        registered = ps.register_file(path, pid, frame, panel=panel,
                                      url_for=url_for)
    except ps.PageNotRegistrable as exc:
        if panel is None:
            _survey_quietly(pid, frame, vs.entry_not_roster(str(exc)))
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if panel is None:
        # Every page opened keeps the volume's completeness picture current.
        _survey_quietly(pid, frame, vs.entry_for_page(registered))

    payload = registered.as_dict()
    # The viewer needs the IIIF image service to build a tile source; the cell
    # rectangles are in that service's full-resolution pixel space, so panning
    # to a cell is a direct coordinate conversion with no extra lookup.
    payload["iiif_service"] = _service_id(iiif_client, pid, frame)
    return payload


@app.get("/volumes/{pid}/pages/{frame}/image")
def page_image(pid: str, frame: int) -> FileResponse:
    """The cached page scan itself.

    The workstation reads pixels from here, not from NDL. An annotator moving
    cell to cell would otherwise generate a request per crop and a tile storm
    per page; NDL answered exactly that pattern with HTTP 429 during
    development. Retrieval stays where the politeness lives - one cached fetch
    per page in `ingestion/iiif_client.py` - and everything downstream is local.

    The public IIIF URL is still what `roster_cell.crop_url` records: provenance
    points at the institution's copy, display comes from ours.
    """
    import iiif_client
    try:
        path = iiif_client.fetch_page(pid, frame)
    except SystemExit as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"retrieval failed: {exc}") from exc
    return FileResponse(path, media_type="image/jpeg")


@app.get("/volumes/{pid}/pages/{frame}/region")
def page_region(pid: str, frame: int,
                x: int = Query(..., ge=0), y: int = Query(..., ge=0),
                w: int = Query(..., gt=0), h: int = Query(..., gt=0)) -> Response:
    """One rectangle of the cached page, as JPEG - the cell crop the UI shows."""
    import cv2
    import iiif_client
    try:
        path = iiif_client.fetch_page(pid, frame)
    except SystemExit as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise HTTPException(status_code=500, detail=f"unreadable page image: {path}")
    ih, iw = image.shape[:2]
    x0, y0 = min(x, iw - 1), min(y, ih - 1)
    crop = image[y0:min(y0 + h, ih), x0:min(x0 + w, iw)]
    if crop.size == 0:
        raise HTTPException(status_code=422,
                            detail=f"region ({x},{y},{w},{h}) is outside the page {iw}x{ih}")
    ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise HTTPException(status_code=500, detail="failed to encode region")
    return Response(content=buf.tobytes(), media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=86400"})


# --------------------------------------------------------------------------
# write side
# --------------------------------------------------------------------------

class ObservationIn(BaseModel):
    """One officer as a human read them.

    `commissioning_date` is the reading exactly as it appears on the page
    (明四三、一二、二六 or 明治43年12月26日) - not a pre-parsed date. Normalizing
    is the server's job so that an ambiguous reading is refused in one place
    instead of being guessed differently by each caller.
    """

    row_index: int = Field(ge=0)
    name_raw: str | None = None
    rank_code: str | None = None
    branch_code: str | None = None
    post: str | None = None
    seniority_no: int | None = None
    commissioning_date: str | None = None
    field_confidence: dict = Field(default_factory=dict)
    # 備考. `observation` has no notes column and the schema is frozen, so a
    # reader's remark rides in `field_confidence` rather than being dropped on
    # the floor - it is a note about the reading, which is what that column is.
    notes: str | None = None
    # Columns the reader marked 同 - "same as the entry above". Named explicitly
    # rather than inferred from the values, because 兵科 and 階級 arrive as
    # vocabulary codes by then and a ditto is not a code.
    ditto: list[str] = Field(default_factory=list)


def _require_page(pid: str, frame: int) -> dict:
    page = db.find_page(pid, frame)
    if not page:
        raise HTTPException(
            status_code=404,
            detail=f"{pid} frame {frame} is not registered; run "
                   f"`python ingestion/iiif_client.py register {pid}` first")
    return page


@app.post("/volumes/{pid}/pages/{frame}/cells", status_code=201)
def create_cells(pid: str, frame: int,
                 user: dict = Depends(current_user)) -> dict:
    """Persist this scan's officer geometry as `roster_cell` rows.

    Idempotent: re-running refreshes the rectangles rather than duplicating
    officers, so a template improvement can be re-applied to a page already
    being transcribed without disturbing the observations hanging off it.

    Always the whole spread, and deliberately not selectable. `roster_cell` is
    UNIQUE (page_id, row_index) and a page_id is a frame, so persisting one leaf
    under its own column numbers collides with the other leaf's rows and
    re-points live observations at the wrong rectangles. `register_spread`
    numbers the whole scan in reading order, which is the only numbering under
    which the two leaves cannot collide.
    """
    import iiif_client
    page = _require_page(pid, frame)
    try:
        path = iiif_client.fetch_page(pid, frame)
        registered = ps.register_file(path, pid, frame,
                                      url_for=iiif_client.region_url)
    except ps.PageNotRegistrable as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SystemExit as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    payload = registered.as_dict()
    cells = db.upsert_cells(page["page_id"], payload["officers"],
                            user["user_id"], volume_pid=pid, frame_no=frame)
    return {"page_id": page["page_id"], "template_id": payload["template_id"],
            "cells": cells}


@app.post("/volumes/{pid}/pages/{frame}/observations", status_code=201)
def create_observation(pid: str, frame: int, body: ObservationIn,
                       user: dict = Depends(current_user)) -> dict:
    """Record one officer. Always a draft; confirmation is a separate act."""
    page = _require_page(pid, frame)
    if not page["edition_date"]:
        raise HTTPException(
            status_code=409,
            detail=f"volume {pid} has no edition_date, which observations need as "
                   f"as_of_date; run scripts/backfill_edition_dates.py")

    with db.read_session() as cur:
        cur.execute("SELECT cell_id FROM roster_cell WHERE page_id = ? AND row_index = ?",
                    (page["page_id"], body.row_index))
        cell = cur.fetchone()
    if not cell:
        raise HTTPException(
            status_code=409,
            detail=f"officer {body.row_index} has no roster_cell on this page; "
                   f"POST .../cells first")

    values = body.model_dump(exclude={"row_index", "commissioning_date", "notes"})
    confidence = dict(values.pop("field_confidence") or {})
    if body.notes and body.notes.strip():
        confidence["notes"] = body.notes.strip()

    # The date normalizer refuses rather than guesses. A reading it cannot
    # resolve is stored as no date at all, with the refusal recorded beside it,
    # so a bad value never enters the panel wearing the same clothes as a good
    # one. app/README: "ambiguous parses are flagged, not guessed".
    # --- ditto marks -------------------------------------------------------
    #
    # 同 says "same as the entry above" and nothing else, so it is resolved
    # against the row directly above and recorded as inherited. reading/ditto.py
    # holds the rules; the important one is that it never reaches further up the
    # column than one row.
    inherited: dict[str, dict] = {}
    dittoed = [c for c in body.ditto if c in ditto.DITTOABLE]
    if dittoed:
        above = db.row_above(page["page_id"], body.row_index)
        for column in dittoed:
            value = above.get(column) if above else None
            if value in (None, ""):
                missing = ("has no recorded value in that column"
                           if above else "has not been recorded yet")
                confidence[column] = {
                    "raw": "同",
                    "refused": (
                        f"printed as a ditto mark, but the officer directly above "
                        f"(no. {body.row_index} on this page) {missing}. Record that "
                        f"one first, or type this value out in full. A ditto is "
                        f"never resolved from further up the column - that would "
                        f"attach a value the page does not claim"),
                }
                values[column] = None
                continue
            values[column] = value
            inherited[column] = {"raw": "同", "from_row": above["row_index"],
                                 "value": value}
            confidence[column] = {
                "raw": "同",
                "inherited_from_row": above["row_index"],
                "note": "printed as a ditto mark; same as the entry above",
            }

    # --- the date ----------------------------------------------------------
    if "commissioning_date" in dittoed:
        parsed_date = values.get("commissioning_date")
    else:
        parsed_date = None
        if body.commissioning_date:
            if ditto.is_ditto(body.commissioning_date):
                # A ditto typed straight into the field, with no client to
                # declare it. Same rules; resolve it rather than refuse a
                # reading the page plainly makes.
                above = db.row_above(page["page_id"], body.row_index)
                stated = above.get("commissioning_date") if above else None
                if stated:
                    parsed_date = stated
                    inherited["commissioning_date"] = {
                        "raw": body.commissioning_date,
                        "from_row": above["row_index"], "value": stated}
                    confidence["commissioning_date"] = {
                        "raw": body.commissioning_date,
                        "inherited_from_row": above["row_index"],
                        "note": "printed as a ditto mark; same as the entry above",
                    }
                else:
                    confidence["commissioning_date"] = {
                        "raw": body.commissioning_date,
                        "refused": (
                            "printed as a ditto mark, but the officer directly "
                            f"above (no. {body.row_index} on this page) has no "
                            "recorded date to inherit. Record that one first, or "
                            "type this date out in full"),
                    }
            else:
                # As printed, or an ISO date handed back from the reading
                # worksheet - eradate decides which, and refuses either way.
                parsed = eradate.parse_reading(body.commissioning_date)
                if parsed.ok:
                    parsed_date = parsed.value
                else:
                    confidence["commissioning_date"] = {
                        "raw": body.commissioning_date, "refused": parsed.reason}
    values["commissioning_date"] = parsed_date
    values["field_confidence"] = confidence

    saved = db.create_observation(
        page_id=page["page_id"], cell_id=cell["cell_id"],
        as_of_date=page["edition_date"], user_id=user["user_id"],
        values=values, volume_pid=pid, frame_no=frame, row_index=body.row_index)
    return {
        "obs_id": saved["obs_id"],
        "status": saved["status"],
        "as_of_date": page["edition_date"],
        "commissioning_date": (parsed_date.isoformat()
                               if hasattr(parsed_date, "isoformat") else parsed_date),
        # What each ditto mark resolved to, keyed by column, so the reader sees
        # the values they did not type and can catch one landing on the wrong row.
        "inherited": inherited,
        # Only refusals. A field carrying 〓 for a character nobody could read was
        # still saved, with what the reader *could* see - reporting it as
        # "not recorded" would be a lie, and would teach annotators to distrust
        # the flag that matters.
        "flagged": {k: v for k, v in confidence.items()
                    if isinstance(v, dict) and "refused" in v},
        "needs_recheck": {k: v for k, v in confidence.items()
                          if isinstance(v, dict) and v.get("unreadable")},
    }


@app.get("/volumes/{pid}/pages/{frame}/observations")
def list_observations(pid: str, frame: int) -> dict:
    page = _require_page(pid, frame)
    # Everything is already a string: SQLite stores dates and timestamps as
    # ISO-8601 text, so there is nothing to serialize on the way out.
    rows = db.observations_for_page(page["page_id"])
    return {"page_id": str(page["page_id"]), "observations": rows,
            "row_audit": db.row_audit(page["page_id"])}


class RowAuditIn(BaseModel):
    status: str = Field(pattern="^(ok|extra_row)$")


@app.post("/volumes/{pid}/pages/{frame}/rows/{index}/audit")
def mark_row(pid: str, frame: int, index: int, body: RowAuditIn,
             user: dict = Depends(current_user)) -> dict:
    """Mark a column of the grid not an officer - or undo it.

    A section label, the column legend or an unused slot is a column the rulings
    define and no officer occupies. Marked, it stops counting toward the page, so
    the page can be finished. Attributed, reversible, and a flag raised by
    validation is left standing.
    """
    page = _require_page(pid, frame)
    mark = lambda: db.set_row_audit(page["page_id"], index, body.status, user["user_id"],  # noqa: E731
                                    volume_pid=pid, frame_no=frame)
    try:
        status = mark()
    except LookupError:
        create_cells(pid, frame, user)      # the row must exist to carry the mark
        try:
            status = mark()
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"row_index": index, "audit_status": status}


@app.get("/volumes/{pid}/progress")
def volume_progress(pid: str) -> dict:
    """Which frames of this volume have readings — the coverage question.

    Frames with nothing recorded are omitted rather than returned as zeroes: a
    volume runs to hundreds of pages and unread is the default state, so listing
    them all would be hundreds of rows saying nothing.
    """
    frames = db.volume_progress(pid)
    return {
        "pid": pid,
        "frames_with_readings": len(frames),
        "observations": sum(f["observations"] for f in frames),
        "frames": frames,
    }


def _survey_quietly(pid: str, frame: int, entry: dict) -> None:
    """Keep the completeness sidecar current - never at the cost of the page."""
    try:
        vs.record_survey(pid, frame, entry)
    except Exception:  # a derived cache must not fail a page load
        pass


# --------------------------------------------------------------------------
# volumes, completeness, proposals, export
# --------------------------------------------------------------------------

@app.get("/volumes")
def list_volumes() -> dict:
    """Registered volumes, with how much of each is surveyed, cached and read."""
    return {"volumes": vs.volumes()}


@app.get("/volumes/{pid}/pages")
def volume_pages(pid: str) -> dict:
    """Every frame of a volume with its completeness - the page picker's list.

    See app/volume_service.py for the statuses, and in particular why a spread
    with an unregistered leaf is never reported as complete.
    """
    if not db.volume_frames(pid):
        raise HTTPException(status_code=404,
                            detail=f"{pid} is not registered; run "
                                   f"`python ingestion/iiif_client.py register {pid}`")
    return vs.page_statuses(pid)


@app.get("/volumes/{pid}/pages/{frame}/proposals")
def page_proposals(pid: str, frame: int) -> dict:
    """Machine proposals for every officer on the scan, from NDL's own OCR.

    200 whenever the page itself can be read: "no proposals, and here is why" is
    something to show the reader, not a failure of the page. Nothing is written
    anywhere - a proposal becomes a record only when a person takes it and
    records the officer.
    """
    import iiif_client
    try:
        path = iiif_client.fetch_page(pid, frame)
    except SystemExit as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"retrieval failed: {exc}") from exc
    try:
        registered = ps.register_file(path, pid, frame)
    except ps.PageNotRegistrable as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        return props.propose_page(pid, frame, page=registered)
    except props.ProposalsUnavailable as exc:
        return {"pid": pid, "frame": frame, "available": False,
                "reason": str(exc), "officers": []}


# --------------------------------------------------------------------------
# zoomed re-reading: NDLOCR-Lite on each cell, compared with NDL's reading
# --------------------------------------------------------------------------
#
# None of these write to the record. A re-reading is an option offered beside
# NDL's reading; a person takes one, the other, or types their own.

@app.get("/ocr/engine")
def ocr_engine() -> dict:
    """Whether NDLOCR-Lite can be driven from here - and if not, why not."""
    return cell_ocr.engine_status()


def _page_image_or_error(pid: str, frame: int):
    import iiif_client
    try:
        return iiif_client.fetch_page(pid, frame)
    except SystemExit as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"retrieval failed: {exc}") from exc


@app.get("/volumes/{pid}/pages/{frame}/cell-ocr")
def cell_ocr_status(pid: str, frame: int) -> dict:
    """The page's zoomed re-readings so far, and the job producing them, if any."""
    return cell_ocr.JOBS.status(pid, frame)


@app.post("/volumes/{pid}/pages/{frame}/cell-ocr")
def cell_ocr_start(pid: str, frame: int,
                   start: int = Query(0, ge=0, description="officer to read first"),
                   fresh: bool = Query(False, description="read again cells already read")) -> dict:
    """Re-read every cell of the page, one zoomed cell at a time, in the background.

    Poll GET for progress. Cells already read with the same crop recipe and
    engine release are not read again unless `fresh`.
    """
    _page_image_or_error(pid, frame)
    engine, reason = cell_ocr.find_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail=reason)
    return cell_ocr.JOBS.start(pid, frame, first_officer=start, fresh=fresh)


@app.delete("/volumes/{pid}/pages/{frame}/cell-ocr")
def cell_ocr_cancel(pid: str, frame: int) -> dict:
    cell_ocr.JOBS.cancel(pid, frame)
    return cell_ocr.JOBS.status(pid, frame)


@app.post("/volumes/{pid}/pages/{frame}/officers/{index}/cells/{field}/cell-ocr")
def cell_ocr_one(pid: str, frame: int, index: int, field: str,
                 fresh: bool = Query(False, description="read again even if already read")) -> dict:
    """Re-read one cell now, zoomed in, and compare it with NDL's reading."""
    _page_image_or_error(pid, frame)
    try:
        return cell_ocr.reread(pid, frame, index, field, fresh=fresh)
    except cell_ocr.EngineUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ps.PageNotRegistrable as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except cell_ocr.WorkerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@app.get("/volumes/{pid}/export.xlsx")
def export_worksheet(
        pid: str,
        request: Request,
        frames: str = Query(..., description="a frame (100), ranges (60,95-110), or 'surveyed'"),
        images: bool = Query(False, description="embed the name crop beside each officer"),
) -> FileResponse:
    """The reading worksheet for these frames, as an Excel workbook.

    Uses only page images already on this machine: a request must never become
    a bulk download from NDL. `scripts/export_worksheet.py --fetch` is the route
    for pages not yet here.
    """
    import worksheet
    try:
        wanted = worksheet.parse_frames(frames, pid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if images and len(wanted) > worksheet.MAX_IMAGE_FRAMES:
        raise HTTPException(status_code=400,
                            detail=f"name images are limited to "
                                   f"{worksheet.MAX_IMAGE_FRAMES} frames per export "
                                   f"({len(wanted)} asked for)")
    # Links in the sheet open the workstation that served it, not a fixed port.
    base = str(request.base_url).rstrip("/")
    if base.endswith("/api"):
        base = base[: -len("/api")]
    result = worksheet.export(pid, wanted, images=images, fetch=False, base_url=base)
    return FileResponse(result.path, media_type=XLSX, filename=result.path.name)


def _service_id(iiif_client, pid: str, frame: int) -> str | None:
    try:
        canvases = iiif_client.canvases(iiif_client.manifest(pid))
    except Exception:
        return None
    for canvas in canvases:
        if canvas.get("frame_no") == frame:
            return canvas.get("service_id")
    return None
