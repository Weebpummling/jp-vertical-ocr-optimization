"""One process, one address: the workstation API under /api and the built UI at /.

Development runs two processes - uvicorn for the API, Vite for the UI, which
proxies /api to it. That is right while the UI is being changed and wrong for the
people using it, who need one thing to start and one address to open. This
mounts the same API at the same /api prefix the UI already calls and serves
`app/ui/dist` beside it, so the built UI runs unchanged.

    python scripts/workstation.py          # then open http://127.0.0.1:8000
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

import api  # noqa: E402

DIST = ROOT / "app" / "ui" / "dist"

root = FastAPI(title="jp-vertical-ocr-optimization workstation",
               docs_url=None, redoc_url=None, openapi_url=None)
root.mount("/api", api.app)

if (DIST / "index.html").exists():
    root.mount("/", StaticFiles(directory=DIST, html=True), name="ui")
else:
    @root.get("/", response_class=HTMLResponse)
    def not_built() -> str:
        return ("<h1>The workstation UI has not been built</h1>"
                "<p>Run <code>npm --prefix app/ui install</code> and "
                "<code>npm --prefix app/ui run build</code>, then restart. "
                "The API is already up: <a href='/api/health'>/api/health</a>.</p>")
