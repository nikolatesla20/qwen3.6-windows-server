"""Developer-side: build the portable launcher zip for a release.

Run on the developer machine ONCE per tag. Produces
``qwen3.6-windows-server-portable-x64.zip`` with embeddable Python, all
launcher dependencies preinstalled, the launcher source, snapshot/tool
scripts, and (optionally) the patched vLLM wheel. End users unzip and
double-click ``start.bat`` — they NEVER run pip.

Pass ``--wheel <path>`` to embed the patched vLLM wheel into the zip
under ``wheels/`` so the launcher can install it on first run without
network access.

Steps:
  1. Download python-3.12.X-embed-amd64.zip into a temp dir.
  2. Extract to <build>/python/.
  3. Edit python312._pth to enable site-packages.
  4. Bootstrap pip via get-pip.py (one-shot, into the embed).
  5. pip install textual rich httpx pyyaml --target python\\Lib\\site-packages.
  6. Strip pip / setuptools / wheel / Scripts / __pycache__ from the embed.
  7. Copy launcher/, snapshots/, windows_tools/, docs/, README + LICENSE,
     and the wheel (if --wheel given) into the build dir.
  8. Zip the whole build dir.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

PY_VERSION = "3.12.7"  # last 3.12 release with embed-amd64 zip
PY_EMBED_URL = f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-embed-amd64.zip"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

LAUNCHER_DEPS = ["textual>=0.86", "rich", "httpx", "pyyaml"]
TOP_FILES = ["LICENSE", "README.md", "CITATION.cff"]
TOP_DIRS = ["launcher", "snapshots", "windows_tools", "docs"]

REPO = Path(__file__).resolve().parent.parent


def download(url: str, dst: Path) -> None:
    print(f"[build] download {url} -> {dst.name}")
    urllib.request.urlretrieve(url, dst)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "dist" / "qwen3.6-windows-server-portable-x64.zip"))
    ap.add_argument("--workdir", default=str(REPO / ".build_launcher"))
    ap.add_argument("--wheel", default=None,
                    help="Path to vllm-...+devnen.X-...whl to bundle into wheels/")
    args = ap.parse_args()

    out_zip = Path(args.out)
    work = Path(args.workdir)
    if work.exists():
        shutil.rmtree(work)
    build = work / "qwen3.6-windows-server"
    build.mkdir(parents=True)
    py_dir = build / "python"
    py_dir.mkdir()

    # 1-2. embed python
    embed_zip = work / "embed.zip"
    download(PY_EMBED_URL, embed_zip)
    with zipfile.ZipFile(embed_zip) as zf:
        zf.extractall(py_dir)

    # 3. enable site-packages in ._pth + add ..\launcher so `python -m app`
    # works without relying on PYTHONPATH (embedded distros ignore it).
    pth = next(py_dir.glob("python*._pth"))
    txt = pth.read_text(encoding="utf-8")
    if "Lib\\site-packages" not in txt:
        txt = txt.rstrip() + "\nLib\\site-packages\n"
    if "..\\launcher" not in txt:
        # Insert right after the first '.' line so it has high priority.
        lines = txt.splitlines()
        for i, line in enumerate(lines):
            if line.strip() == ".":
                lines.insert(i + 1, "..\\launcher")
                break
        else:
            lines.append("..\\launcher")
        txt = "\n".join(lines) + "\n"
    if "import site" in txt and "#import site" in txt:
        txt = txt.replace("#import site", "import site")
    elif "import site" not in txt:
        txt = txt.rstrip() + "\nimport site\n"
    pth.write_text(txt, encoding="utf-8")

    # 4. get-pip
    get_pip = work / "get-pip.py"
    download(GET_PIP_URL, get_pip)
    py_exe = py_dir / "python.exe"
    subprocess.check_call([str(py_exe), str(get_pip), "--no-warn-script-location"])

    # 5. install deps
    sp = py_dir / "Lib" / "site-packages"
    sp.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(
        [str(py_exe), "-m", "pip", "install",
         "--no-warn-script-location",
         "--target", str(sp), *LAUNCHER_DEPS]
    )

    # 6. strip pip + tools + scripts (users don't need them)
    for victim in ["pip", "pip.exe", "setuptools", "wheel"]:
        for p in sp.glob(victim):
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
    for d in [py_dir / "Scripts"]:
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
    for pyc in py_dir.rglob("__pycache__"):
        shutil.rmtree(pyc, ignore_errors=True)

    # 7. copy launcher + snapshots + tools + docs + readme
    for f in TOP_FILES:
        src = REPO / f
        if src.exists():
            shutil.copy2(src, build / f)
    for d in TOP_DIRS:
        src = REPO / d
        if src.exists():
            shutil.copytree(src, build / d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # ship the user-facing start.bat at top level
    shutil.copy2(REPO / "launcher" / "start.bat", build / "start.bat")

    # 7b. optionally bundle the patched vLLM wheel under wheels/
    if args.wheel:
        wheel_src = Path(args.wheel)
        if not wheel_src.exists():
            print(f"[build] WARNING: --wheel {wheel_src} not found; skipping bundle", file=sys.stderr)
        else:
            wheels_dir = build / "wheels"
            wheels_dir.mkdir(exist_ok=True)
            shutil.copy2(wheel_src, wheels_dir / wheel_src.name)
            print(f"[build] bundled wheel: {wheel_src.name}")

    # 8. zip
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    print(f"[build] writing {out_zip}")
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in build.rglob("*"):
            zf.write(p, p.relative_to(build.parent))
    size_mb = out_zip.stat().st_size / (1024 * 1024)
    print(f"[build] done. {out_zip.name} = {size_mb:.1f} MiB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
