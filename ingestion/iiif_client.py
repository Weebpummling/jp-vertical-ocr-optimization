"""NDL IIIF client: manifest fetch, page registration, polite image retrieval.

Layer 1. Registers a roster volume and its pages from the NDL IIIF manifest, and
fetches page images into the private data home. Stdlib only.

Registration writes straight into the database file:

    python ingestion/iiif_client.py register 1449474

Image fetch caches under %JP_OCR_DATA%/cache/{pid}/ and never overwrites:

    python ingestion/iiif_client.py fetch 1449474 51

Politeness: one request at a time, a fixed delay between image requests
(Spike B observed ~1.5 s/image as the working rate), an identifying UA, and
resumable caching so re-runs cost NDL nothing.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

MANIFEST_URL = "https://dl.ndl.go.jp/api/iiif/{pid}/manifest.json"
USER_AGENT = "jp-vertical-ocr-optimization (research ingestion; polite, cached)"
IMAGE_DELAY_S = 1.5


def _get(url: str, *, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def manifest(pid: str) -> dict:
    """Fetch the manifest, caching it beside the page images.

    Manifests for these volumes run to hundreds of canvases; caching means the
    region and page helpers cost NDL one manifest request per volume, ever.
    """
    try:
        cache = data_home() / "cache" / pid / "manifest.json"
    except SystemExit:
        cache = None  # no data home (e.g. CI) — fetch without caching
    if cache is not None and cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    man = json.loads(_get(MANIFEST_URL.format(pid=pid)).decode("utf-8"))
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
    return man


def canvases(man: dict) -> list[dict]:
    """Flatten a IIIF v2 manifest to [{frame_no, image_url, width, height}].

    Frame numbers are 1-based positions in the sequence — the same numbering the
    NDL viewer shows and the worklist uses.
    """
    out = []
    for seq in man.get("sequences", []):
        for i, canvas in enumerate(seq.get("canvases", []), start=1):
            images = canvas.get("images", [])
            resource = images[0].get("resource", {}) if images else {}
            service = resource.get("service", {})
            out.append({
                "frame_no": i,
                "image_url": resource.get("@id"),
                "service_id": service.get("@id"),
                "width": canvas.get("width"),
                "height": canvas.get("height"),
            })
    return out


def volume_label(man: dict) -> str:
    label = man.get("label", "")
    if isinstance(label, dict):  # IIIF v3-style language map, just in case
        label = next(iter(label.values()), [""])[0]
    return label


def register(pid: str, man: dict) -> dict:
    """Register the volume and its pages in the database, idempotently.

    Writes directly rather than emitting SQL to be piped into a client. The
    generate-SQL-and-pipe pattern existed because the database was a container
    with no Python driver on the near side; the database is now a local file, and
    piping Japanese text through a Windows console was a standing hazard - cp932
    cannot encode 步, so the pipe, not the data, decided what survived.

    The volume is matched by pid; pages rely on UNIQUE (volume_id, frame_no), so
    re-running after a partial ingest adds only what is missing.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
    import db  # imported here so the fetch/manifest paths stay stdlib-only

    cvs = canvases(man)
    added = 0
    with db.session() as conn:
        cur = conn.cursor()
        cur.execute("SELECT volume_id FROM source_volume WHERE pid = ?", (pid,))
        row = cur.fetchone()
        if row:
            volume_id = row["volume_id"]
        else:
            volume_id = db.new_id()
            cur.execute(
                "INSERT INTO source_volume (volume_id, title, series, pid, "
                "holding_institution, iiif_manifest_url, source_url, retrieved_at) "
                "VALUES (?, ?, '停年名簿', ?, 'NDL', ?, ?, datetime('now'))",
                (volume_id, volume_label(man), pid,
                 MANIFEST_URL.format(pid=pid), "https://dl.ndl.go.jp/pid/" + pid))
        for c in cvs:
            cur.execute(
                "INSERT INTO source_page (page_id, volume_id, frame_no) VALUES (?, ?, ?) "
                "ON CONFLICT (volume_id, frame_no) DO NOTHING",
                (db.new_id(), volume_id, c["frame_no"]))
            added += cur.rowcount if cur.rowcount > 0 else 0
    return {"pid": pid, "volume_id": volume_id, "canvases": len(cvs), "pages_added": added}


def data_home() -> Path:
    home = os.environ.get("JP_OCR_DATA")
    if not home:
        raise SystemExit("JP_OCR_DATA is not set (see docs/data-home.md)")
    return Path(home)


def fetch_page(pid: str, frame_no: int, *, out_dir: Path | None = None) -> Path:
    """Fetch one page image at full resolution into the cache; skip if cached."""
    out_dir = out_dir or (data_home() / "cache" / pid)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"frame_{frame_no:04d}.jpg"
    if dest.exists() and dest.stat().st_size > 0:
        print(f"cached: {dest}", file=sys.stderr)
        return dest

    man = manifest(pid)
    cvs = {c["frame_no"]: c for c in canvases(man)}
    if frame_no not in cvs:
        raise SystemExit(f"frame {frame_no} not in manifest ({len(cvs)} canvases)")
    c = cvs[frame_no]
    url = c["image_url"] or (c["service_id"] + "/full/full/0/default.jpg")

    time.sleep(IMAGE_DELAY_S)
    data = _get(url, timeout=120)
    tmp = dest.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(dest)
    print(f"fetched: {dest} ({len(data)} bytes)", file=sys.stderr)
    return dest


def region_url(pid: str, frame_no: int, bbox: tuple[int, int, int, int]) -> str:
    """IIIF Image API URL for a pixel region of a page — the re-checkable
    provenance form that roster_cell.crop_url stores. Anyone with the URL can
    see exactly the patch of page a value was read from.

    bbox is (x, y, w, h) in full-resolution pixel coordinates.
    """
    man = manifest(pid)
    cvs = {c["frame_no"]: c for c in canvases(man)}
    if frame_no not in cvs:
        raise SystemExit(f"frame {frame_no} not in manifest ({len(cvs)} canvases)")
    service = cvs[frame_no]["service_id"]
    if not service:
        raise SystemExit(f"frame {frame_no} has no IIIF image service")
    x, y, w, h = bbox
    return f"{service}/{x},{y},{w},{h}/full/0/default.jpg"


def fetch_region(pid: str, frame_no: int, bbox: tuple[int, int, int, int]) -> Path:
    """Fetch one cell/region crop into the cache; skip if already cached."""
    x, y, w, h = bbox
    out_dir = data_home() / "cache" / pid / "regions"
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"frame_{frame_no:04d}_{x}_{y}_{w}x{h}.jpg"
    if dest.exists() and dest.stat().st_size > 0:
        print(f"cached: {dest}", file=sys.stderr)
        return dest
    time.sleep(IMAGE_DELAY_S)
    data = _get(region_url(pid, frame_no, bbox), timeout=120)
    tmp = dest.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(dest)
    print(f"fetched: {dest} ({len(data)} bytes)", file=sys.stderr)
    return dest


def main(argv: list[str]) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    if len(argv) >= 2 and argv[0] == "register":
        result = register(argv[1], manifest(argv[1]))
        print(f"{result['pid']}: {result['canvases']} canvases in manifest, "
              f"{result['pages_added']} pages added")
    elif len(argv) >= 3 and argv[0] == "fetch":
        fetch_page(argv[1], int(argv[2]))
    elif len(argv) >= 7 and argv[0] == "region":
        bbox = tuple(int(v) for v in argv[3:7])
        print(region_url(argv[1], int(argv[2]), bbox))
        if "--fetch" in argv:
            fetch_region(argv[1], int(argv[2]), bbox)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
