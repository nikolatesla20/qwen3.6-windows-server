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
  1. Try ``import vllm`` AND check the install-marker matches the bundled
     wheel's SHA256. If both pass, return.
  2. Locate ``wheels/vllm-*.whl`` (proper PEP 427 name) or legacy
     ``wheels/vllm.whl`` (back-compat with v0.1.4 and earlier zips).
  3. If pip is missing, bootstrap it with the vendored ``get-pip.py``
     (or download from https://bootstrap.pypa.io).
  4. ``pip install --extra-index-url <pytorch-cu126> <wheel>`` — pulls
     torch + ~150 deps from PyPI / pytorch.org. Several GB, several
     minutes. Resumable: rerunning skips wheels already cached.
  5. Write a marker JSON containing the wheel's SHA256 + version so a
     subsequent zip re-extract on top of an existing install correctly
     detects "different wheel, reinstall" instead of silently keeping
     the old one.

Runs in the parent cmd window before the Textual TUI mounts, so any
error is visible (no flashing-and-closing failure mode).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from . import paths

WHEEL_DIR_NAME = "wheels"
LEGACY_WHEEL_FILENAME = "vllm.whl"  # back-compat with v0.1.4 release zips
GET_PIP_VENDORED_NAME = "get-pip.py"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
TORCH_INDEX = "https://download.pytorch.org/whl/cu126"

# ~6 GB of wheels download + extracted site-packages. Used for the
# preflight free-space check; not load-bearing if shutil.disk_usage fails.
EXPECTED_INSTALL_BYTES = 6 * 1024 * 1024 * 1024

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
    """Return the bundled wheel, preferring a properly-named PEP 427 file.

    v0.1.5+ ships ``wheels/vllm-<version>-<tag>.whl`` directly. Older
    zips (v0.1.4 and earlier) shipped ``wheels/vllm.whl`` and renamed it
    at install time. Both layouts are accepted here.
    """
    wheels_dirs = [
        paths.install_root() / WHEEL_DIR_NAME,
        paths.writable_root() / WHEEL_DIR_NAME,
    ]
    # Prefer a real PEP 427 vllm-*.whl so we never need to rename.
    for d in wheels_dirs:
        if d.is_dir():
            for cand in sorted(d.glob("vllm-*.whl")):
                if cand.is_file():
                    return cand
    # Legacy fallback: vllm.whl needs renaming before pip will accept it.
    for d in wheels_dirs:
        legacy = d / LEGACY_WHEEL_FILENAME
        if legacy.is_file():
            return legacy
    return None


def _wheel_proper_filename(wheel: Path) -> Path:
    """Return a canonically-named copy of the wheel pip will accept.

    No-op when the wheel already has a PEP 427 filename. Otherwise reads
    version + tag from the wheel's METADATA / WHEEL files and writes a
    renamed copy under the writable root.
    """
    if wheel.name.startswith("vllm-") and wheel.name.endswith(".whl"):
        return wheel  # already properly named — nothing to do

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
        version = version or "0.0.0"
        tag = tag or "py3-none-any"

    proper_name = f"vllm-{version}-{tag}.whl"
    dest = paths.writable_root() / WHEEL_DIR_NAME / proper_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.is_file() or dest.stat().st_size != wheel.stat().st_size:
        shutil.copy2(wheel, dest)
    return dest


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_marker() -> dict:
    p = _marker_path()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_marker(payload: dict) -> None:
    try:
        _marker_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as e:
        # Non-fatal — site-packages may be read-only when install_root is
        # under Program Files. The next run will just re-import-check.
        print(f"  (note: could not write install marker: {e})")


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


def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024:
            return f"{n:.2f} {unit}"
        n /= 1024.0
    return f"{n:.2f} PiB"


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
    # Free-space preflight: warn loudly if the embedded python's drive
    # doesn't have room for the ~6 GB of wheels we're about to fetch and
    # extract into site-packages.
    try:
        target = _site_packages()
        target.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(target).free
        print(f"  disk free:     {_fmt_bytes(free)} on {Path(target.anchor or target).drive or target}")
        print(f"  expected use:  ~{_fmt_bytes(EXPECTED_INSTALL_BYTES)} (vLLM + torch + CUDA wheels)")
        if free < EXPECTED_INSTALL_BYTES:
            print()
            print(f"  [ERROR] Need ~{_fmt_bytes(EXPECTED_INSTALL_BYTES)} free, only {_fmt_bytes(free)} available.")
            print("          Free up space and re-run, or move the install to a roomier drive.")
            sys.exit(1)
        if free < EXPECTED_INSTALL_BYTES * 1.25:
            print("  [warn]         Disk is tight (<25% headroom). Pip download cache may fail mid-install.")
    except OSError:
        pass
    print(f"  est. time:     5–15 min on a fast (>200 Mbps) connection")
    print()


def ensure_runtime() -> None:
    """Block until vllm + the bundled wheel's exact build are installed.

    Idempotent: a no-op when the marker file's wheel SHA matches the
    bundled wheel and ``import vllm`` works. When a user re-extracts a
    new release zip on top of an existing install we detect the SHA
    mismatch and reinstall — without that check, the old vLLM stays in
    site-packages forever.
    """
    wheel = _wheel_path()
    bundled_sha = _sha256_file(wheel) if wheel and wheel.is_file() else None
    marker = _read_marker()

    # Fast path: marker matches the bundled wheel and vllm imports cleanly.
    if (
        bundled_sha
        and marker.get("wheel_sha256") == bundled_sha
        and _vllm_importable()
    ):
        return

    # Older install (no marker / legacy "ok" string) but vllm imports.
    # If we can't see a bundled wheel either, leave it alone — the user
    # may be running against their own venv.
    if marker and marker.get("wheel_sha256") is None and _vllm_importable() and not wheel:
        return

    if wheel is None:
        print(
            "[setup] Could not find the bundled wheel. Expected one of:\n"
            f"  {paths.install_root() / WHEEL_DIR_NAME / 'vllm-*.whl'}\n"
            f"  {paths.install_root() / WHEEL_DIR_NAME / LEGACY_WHEEL_FILENAME}\n"
            "Re-extract the release zip or drop the wheel into the wheels/ folder."
        )
        sys.exit(1)

    _print_banner()

    if marker.get("wheel_sha256") and marker.get("wheel_sha256") != bundled_sha:
        print("  [reinstall] Bundled wheel changed since last install — reinstalling vLLM.")
        print(f"             marker: {marker.get('wheel_sha256', '<none>')[:12]}...")
        print(f"             bundle: {bundled_sha[:12]}...")
        print()

    proper_wheel = _wheel_proper_filename(wheel)

    if not _pip_available():
        _bootstrap_pip()

    _install_wheel(proper_wheel)

    payload = {
        "wheel_sha256": bundled_sha,
        "wheel_filename": wheel.name,
    }
    # Best-effort: read the version out of the wheel name for human eyes.
    if proper_wheel.name.startswith("vllm-"):
        try:
            payload["version"] = proper_wheel.name.split("-", 2)[1]
        except IndexError:
            pass
    _write_marker(payload)

    print()
    print("[setup] vLLM runtime installed.")
    print()
