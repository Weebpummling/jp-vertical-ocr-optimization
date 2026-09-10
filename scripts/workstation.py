"""Start the transcription workstation - one command, one address.

    python scripts/workstation.py                  # http://127.0.0.1:8000
    python scripts/workstation.py --open           # and open a browser at it
    python scripts/workstation.py --build          # rebuild the UI first (needs node)
    python scripts/workstation.py --port 8010

Records go to the database at JPOCR_DB, or the data home's officer-index.db.

Runs without --reload on purpose: killing a reloading uvicorn's parent orphans
the child that still holds the port.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "app" / "ui" / "dist"
sys.path.insert(0, str(ROOT / "app"))


def build_ui() -> bool:
    npm = shutil.which("npm")
    if not npm:
        print("npm is not installed here, so the UI cannot be built on this machine.")
        return False
    ui = ROOT / "app" / "ui"
    if not (ui / "node_modules").exists():
        if subprocess.call([npm, "--prefix", str(ui), "install"]) != 0:
            return False
    return subprocess.call([npm, "--prefix", str(ui), "run", "build"]) == 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--build", action="store_true", help="rebuild the UI before starting")
    ap.add_argument("--open", action="store_true", help="open a browser at the workstation")
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if args.build or not (DIST / "index.html").exists():
        if not build_ui() and not (DIST / "index.html").exists():
            print("No built UI to serve. Build it on a machine with node, copy "
                  "app/ui/dist here, and start again.")
            return 2

    if not os.environ.get("JP_OCR_DATA"):
        print("JP_OCR_DATA is not set; page images and OCR have nowhere to live.")
        return 2

    import db
    url = f"http://{args.host}:{args.port}"
    print(f"workstation  {url}")
    print(f"database     {db.db_path()}")
    print("stop with Ctrl+C")
    if args.open:
        threading.Timer(2.0, lambda: webbrowser.open(url)).start()
    return subprocess.call([sys.executable, "-m", "uvicorn", "app.serve:root",
                            "--host", args.host, "--port", str(args.port)], cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
