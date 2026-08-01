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

    return registered.as_dict()
