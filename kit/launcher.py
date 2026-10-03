"""Start Transcription - what a reader double-clicks.

A reader's kit is a folder: this program, one volume's page images and OCR, and
a database with only that volume in it (app/kit.py). This starts the
workstation from that folder and opens it in the reader's browser. Nothing is
installed, nothing is fetched, and no setting lives outside the folder - so the
folder can sit on any Windows machine, and deleting it removes everything.

    Start Transcription.exe                    the reader's way in
    Start Transcription.exe --selftest out.json   prove the kit works, write a report
    Start Transcription.exe --headless --port 8011   server only, for testing

Built by scripts/build_kit_app.py; run unfrozen with --root <kit folder>.

The window is deliberately small: it says the workstation is running, reopens
the browser, and quits. Everything a reader does happens in the browser.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

APP_NAME = "Officer roster transcription"
# A fixed port keeps the browser's memory of where the reader left off, which
# is kept per address. Any free port is used if this one is taken.
PREFERRED_PORT = 47833
FROZEN = bool(getattr(sys, "frozen", False))

NOT_EXTRACTED = (
    "This folder is not complete, so the transcription program cannot start.\n\n"
    "If you opened it from inside the zip file: close this, right-click the zip "
    "file, choose \"Extract All...\", and start \"Start Transcription\" from the "
    "folder that creates.")
NOT_WRITABLE = (
    "This folder cannot be written to, so your work could not be saved.\n\n"
    "Move the whole folder somewhere of your own - Documents or the Desktop - "
    "and start it again from there.")


def bundle_root() -> Path:
    """Where the workstation's own files are: the PyInstaller bundle, or the repo."""
    if FROZEN:
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent.parent


def tell(title: str, text: str, *, error: bool = False, quiet: bool = False) -> None:
    """Say something to the reader - in a dialog, since a kit has no console."""
    logging.getLogger("kit").log(logging.ERROR if error else logging.INFO, "%s: %s", title, text)
    if quiet:
        return
    try:
        import tkinter
        from tkinter import messagebox
        root = tkinter.Tk()
        root.withdraw()
        (messagebox.showerror if error else messagebox.showinfo)(title, text)
        root.destroy()
    except Exception:  # no display at all: the log has it
        pass


def check_folder(root: Path) -> str | None:
    """Why this folder cannot be worked from, in the reader's words; None if it can."""
    data = root / "data"
    if not (data / "assignment.json").exists() or not (data / "officer-index.db").exists():
        return NOT_EXTRACTED
    probe = data / ".write-test"
    try:
        probe.write_text("ok", encoding="ascii")
        probe.unlink()
    except OSError:
        return NOT_WRITABLE
    return None


def setup_logging(root: Path) -> None:
    logs = root / "data" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stream = open(logs / "kit.log", "a", encoding="utf-8", buffering=1)
    # A windowed program has no stdout or stderr at all; code that prints -
    # and uvicorn's own logging - would fail on None.
    if sys.stdout is None or FROZEN:
        sys.stdout = stream
    if sys.stderr is None or FROZEN:
        sys.stderr = stream
    logging.basicConfig(stream=stream, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def enter_kit(root: Path) -> dict:
    """Point the workstation at this folder and nowhere else; returns the assignment."""
    data = root / "data"
    os.environ["JP_OCR_DATA"] = str(data)
    os.environ["JPOCR_DB"] = str(data / "officer-index.db")
    os.environ["JPOCR_KIT"] = str(data / "assignment.json")
    os.environ["JPOCR_OFFLINE"] = "1"
    # A kit carries no re-reading engine; never pick up one that happens to be
    # installed on this machine, or two readers' kits would behave differently.
    os.environ["NDLOCR_LITE_HOME"] = str(data / "no-engine")
    sys.dont_write_bytecode = True
    bundle = bundle_root()
    for sub in ("reading", "ingestion", "app"):
        if str(bundle / sub) not in sys.path:
            sys.path.insert(0, str(bundle / sub))
    return json.loads((data / "assignment.json").read_text(encoding="utf-8"))


def fetch_json(url: str, timeout: float = 5.0):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def already_running(root: Path, assignment: dict) -> str | None:
    """The address of this same kit if it is already up, else None."""
    marker = root / "data" / "kit-running.json"
    try:
        port = int(json.loads(marker.read_text(encoding="utf-8"))["port"])
        info = fetch_json(f"http://127.0.0.1:{port}/api/kit", timeout=1.5)
    except Exception:
        return None
    if info.get("kit") and info.get("pid") == assignment.get("pid"):
        return f"http://127.0.0.1:{port}/"
    return None


def free_port(preferred: int) -> int:
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return s.getsockname()[1]
    raise OSError("no free port on this machine")


class Workstation:
    """The server, on a thread of its own."""

    def __init__(self, port: int):
        import uvicorn
        import serve

        self.port = port
        self.url = f"http://127.0.0.1:{port}/"
        config = uvicorn.Config(serve.root, host="127.0.0.1", port=port, log_config=None,
                                access_log=False, loop="asyncio", http="h11", ws="none",
                                lifespan="off")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, name="workstation", daemon=True)

    def start(self, wait_s: float = 60.0) -> None:
        self.thread.start()
        deadline = time.time() + wait_s
        while time.time() < deadline:
            if not self.thread.is_alive():
                raise RuntimeError("the workstation stopped while starting - see data/logs/kit.log")
            try:
                fetch_json(self.url + "api/health", timeout=2)
                return
            except (urllib.error.URLError, OSError, ValueError):
                time.sleep(0.2)
        raise RuntimeError("the workstation did not start within a minute")

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


