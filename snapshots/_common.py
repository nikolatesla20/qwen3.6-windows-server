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
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

VENV = Path(os.environ.get("VLLM_WINDOWS_VENV", str(REPO_ROOT / "venv")))
VLLM_EXE = VENV / "Scripts" / "vllm.exe"

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
