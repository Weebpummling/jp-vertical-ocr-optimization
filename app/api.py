"""Layer 3 - HTTP surface for the transcription workstation.

Deliberately thin: every decision lives in `app/page_service.py`, which is
testable without a server. This module only routes, fetches, and serialises.

Run it:
    pip install -r requirements.txt
    uvicorn app.api:app --reload      # from the repository root

The read side is what exists so far - given a volume and frame, where every
officer and every field sits on the page. Write endpoints (creating
observations) are not here yet: they touch the audited tables, and no code path
may author a value without a human behind it, so they land with authentication.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "ingestion"))

import page_service as ps  # noqa: E402

app = FastAPI(
    title="jp-vertical-ocr-optimization workstation",
    description="Read-side API for the transcription workstation (Layer 3).",
)


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

    Frozen 31 Jul 2026 (11 ranks / 14 branches / 28 variants). Typing a printed
    variant must resolve to the canonical code in a keystroke or two - that is
    what keeps normalization from becoming a separate cleanup pass.
    """
    return ps.vocabularies()


@app.get("/volumes/{pid}/pages/{frame}")
def page(pid: str, frame: int,
         panel: int = Query(0, ge=0, description="0 = right-hand page"),
         crop_urls: bool = Query(False,
                                 description="Build IIIF region URLs (costs a manifest fetch)")) -> dict:
    """Officer strips and field rectangles for one page panel.

    404 if the frame cannot be retrieved; 422 if the page registers against no
    template - an index page or a badly degraded panel is a human task, not a
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
        registered = ps.register_file(path, pid, frame, panel=panel, url_for=url_for)
    except ps.PageNotRegistrable as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

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


def _service_id(iiif_client, pid: str, frame: int) -> str | None:
    try:
        canvases = iiif_client.canvases(iiif_client.manifest(pid))
    except Exception:
        return None
    for canvas in canvases:
        if canvas.get("frame_no") == frame:
            return canvas.get("service_id")
    return None