def selftest(station: Workstation, root: Path, assignment: dict) -> dict:
    """Open the kit the way a reader will, and say what works. Reads only -
    except for one return package, built and removed, because sending work
    home is the step a reader cannot recover from if it is broken."""
    base = station.url + "api"
    pid = assignment["pid"]
    checks: list[dict] = []

    def check(name: str, fn):
        started = time.time()
        try:
            detail = fn()
            checks.append({"check": name, "ok": True, "detail": detail,
                           "seconds": round(time.time() - started, 2)})
        except Exception as exc:
            checks.append({"check": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}",
                           "seconds": round(time.time() - started, 2)})

    def raw(path: str) -> bytes:
        with urllib.request.urlopen(base + path, timeout=300) as resp:
            return resp.read()

    def kit_matches():
        info = fetch_json(base + "/kit")
        assert info["kit"] and info["pid"] == pid, info
        return {"reader": info["reader"], "start_frame": info["start_frame"]}

    def reader_is_known():
        who = fetch_json(base + "/whoami")
        assert who["user_id"] == assignment["reader"]["user_id"], who
        return who["display_name"]

    pages: dict = {}

    def page_list():
        pages.update(fetch_json(base + f"/volumes/{pid}/pages", timeout=120))
        assert pages["frames_total"] > 0
        assert pages["cached"] == pages["frames_total"], "page images are missing from the kit"
        assert pages["surveyed"] == pages["frames_total"], "pages are not surveyed"
        stored = len(list((root / "data" / "cache" / pid / "registered").glob("frame_*.json")))
        assert stored == pages["frames_total"], \
            f"{pages['frames_total'] - stored} pages have no stored registration"
        return {"frames": pages["frames_total"], "officers_known": pages["officers_known"],
                "counts": pages["counts"]}

    def ui_is_built():
        with urllib.request.urlopen(station.url, timeout=30) as resp:
            html = resp.read().decode("utf-8")
        assert "<div id=\"root\">" in html or "id=\"root\"" in html, "the UI is not in the bundle"
        return len(html)

    def open_page(frame: int):
        def run():
            page = fetch_json(base + f"/volumes/{pid}/pages/{frame}", timeout=300)
            assert page["officer_count"] > 0, "no officers on a roster page"
            image = raw(f"/volumes/{pid}/pages/{frame}/image")
            assert image[:2] == b"\xff\xd8", "the page image is not a JPEG"
            x, y, w, h = page["officers"][0]["cells"][0]["bbox"]
            crop = raw(f"/volumes/{pid}/pages/{frame}/region?x={x}&y={y}&w={w}&h={h}")
            assert len(crop) > 100, "an empty crop"
            got = fetch_json(base + f"/volumes/{pid}/pages/{frame}/proposals", timeout=300)
            assert got.get("available", True), got.get("reason")
            filled = sum(1 for o in got["officers"] for f in o["fields"].values()
                         if f.get("fill"))
            assert filled > 0, "no machine readings on a roster page"
            fetch_json(base + f"/volumes/{pid}/pages/{frame}/observations")
            return {"template": page["template_id"], "officers": page["officer_count"],
                    "image_bytes": len(image), "fields_proposed": filled}
        return run

    def send_work_home():
        import zipfile
        existed = (root / "outbox").exists()
        req = urllib.request.Request(base + "/kit/return?reveal=false", data=b"", method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:
            got = json.loads(resp.read().decode("utf-8"))
        made = root / got["folder"] / got["file"]
        with zipfile.ZipFile(made) as z:
            names = sorted(z.namelist())
        assert "officer-index.db" in names and "officer-record.csv" in names, names
        made.unlink()
        if not existed:
            (root / "outbox").rmdir()
        return got

    check("the workstation answers", lambda: fetch_json(base + "/health")["status"])
    check("the interface is in the bundle", ui_is_built)
    check("this is the assigned kit", kit_matches)
    check("the reader is recognized without a code", reader_is_known)
    check("vocabularies load", lambda: {k: len(v) for k, v in fetch_json(base + "/vocab").items()
                                        if isinstance(v, list)})
    check("every page is present and surveyed", page_list)
    roster = [p["frame"] for p in pages.get("pages", []) if p.get("officers")]
    for frame in sorted({roster[0], roster[len(roster) // 2], roster[-1]}) if roster else []:
        check(f"frame {frame} opens with its image, a crop and machine readings",
              open_page(frame))
    check("work can be packed to send home", send_work_home)

    def window_draws():
        # Built and laid out, never shown for long: proves Tk and its data files
        # are in the bundle, which nothing else here would notice until a reader
        # double-clicked.
        root = build_window(station, assignment)
        root.update_idletasks()
        size = (root.winfo_reqwidth(), root.winfo_reqheight())
        root.destroy()
        return {"size": size}

    check("the launcher window can be drawn", window_draws)
    return {"ok": all(c["ok"] for c in checks), "pid": pid, "frozen": FROZEN,
            "python": sys.version.split()[0], "checks": checks}


def build_window(station: Workstation, assignment: dict):
    """The small window a reader sees: running, reopen the browser, quit."""
    import tkinter
    from tkinter import ttk

    root = tkinter.Tk()
    root.title(APP_NAME)
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=18)
    frame.grid()
    ttk.Label(frame, text=APP_NAME, font=("Segoe UI", 13, "bold")).grid(
        row=0, column=0, columnspan=2, sticky="w")
    ttk.Label(frame, text=assignment.get("title") or assignment["pid"], wraplength=420).grid(
        row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
    ttk.Label(frame, text="Reader: " + (assignment["reader"].get("display_name") or "")).grid(
        row=2, column=0, columnspan=2, sticky="w")
    ttk.Label(frame, wraplength=420, justify="left", text=(
        "The workstation is open in your web browser. Keep this window open while you "
        "work - closing it stops the program. Your work is saved as you go.")).grid(
        row=3, column=0, columnspan=2, sticky="w", pady=(12, 12))
    ttk.Button(frame, text="Open the workstation",
               command=lambda: webbrowser.open(station.url)).grid(row=4, column=0, sticky="w")
    ttk.Button(frame, text="Quit", command=root.destroy).grid(row=4, column=1, sticky="e")
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    return root


def window(station: Workstation, assignment: dict) -> None:
    root = build_window(station, assignment)
    root.after(400, lambda: webbrowser.open(station.url))
    root.mainloop()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", help="the kit folder (default: the folder this program is in)")
    ap.add_argument("--selftest", metavar="OUT.json",
                    help="check the kit end to end, write a report, and exit")
    ap.add_argument("--headless", action="store_true",
                    help="run the server only: no window, no browser")
    ap.add_argument("--port", type=int, default=PREFERRED_PORT)
    args = ap.parse_args(argv)
    quiet = bool(args.selftest or args.headless)
    if quiet:
        os.environ["JPOCR_KIT_QUIET"] = "1"

    if args.root:
        root = Path(args.root).resolve()
    elif FROZEN:
        root = Path(sys.executable).resolve().parent
    else:
        ap.error("--root is required when not running as the built program")

    problem = check_folder(root)
    if problem:
        if args.selftest:
            Path(args.selftest).write_text(json.dumps({"ok": False, "checks": [
                {"check": "the folder is complete and writable", "ok": False,
                 "detail": problem}]}, indent=1), encoding="utf-8")
        tell(APP_NAME, problem, error=True, quiet=quiet)
        return 2
    setup_logging(root)
    log = logging.getLogger("kit")
    marker = root / "data" / "kit-running.json"
    station = None
    try:
        assignment = enter_kit(root)
        if not quiet:
            running = already_running(root, assignment)
            if running:
                # A second double-click is a reader looking for the window they lost.
                webbrowser.open(running)
                return 0
        station = Workstation(free_port(args.port))
        log.info("starting %s for %s on %s", assignment["pid"],
                 assignment["reader"].get("display_name"), station.url)
        station.start()
        marker.write_text(json.dumps({"port": station.port, "pid": os.getpid()}),
                          encoding="utf-8")
        if args.selftest:
            report = selftest(station, root, assignment)
            Path(args.selftest).write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
            return 0 if report["ok"] else 1
        if args.headless:
            while station.thread.is_alive():
                time.sleep(0.5)
            return 0
        window(station, assignment)
        return 0
    except Exception as exc:
        log.error("failed to start\n%s", traceback.format_exc())
        if args.selftest:
            Path(args.selftest).write_text(json.dumps({"ok": False, "checks": [
                {"check": "the program starts", "ok": False,
                 "detail": traceback.format_exc()}]}, indent=1), encoding="utf-8")
        tell(APP_NAME, f"The transcription program could not start.\n\n{exc}\n\n"
                       f"Details are in data\\logs\\kit.log - send that file to the "
                       f"person who gave you this kit.", error=True, quiet=quiet)
        return 1
    finally:
        if station is not None:
            station.stop()
            try:
                marker.unlink()
            except OSError:
                pass


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
