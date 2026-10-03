"""Build the program a reader's kit runs: "Start Transcription.exe".

    python scripts/build_kit_app.py            # -> build/kit-app/Start Transcription/

One folder holding the launcher (kit/launcher.py), a private Python, and the
workstation itself. A reader needs nothing installed. scripts/build_volume_kit.py
copies this folder into each kit, so it is built once and reused; rebuild it
after changing the workstation.

The workstation's source travels as plain files beside the runtime, not frozen
into it. Every module here finds its neighbours - templates, vocabularies, the
schema, the built UI - by walking up from its own file, and that only works
when the files are laid out as they are in the repository. So the repository's
layout is reproduced inside the bundle, and the launcher imports from it.
PyInstaller is then told, by reading the source's imports, which third-party
and standard-library modules that code will ask for.

Builds in its own virtual environment (.venv-kit), created on first use: the
kit must carry exactly the packages in requirements.txt, and nothing this
machine happens to have installed.
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv-kit"
OUT = ROOT / "build" / "kit-app"
WORK = ROOT / "build" / "kit-work"
NAME = "Start Transcription"
SOURCE_DIRS = ("app", "reading", "ingestion")
# Whole folders the workstation reads at run time, at their repository paths.
DATA = ("templates", "data/vocab", "db", "app/ui/dist")


def venv_python() -> Path:
    return VENV / "Scripts" / "python.exe"


def ensure_venv() -> None:
    if not venv_python().exists():
        print(f"creating {VENV.name} ...")
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
    probe = subprocess.run([str(venv_python()), "-c", "import PyInstaller, fastapi, cv2"],
                           capture_output=True)
    if probe.returncode != 0:
        print("installing the workstation's packages and PyInstaller ...")
        subprocess.check_call([str(venv_python()), "-m", "pip", "install", "-q",
                               "-r", str(ROOT / "requirements.txt"), "pyinstaller"])


def find_local(name: str) -> Path | None:
    for sub in SOURCE_DIRS:
        path = ROOT / sub / f"{name}.py"
        if path.exists():
            return path
    return None


def walk_imports(entries: list[Path]) -> tuple[list[Path], list[str]]:
    """The workstation's own modules reachable from `entries`, and every other
    module name they import - in functions too, which is where the lazy ones are."""
    local: dict[Path, None] = {}
    foreign: set[str] = set()
    queue = list(entries)
    while queue:
        path = queue.pop()
        if path in local:
            continue
        local[path] = None
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module] + [f"{node.module}.{alias.name}" for alias in node.names]
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                if top == "__future__":
                    continue
                mine = find_local(top)
                if mine:
                    queue.append(mine)
                else:
                    foreign.add(name)
    return sorted(local), sorted(foreign)


def importable(name: str) -> bool:
    """Whether `name` is a module here - `from x import y` yields x.y, which is
    as often a function as a module."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def commit() -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--",
                                *SOURCE_DIRS, "kit", "templates", "data/vocab", "db"],
                               capture_output=True, text=True).stdout.strip()
        return out + ("+changes" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return None


def build() -> Path:
    import PyInstaller.__main__

    if not (ROOT / "app" / "ui" / "dist" / "index.html").exists():
        raise SystemExit("app/ui/dist is not built: run `npm --prefix app/ui run build`")
    sources, foreign = walk_imports([ROOT / "app" / "serve.py"])
    hidden = [name for name in foreign if importable(name)]
    args = [str(ROOT / "kit" / "launcher.py"), "--name", NAME, "--noconfirm", "--clean",
            "--windowed", "--distpath", str(OUT), "--workpath", str(WORK),
            "--specpath", str(WORK), "--collect-submodules", "uvicorn", "--log-level", "WARN"]
    for name in hidden:
        args += ["--hidden-import", name]
    for path in sources:
        args += ["--add-data", f"{path};{path.parent.relative_to(ROOT).as_posix()}"]
    for rel in DATA:
        args += ["--add-data", f"{ROOT / rel};{rel}"]
    print(f"{len(sources)} workstation modules, {len(hidden)} imports named to PyInstaller")
    PyInstaller.__main__.run(args)

    folder = OUT / NAME
    info = {
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": commit(),
        "python": sys.version.split()[0],
        "modules": [p.relative_to(ROOT).as_posix() for p in sources],
    }
    (folder / "_internal" / "kit-app.json").write_text(json.dumps(info, indent=1),
                                                       encoding="utf-8")
    return folder


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in-venv", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if not args.in_venv:
        ensure_venv()
        return subprocess.call([str(venv_python()), str(Path(__file__).resolve()), "--in-venv"])

    if OUT.exists():
        shutil.rmtree(OUT)
    folder = build()
    size = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())
    print(f"\nbuilt {folder}")
    print(f"{size / 1e6:.0f} MB in {sum(1 for f in folder.rglob('*') if f.is_file())} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
