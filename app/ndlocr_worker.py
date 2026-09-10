"""NDLOCR-Lite, loaded once and kept: one JSON request per line on stdin.

Runs under NDLOCR-Lite's own interpreter with its source directory as the
working directory - never under the project's Python, which has neither
onnxruntime nor the models. `app/cell_ocr.py` starts it and talks to it; nothing
else should.

    request   {"id": 3, "image": "C:/.../crop.png"}
    reply     {"id": 3, "ok": true, "seconds": 0.51,
               "lines": [{"text": "931", "confidence": 0.98,
                          "box": [xmin, ymin, xmax, ymax], "vertical": true}]}

The first line written is {"ready": true, "version": ...} once the models have
loaded (about seven seconds), or {"ready": false, "error": ...} if they cannot.
NDLOCR-Lite prints progress on stdout, and the protocol owns stdout, so the
engine's own output is redirected to stderr at the file-descriptor level. End of
input ends the worker.

Standard library plus what NDLOCR-Lite itself installs - this file must not
import anything from the project.
"""
import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path


class _Captured(Exception):
    pass


def default_args(ocr):
    """NDLOCR-Lite's defaults, read from its own argument parser.

    Model file names change between releases, so they are never copied here:
    `ocr.main()` is run just far enough to build and parse its parser, and the
    namespace is taken before anything is processed.
    """
    captured = {}
    real = argparse.ArgumentParser.parse_known_args

    def capture(self, args=None, namespace=None):
        parsed, _rest = real(self, args, namespace)
        captured["args"] = parsed
        raise _Captured

    saved_argv = sys.argv
    argparse.ArgumentParser.parse_known_args = capture
    sys.argv = ["ocr.py", "--output", tempfile.gettempdir()]
    try:
        ocr.main()
    except _Captured:
        pass
    finally:
        argparse.ArgumentParser.parse_known_args = real
        sys.argv = saved_argv
    if "args" not in captured:
        raise RuntimeError("could not read NDLOCR-Lite's default arguments")
    return captured["args"]


def main() -> int:
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8",
                         buffering=1)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    sys.stdout = sys.stderr
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    sys.path.insert(0, os.getcwd())

    def say(message):
        protocol.write(json.dumps(message, ensure_ascii=False) + "\n")
        protocol.flush()

    try:
        import numpy as np
        from PIL import Image
        import ocr

        args = default_args(ocr)
        detector = ocr.get_detector(args)
        recognizer100 = ocr.get_recognizer(args=args)
        recognizer30 = ocr.get_recognizer(args=args, weights_path=args.rec_weights30)
        recognizer50 = ocr.get_recognizer(args=args, weights_path=args.rec_weights50)
        version = getattr(ocr, "__version__", None)
    except Exception as exc:  # the reason is the whole point of the reply
        say({"ready": False, "error": f"{type(exc).__name__}: {exc}"})
        return 2

    say({"ready": True, "version": version})
    scratch = tempfile.mkdtemp(prefix="ndlocr-worker-")

    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            request = json.loads(raw)
        except ValueError:
            continue
        request_id = request.get("id")
        try:
            started = time.time()
            image_path = request["image"]
            image = np.array(Image.open(image_path).convert("RGB"))
            result = ocr._run_ocr_on_image_array(
                detector, recognizer30, recognizer50, recognizer100,
                Path(image_path).name, image, scratch, save_viz=False)
            lines = []
            for line in result.get("json_lines", []):
                points = line.get("boundingBox") or []
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                lines.append({
                    "text": line.get("text", ""),
                    "confidence": line.get("confidence"),
                    "box": [min(xs), min(ys), max(xs), max(ys)] if points else None,
                    "vertical": line.get("isVertical") == "true",
                })
            say({"id": request_id, "ok": True, "lines": lines,
                 "seconds": round(time.time() - started, 3)})
        except Exception as exc:
            say({"id": request_id, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
