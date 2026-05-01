"""Shared resolution for snapshot scripts.

Each ``start_*.py`` imports VENV / MODEL_PATH / VCVARS from here so users
can override paths via environment variables instead of editing every
snapshot. Resolution order:

* ``VLLM_WINDOWS_VENV`` env var, else repo-root ``venv``.
* ``VLLM_MODEL_DIR`` env var, else repo-root ``models/Qwen3.6-27B-int4-AutoRound``.
* ``VLLM_WINDOWS_VCVARS`` env var, else the most likely VS 2022 install.
* ``VLLM_WINDOWS_LOGS`` env var, else repo-root ``logs``. Created on first use.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

def _resolve_vllm_exe() -> tuple[Path, Path]:
    """Resolve (PYTHON_HOME, VLLM_EXE).

    Resolution order:
      1. ``VLLM_WINDOWS_VENV`` env var → expects ``Scripts/vllm.exe`` and
         ``Scripts/python.exe`` underneath (developer / external venv).
      2. ``REPO_ROOT/venv/Scripts/vllm.exe`` (developer checkout).
      3. ``REPO_ROOT/python/Scripts/vllm.exe`` (portable release: vllm
         is installed directly into the embedded Python's site-packages
         by ``launcher/app/setup.py``, which writes the entry-point exe
         under ``python/Scripts/``).
    """
    env = os.environ.get("VLLM_WINDOWS_VENV")
    if env:
        root = Path(env)
        return root, root / "Scripts" / "vllm.exe"
    dev_venv = REPO_ROOT / "venv"
    if (dev_venv / "Scripts" / "vllm.exe").exists():
        return dev_venv, dev_venv / "Scripts" / "vllm.exe"
    embedded = REPO_ROOT / "python"
    return embedded, embedded / "Scripts" / "vllm.exe"


VENV, VLLM_EXE = _resolve_vllm_exe()

MODEL_PATH = os.environ.get(
    "VLLM_MODEL_DIR",
    str(REPO_ROOT / "models" / "Qwen3.6-27B-int4-AutoRound"),
)


def _find_vcvars() -> str:
    env = os.environ.get("VLLM_WINDOWS_VCVARS")
    if env and Path(env).exists():
        return env
    candidates = [
        r"C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvars64.bat",
        r"C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat",
        r"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat",
        r"C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat",
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    return candidates[2]  # community is the most common — return so caller can warn


VCVARS = _find_vcvars()

# vswhere.exe lives under the VS Installer dir, NOT on PATH by default.
# vcvars64.bat shells out to vswhere.exe with no path qualifier, so without
# this prefix the snapshot logs start with a scary
# `'vswhere.exe' is not recognized as an internal or external command` line
# even though vcvars then falls through to a working VS install.
VS_INSTALLER_DIR = r"C:\Program Files (x86)\Microsoft Visual Studio\Installer"


def msvc_env() -> dict:
    """Capture env vars set by vcvars64.bat so FlashInfer's ninja+cl.exe JIT works.

    Without this, fp8 KV hits a FileNotFoundError when FlashInfer tries to
    compile a new prefill kernel at first request.
    """
    if not Path(VCVARS).exists():
        print(f"[warn] vcvars64.bat not found at {VCVARS} - FlashInfer JIT may fail.")
        return {}
    path_prefix = f'set "PATH={VS_INSTALLER_DIR};%PATH%" && ' if Path(VS_INSTALLER_DIR).is_dir() else ""
    out = subprocess.check_output(
        f'cmd /S /C "{path_prefix}"{VCVARS}" && set"',
        text=True, errors="replace",
    )
    env = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            env[k] = v
    return env

def _resolve_logs_dir() -> Path:
    """Return a writable logs dir.

    Honors $VLLM_WINDOWS_LOGS if set. Otherwise tries repo_root/logs, and
    falls back to %LocalAppData%\\qwen36-windows-server\\logs when the
    repo root is read-only (e.g. installs under Program Files).
    """
    env = os.environ.get("VLLM_WINDOWS_LOGS")
    if env:
        d = Path(env)
        d.mkdir(parents=True, exist_ok=True)
        return d
    candidate = REPO_ROOT / "logs"
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        probe = candidate / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return candidate
    except OSError:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        d = Path(base) / "qwen36-windows-server" / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return d


LOGS_DIR = _resolve_logs_dir()


def log_path_for(port: int) -> Path:
    return LOGS_DIR / f"vllm_server.{port}.log"


# Path to the vendored Qwen3.5 enhanced jinja chat template. Lives under
# the vllm-windows repo (next to the patched wheel source). End-user
# portable installs symlink/copy it into ${VLLM_WINDOWS_TEMPLATES} so
# launcher zips can stand alone.
def enhanced_jinja_path() -> Path:
    env = os.environ.get("VLLM_WINDOWS_ENHANCED_JINJA")
    if env and Path(env).exists():
        return Path(env)
    candidates = [
        REPO_ROOT / "templates" / "qwen3.5-enhanced.jinja",
        REPO_ROOT.parent / "vllm-windows" / "templates" / "qwen3.5-enhanced.jinja",
    ]
    for p in candidates:
        if p.exists():
            return p
    # Last resort — return the most likely portable layout (launcher next
    # to vllm-windows). Caller will print an error if it doesn't exist.
    return candidates[0]
