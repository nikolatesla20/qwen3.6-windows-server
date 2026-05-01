"""First-run runtime installer.

The portable zip ships only the launcher, the wheel, and an embedded Python
3.12 runtime. It does NOT pre-install vLLM and its ~150 transitive
dependencies (torch, cuda libs, transformers, ray, etc.) — that would push
the zip past the 2 GB GitHub release-asset cap.

Instead, on first run we install the bundled wheel into the embedded
Python's ``site-packages`` directly. No venv layer: the embedded runtime
is already private to this install, and skipping the venv avoids the
``ensurepip`` / ``venv``-stripped-from-embedded-python problem.

Pipeline:
  1. Try ``import vllm``. If it works, return.
  2. Locate ``wheels/vllm.whl`` (bundled at install root).
  3. If pip is missing, bootstrap it with the vendored ``get-pip.py``
     (or download from https://bootstrap.pypa.io).
  4. ``pip install --extra-index-url <pytorch-cu126> <wheel>`` — pulls
     torch + ~150 deps from PyPI / pytorch.org. Several GB, several
     minutes. Resumable: rerunning skips wheels already cached.
  5. Write a marker so subsequent launches skip steps 1-4.

Runs in the parent cmd window before the Textual TUI mounts, so any
error is visible (no flashing-and-closing failure mode).
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from . import paths

WHEEL_DIR_NAME = "wheels"
WHEEL_FILENAME = "vllm.whl"
# pip rejects wheel files unless the filename matches PEP 427. The
# bundled wheel ships as a stable "vllm.whl" so users / docs don't need
# to track the exact version string. We rename to the canonical form at
# install time using the version embedded in the wheel's METADATA.
GET_PIP_VENDORED_NAME = "get-pip.py"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
TORCH_INDEX = "https://download.pytorch.org/whl/cu126"

MARKER_NAME = ".vllm_runtime_installed"


def _embedded_python() -> Path:
    return Path(sys.executable)


def _site_packages() -> Path:
    return _embedded_python().parent / "Lib" / "site-packages"


def _marker_path() -> Path:
    # Lives next to site-packages so it survives across re-extracts of
    # the zip (which would also wipe site-packages).
    return _site_packages() / MARKER_NAME


def _vllm_importable() -> bool:
    return importlib.util.find_spec("vllm") is not None


def _wheel_path() -> Path | None:
    candidates = [
        paths.install_root() / WHEEL_DIR_NAME / WHEEL_FILENAME,
        paths.writable_root() / WHEEL_DIR_NAME / WHEEL_FILENAME,
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def _wheel_proper_filename(wheel: Path) -> Path:
    """Return a canonically-named copy of the wheel pip will accept.

    Reads the version + tag from the wheel's METADATA / WHEEL files and
    builds a PEP 427 filename like ``vllm-0.19.0+devnen.1-cp312-cp312-win_amd64.whl``.
    The copy lives in the writable root so we never need to write to
    install_root (which may be Program Files).
    """
    import zipfile

    version = None
    tag = None
    with zipfile.ZipFile(wheel) as z:
        for name in z.namelist():
            if name.endswith("METADATA") and version is None:
                for line in z.read(name).decode("utf-8", errors="replace").splitlines():
                    if line.startswith("Version: "):
                        version = line.split(": ", 1)[1].strip()
                        break
            if name.endswith("WHEEL") and tag is None:
                for line in z.read(name).decode("utf-8", errors="replace").splitlines():
                    if line.startswith("Tag: "):
                        tag = line.split(": ", 1)[1].strip()
                        break
            if version and tag:
                break

    if not version or not tag:
        # Bundle is malformed — fall back to a guess. pip will tell us.
        version = version or "0.0.0"
        tag = tag or "py3-none-any"

    proper_name = f"vllm-{version}-{tag}.whl"
    dest = paths.writable_root() / WHEEL_DIR_NAME / proper_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.is_file() or dest.stat().st_size != wheel.stat().st_size:
        shutil.copy2(wheel, dest)
    return dest


def _pip_available() -> bool:
    return importlib.util.find_spec("pip") is not None


def _vendored_get_pip() -> Path | None:
    candidates = [
        paths.install_root() / WHEEL_DIR_NAME / GET_PIP_VENDORED_NAME,
        paths.install_root() / GET_PIP_VENDORED_NAME,
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def _download_get_pip() -> Path:
    dest = paths.writable_root() / GET_PIP_VENDORED_NAME
    print(f"  Downloading get-pip.py from {GET_PIP_URL} ...")
    req = urllib.request.Request(GET_PIP_URL, headers={"User-Agent": "qwen36-launcher/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as fh:
            fh.write(r.read())
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(f"failed to download get-pip.py: {e}") from e
    return dest


def _bootstrap_pip() -> None:
    src = _vendored_get_pip() or _download_get_pip()
    print(f"  Bootstrapping pip via {src.name} ...")
    r = subprocess.run(
        [sys.executable, str(src), "--no-warn-script-location"],
        capture_output=False,
    )
    if r.returncode != 0:
        raise RuntimeError(f"pip bootstrap failed (exit {r.returncode})")
    if not _pip_available():
        raise RuntimeError("pip bootstrap reported success but `import pip` still fails")


def _install_wheel(wheel: Path) -> None:
    print()
    print("  Installing vLLM and its ~150 transitive dependencies.")
    print("  Total download is multiple GB (torch + CUDA wheels + Python deps).")
    print("  Expect 5–15 minutes on a fast connection. Progress prints below.")
    print()
    cmd = [
        sys.executable, "-m", "pip", "install",
        "--extra-index-url", TORCH_INDEX,
        "--no-warn-script-location",
        str(wheel),
    ]
    r = subprocess.run(cmd, capture_output=False)
    if r.returncode != 0:
        raise RuntimeError(f"pip install failed (exit {r.returncode})")
    # vLLM 0.19.0+devnen.1's METADATA gates llguidance + xgrammar on
    # ``platform_machine == "x86_64"`` — Windows reports "AMD64" instead,
    # so pip's marker evaluator skips both. Install them explicitly so
    # the structured-output backend can import.
    print()
    print("  Installing Windows-marker-skipped extras (llguidance, xgrammar) ...")
    extras_cmd = [
        sys.executable, "-m", "pip", "install",
        "--no-warn-script-location",
        "llguidance>=1.3.0,<1.4.0",
        "xgrammar>=0.1.32,<1.0.0",
    ]
    r = subprocess.run(extras_cmd, capture_output=False)
    if r.returncode != 0:
        raise RuntimeError(f"extras install failed (exit {r.returncode})")


def _print_banner() -> None:
    print("=" * 70)
    print(" qwen3.6-windows-server — first-run runtime install")
    print("=" * 70)
    print(f"  python:        {sys.executable}")
    print(f"  install root:  {paths.install_root()}")
    print(f"  writable root: {paths.writable_root()}")
    print()


def ensure_runtime() -> None:
    """Block until vllm + torch are importable. Idempotent: a no-op on subsequent runs."""
    if _marker_path().is_file() and _vllm_importable():
        return
    if _vllm_importable():
        # Older install missing the marker — drop one so future runs short-circuit.
        try:
            _marker_path().write_text("ok", encoding="utf-8")
        except OSError:
            pass
        return

    _print_banner()

    wheel = _wheel_path()
    if wheel is None:
        print(
            "[setup] Could not find the bundled wheel. Expected one of:\n"
            f"  {paths.install_root() / WHEEL_DIR_NAME / WHEEL_FILENAME}\n"
            f"  {paths.writable_root() / WHEEL_DIR_NAME / WHEEL_FILENAME}\n"
            "Re-extract the release zip or drop vllm.whl into the wheels/ folder."
        )
        sys.exit(1)

    proper_wheel = _wheel_proper_filename(wheel)

    if not _pip_available():
        _bootstrap_pip()

    _install_wheel(proper_wheel)

    try:
        _marker_path().write_text("ok", encoding="utf-8")
    except OSError as e:
        # Non-fatal — site-packages may be read-only when install_root is
        # under Program Files. The next run will just re-import-check.
        print(f"  (note: could not write install marker: {e})")

    print()
    print("[setup] vLLM runtime installed. Launching TUI ...")
    print()
