"""Build a reader's kit: one zip with the program, one volume, and their name on it.

    python scripts/build_volume_kit.py 1449426 --reader "Tanaka Hanako" \\
        --return-to "Email that file to lead@example.org."

The reader unzips it, double-clicks "Start Transcription", and reads. Nothing
is installed and nothing is fetched; their work comes home as one small file
(the workstation's "Send in my work"), merged with scripts/merge_returned.py.

What it does, in order - and it stops at the first thing that is not right:

  1. checks the volume is complete on this machine: every page image, NDL's OCR
     and the manifest (a kit cannot fetch what it lacks);
  2. finds the reader in the master database, or adds them;
  3. cuts a database holding only this volume, ids intact (app/kit_build.py);
  4. registers every page from its original scan, here, and stores the result in
     the kit - a kit never registers a page itself, so what a reader records
     against is exactly what this machine sees (app/page_service.py). Because of
     that the page images can be shipped smaller: by default they are recompressed
     to about 40% of their size (--images original copies them untouched);
  5. starts the kit's own program against the result and has it open pages the
     way a reader will (its --selftest), so a kit that would not work is never
     sent;
  6. zips it.

Kits are written to <data home>/kits unless --out says otherwise. The master
database is the one the workstation uses (JPOCR_DB, or the data home's).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _sub in ("app", "scripts", "ingestion", "reading"):
    if str(ROOT / _sub) not in sys.path:
        sys.path.insert(0, str(ROOT / _sub))

import build_kit_app  # noqa: E402

APP = build_kit_app.OUT / build_kit_app.NAME
EXE = f"{build_kit_app.NAME}.exe"
DEFAULT_RETURN = "Send that file to the person who gave you this kit."


def slug(name: str, fallback: str) -> str:
    ascii_name = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-")
    return ascii_name or fallback


def find_or_add_reader(name: str, issuer_code: str | None) -> dict:
    import db
    import issue_access_code

    with db.read_session() as cur:
        cur.execute("SELECT user_id, display_name FROM app_user WHERE display_name = ?", (name,))
        found = [dict(r) for r in cur.fetchall()]
    if len(found) > 1:
        raise SystemExit(f"{len(found)} people in the master database are called {name!r}; "
                         f"give one a distinguishing name first")
    if found:
        print(f"reader          {name} (already in the master database)")
        return found[0]
    issue_access_code.issue(name, issue_access_code._resolve_issuer(issuer_code))
    with db.read_session() as cur:
        cur.execute("SELECT user_id, display_name FROM app_user WHERE display_name = ?", (name,))
        print(f"reader          {name} (added to the master database)")
        return dict(cur.fetchone())


def ensure_app(rebuild: bool) -> None:
    info = APP / "_internal" / "kit-app.json"
    if rebuild or not (APP / EXE).exists() or not info.exists():
        print("building the kit program ...")
        if build_kit_app.main([]) != 0:
            raise SystemExit("the kit program did not build")
        return
    built = json.loads(info.read_text(encoding="utf-8")).get("commit")
    now = build_kit_app.commit()
    if built != now:
        print(f"note: the kit program was built from {built}, the checkout is at {now}; "
              f"--rebuild-app rebuilds it")


def run_selftest(stage: Path) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "selftest.json"
        env = {k: v for k, v in os.environ.items()
               if k not in ("JP_OCR_DATA", "JPOCR_DB", "JPOCR_KIT", "PYTHONPATH", "PYTHONHOME")}
        # A reader may have no network at all. Point every proxy at a dead port, so
        # anything that reached for the internet would fail the test here.
        env.update(HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9",
                   NO_PROXY="127.0.0.1,localhost")
        code = subprocess.call([str(stage / EXE), "--selftest", str(report)],
                               cwd=str(stage), env=env, timeout=1200)
        if not report.exists():
            raise SystemExit(f"the kit's self-test wrote no report (exit {code}); "
                             f"see {stage / 'data' / 'logs' / 'kit.log'}")
        return json.loads(report.read_text(encoding="utf-8"))


def zip_folder(stage: Path, dest: Path) -> None:
    part = dest.with_suffix(".part")
    with zipfile.ZipFile(part, "w", allowZip64=True) as z:
        for path in sorted(stage.rglob("*")):
            if path.is_dir():
                continue
            # Page images are already compressed; deflating them only costs time.
            method = zipfile.ZIP_STORED if path.suffix.lower() == ".jpg" else zipfile.ZIP_DEFLATED
            z.write(path, f"{stage.name}/{path.relative_to(stage).as_posix()}", method)
    part.replace(dest)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pid")
    ap.add_argument("--reader", required=True, help="the reader's name, as it should be recorded")
    ap.add_argument("--return-to", default=DEFAULT_RETURN,
                    help="one sentence telling the reader where to send their work")
    ap.add_argument("--images", choices=("small", "original"), default="small")
    ap.add_argument("--out", help="folder to write the kit into (default: <data home>/kits)")
    ap.add_argument("--issuer", help="your id code, to record who added a new reader")
    ap.add_argument("--workers", type=int, default=max(1, min(8, (os.cpu_count() or 2) - 2)))
    ap.add_argument("--rebuild-app", action="store_true", help="rebuild the kit program first")
    ap.add_argument("--force", action="store_true", help="replace a kit already built here")
    ap.add_argument("--no-zip", action="store_true", help="leave the folder, write no zip")
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    # Run this with the Python the workstation itself runs on (not the kit's
    # build environment): step 4 has to register pages exactly as the master does.

    import db
    import kit_build
    import volume_service as vs

    started = time.time()
    master = Path(db.db_path())
    cache = vs.data_home() / "cache" / args.pid
    out = Path(args.out) if args.out else vs.data_home() / "kits"
    print(f"master database {master}")

    volume = kit_build.volume_row(master, args.pid)
    print(f"volume          {args.pid}  {volume['title']}  ({len(volume['frames'])} pages)")
    problems = kit_build.check_volume_data(cache, volume["frames"])
    if problems:
        raise SystemExit("the volume's data is not complete:\n  " + "\n  ".join(problems))

    ensure_app(args.rebuild_app)
    reader = find_or_add_reader(args.reader, args.issuer)
    stage = out / f"Roster-{args.pid}-{slug(args.reader, reader['user_id'][:8])}"
    archive = stage.with_suffix(".zip")
    for existing in (stage, archive):
        if existing.exists():
            if not args.force:
                raise SystemExit(f"{existing} already exists; --force replaces it")
            shutil.rmtree(existing) if existing.is_dir() else existing.unlink()
    out.mkdir(parents=True, exist_ok=True)

    try:
        print("copying the program ...")
        shutil.copytree(APP, stage)
        data = stage / "data"
        data.mkdir()
        counts = kit_build.make_kit_db(master, data / "officer-index.db", args.pid,
                                       reader["user_id"])
        print(f"database        {counts['source_page']} pages, {counts['observation']} readings "
              f"already on record, {counts['app_user']} people")

        def progress(done: int, total: int) -> None:
            if done == total or done % 50 == 0:
                print(f"\rpages           {done}/{total}", end="", flush=True)

        stats = kit_build.prepare_volume_data(cache, data, args.pid, volume["frames"],
                                              images=args.images, workers=args.workers,
                                              progress=progress)
        print(f"\rpages           {stats['frames']} registered here and stored: "
              f"{stats['roster']} roster pages, {stats['officers']} officers; "
              f"images {stats['bytes'] / 1e6:.0f} MB ({args.images})")
        kit_build.write_assignment(data / "assignment.json", volume=volume, reader=reader,
                                   return_to=args.return_to, images=args.images,
                                   app_commit=build_kit_app.commit(),
                                   registered_with=kit_build.libraries())
        template = (ROOT / "kit" / "README-FIRST.txt").read_text(encoding="utf-8")
        (stage / "README-FIRST.txt").write_text(
            template.format(title=volume["title"], reader=reader["display_name"],
                            pid=args.pid, return_to=args.return_to),
            encoding="utf-8-sig", newline="\r\n")

        print("self-test       starting the kit as a reader would ...")
        report = run_selftest(stage)
        for check in report["checks"]:
            print(f"  {'ok  ' if check['ok'] else 'FAIL'} {check['check']}"
                  + ("" if check["ok"] else f"\n       {check['detail']}"))
        if not report["ok"]:
            raise SystemExit(f"the kit failed its self-test and was not zipped; "
                             f"it is left at {stage} to look at")
        shutil.rmtree(data / "logs", ignore_errors=True)
        (data / "kit-running.json").unlink(missing_ok=True)
    except BaseException:
        print()
        raise

    size = sum(f.stat().st_size for f in stage.rglob("*") if f.is_file())
    print(f"\nkit folder      {stage}  ({size / 1e6:.0f} MB)")
    if not args.no_zip:
        print("zipping ...")
        zip_folder(stage, archive)
        print(f"kit zip         {archive}  ({archive.stat().st_size / 1e6:.0f} MB)")
        print(f"sha256          {sha256(archive)}")
    print(f"done in {time.time() - started:.0f} s")
    print(f"\nSend the zip to {reader['display_name']}. They extract it, double-click "
          f"\"Start Transcription\", and read; README-FIRST.txt in the folder says the same.")
    print("When their file comes back:  python scripts/merge_returned.py <file>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
