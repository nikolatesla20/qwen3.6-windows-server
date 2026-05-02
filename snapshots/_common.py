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
import sys
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


def _count_visible_gpus() -> int:
    """Count NVIDIA GPUs reported by nvidia-smi.

    Returns 0 when nvidia-smi is missing or fails — caller should treat
    that as 'unknown, don't second-guess the snapshot defaults'.
    """
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            text=True, stderr=subprocess.DEVNULL, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return 0
    return sum(1 for line in out.splitlines() if line.strip())


def resolve_cuda_visible_devices(preferred_single: str, world_size: int) -> str:
    """Pick CUDA_VISIBLE_DEVICES with a one-GPU fallback.

    The 2× 3090 snapshots default to pinning the single-card path to GPU 1
    so GPU 0 stays free for the display compositor and other work. On a
    single-GPU box (or any host where nvidia-smi reports fewer GPUs than
    the snapshot expects), that pin is wrong and vLLM dies with no useful
    error. Detect that case and fall back to GPU 0 with a loud log line.

    Args:
        preferred_single: ``CUDA_VISIBLE_DEVICES`` value the snapshot
            wants when running TP=PP=1 (usually ``"1"`` or ``"0"``).
        world_size: TP * PP. Multi-GPU snapshots want ``"0,1"``.
    """
    visible = _count_visible_gpus()
    if world_size > 1:
        if visible and visible < world_size:
            print(
                f"[warn] snapshot wants {world_size} GPUs but nvidia-smi "
                f"reports {visible}. Pick a single-GPU snapshot "
                f"(start_72tps / start_gpu0_50k) instead.",
                file=sys.stderr,
            )
        return ",".join(str(i) for i in range(max(world_size, 1)))
    try:
        wanted_idx = int(preferred_single.split(",")[0])
    except ValueError:
        wanted_idx = 0
    if visible and wanted_idx >= visible:
        print(
            f"[warn] snapshot prefers GPU {wanted_idx} but only {visible} "
            f"GPU(s) visible — falling back to GPU 0. For dedicated "
            f"single-GPU tuning see start_gpu0_50k.",
            file=sys.stderr,
        )
        return "0"
    return preferred_single


def msvc_env() -> dict:
    """Capture env vars set by vcvars64.bat so FlashInfer's ninja+cl.exe JIT works.

    Without this, fp8 KV hits a FileNotFoundError when FlashInfer tries to
    compile a new prefill kernel at first request. Best-effort: shipped
    snapshots use TRITON_ATTN, not FlashInfer JIT, so failure here is a
    warning, not a fatal error.
    """
    if not Path(VCVARS).exists():
        print(f"[warn] vcvars64.bat not found at {VCVARS} - FlashInfer JIT may fail.")
        return {}
    path_prefix = f'set "PATH={VS_INSTALLER_DIR};%PATH%" && ' if Path(VS_INSTALLER_DIR).is_dir() else ""
    try:
        out = subprocess.check_output(
            f'cmd /S /C "{path_prefix}"{VCVARS}" && set"',
            text=True, errors="replace", stderr=subprocess.STDOUT,
        )
    except (subprocess.CalledProcessError, OSError) as e:
        print(
            f"[warn] vcvars64.bat invocation failed ({e.__class__.__name__}); "
            f"continuing without MSVC env. TRITON_ATTN snapshots are unaffected; "
            f"FlashInfer JIT (if used) may fail at first request.",
            file=sys.stderr,
        )
        return {}
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
