"""Pre-TUI model discovery and download.

Runs in the parent cmd window before Textual mounts. Prints plain text
so any error is visible (no flashing-and-closing window failure mode).

Discovery order:
  1. $VLLM_MODEL_DIR — explicit override, wins.
  2. user_config.json saved path from a previous run.
  3. <writable_root>\\models\\Qwen3.6-27B-int4-AutoRound (default location).
  4. Quick scan of fixed drives for a folder of that name.

If nothing is found, prompts the user:
  [1] enter a custom path
  [2] auto-download from Hugging Face (~16 GB, public, no token needed)
  [q] quit

Auto-download uses stdlib urllib only — no huggingface_hub dependency.
The Lorbus repo is public so the resolve URLs work anonymously.
"""
from __future__ import annotations

import json
import os
import string
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable

from . import paths

REPO_ID = paths.DEFAULT_MODEL_REPO
HF_API_TREE = f"https://huggingface.co/api/models/{REPO_ID}/tree/main?recursive=1"
HF_RESOLVE_TMPL = f"https://huggingface.co/{REPO_ID}/resolve/main/{{path}}"


# ---------------------------------------------------------------- discovery


def _scan_fixed_drives() -> list[Path]:
    """Look for a `Qwen3.6-27B-int4-AutoRound` folder on the obvious places.

    Cheap: only checks <drive>:\\ and <drive>:\\_models\\ — does not walk
    full trees. Designed to find the folder a user already has from a
    previous download without lighting the disk on fire.
    """
    hits: list[Path] = []
    target = paths.DEFAULT_MODEL_DIRNAME
    candidates: list[Path] = []
    for letter in string.ascii_uppercase:
        root = Path(f"{letter}:\\")
        if not root.exists():
            continue
        candidates.append(root / target)
        candidates.append(root / "_models" / target)
        candidates.append(root / "models" / target)
        candidates.append(root / "AI" / target)
    for c in candidates:
        try:
            if paths.looks_like_model_dir(c):
                hits.append(c)
        except OSError:
            pass
    return hits


def _discover() -> Path | None:
    env = os.environ.get("VLLM_MODEL_DIR")
    if env:
        p = Path(env)
        if paths.looks_like_model_dir(p):
            return p
    cfg = paths.load_user_config()
    saved = cfg.get("model_dir")
    if saved:
        p = Path(saved)
        if paths.looks_like_model_dir(p):
            return p
    default = paths.default_model_dir()
    if paths.looks_like_model_dir(default):
        return default
    hits = _scan_fixed_drives()
    if len(hits) == 1:
        return hits[0]
    return None


# ---------------------------------------------------------------- download


def _http_get_json(url: str, timeout: float = 30.0) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": "qwen36-launcher/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _list_repo_files() -> list[dict]:
    """Return [{path, size}, ...] for every blob in the repo at main."""
    data = _http_get_json(HF_API_TREE)
    if not isinstance(data, list):
        raise RuntimeError(f"unexpected HF API response: {type(data).__name__}")
    out: list[dict] = []
    for entry in data:
        if entry.get("type") != "file":
            continue
        path = entry.get("path")
        size = entry.get("size") or (entry.get("lfs") or {}).get("size") or 0
        if path:
            out.append({"path": path, "size": int(size)})
    return out


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024:
            return f"{n:.2f} {unit}"
        n /= 1024.0
    return f"{n:.2f} PiB"


def _download_one(rel_path: str, dest: Path, expected_size: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and expected_size and dest.stat().st_size == expected_size:
        print(f"  [skip] {rel_path}  ({_fmt_bytes(expected_size)} already present)")
        return
    url = HF_RESOLVE_TMPL.format(path=rel_path)
    tmp = dest.with_suffix(dest.suffix + ".part")
    if tmp.exists():
        tmp.unlink()
    req = urllib.request.Request(url, headers={"User-Agent": "qwen36-launcher/1.0"})
    started = time.time()
    last_print = 0.0
    bytes_done = 0
    try:
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as fh:
            total = int(r.headers.get("Content-Length") or expected_size or 0)
            chunk = 1024 * 1024  # 1 MiB
            while True:
                buf = r.read(chunk)
                if not buf:
                    break
                fh.write(buf)
                bytes_done += len(buf)
                now = time.time()
                if now - last_print >= 0.5 or (total and bytes_done == total):
                    pct = (bytes_done * 100 / total) if total else 0
                    elapsed = max(now - started, 1e-3)
                    rate = bytes_done / elapsed
                    bar_w = 30
                    fill = int(bar_w * pct / 100) if total else 0
                    bar = "#" * fill + "." * (bar_w - fill)
                    sys.stdout.write(
                        f"\r  {rel_path[:40]:40s} [{bar}] {pct:5.1f}%  "
                        f"{_fmt_bytes(bytes_done)} / {_fmt_bytes(total)}  "
                        f"{_fmt_bytes(int(rate))}/s        "
                    )
                    sys.stdout.flush()
                    last_print = now
        sys.stdout.write("\n")
        sys.stdout.flush()
        tmp.replace(dest)
    except (urllib.error.URLError, OSError) as e:
        if tmp.exists():
            try: tmp.unlink()
            except OSError: pass
        raise RuntimeError(f"download failed for {rel_path}: {e}") from e


def _download_repo(dest_root: Path) -> None:
    print(f"\nFetching file list from huggingface.co/{REPO_ID} ...")
    files = _list_repo_files()
    total_bytes = sum(f["size"] for f in files)
    print(f"  {len(files)} files, ~{_fmt_bytes(total_bytes)} total\n")
    print(f"Destination: {dest_root}")
    print("Downloading. Resumable: a re-run will skip files already present at the right size.\n")
    dest_root.mkdir(parents=True, exist_ok=True)
    for i, f in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {f['path']}  ({_fmt_bytes(f['size'])})")
        _download_one(f["path"], dest_root / f["path"], f["size"])
    print("\nAll files downloaded.")


# ---------------------------------------------------------------- prompt


def _print_banner() -> None:
    print("=" * 70)
    print(" qwen3.6-windows-server — first-run model setup")
    print("=" * 70)
    install = paths.install_root()
    writable = paths.writable_root()
    print(f"  install root:    {install}")
    print(f"  writable root:   {writable}")
    if writable != install:
        print(f"  (install is read-only; logs/downloads go to writable root)")
    print()


def _prompt_choice(extra_hits: list[Path]) -> tuple[str, Path | None]:
    """Returns (action, path) where action ∈ {'use','download','quit'}."""
    print("No valid Qwen3.6-27B-int4-AutoRound model directory was found.")
    print()
    if extra_hits:
        print("Possible candidates detected on your drives:")
        for i, h in enumerate(extra_hits, 1):
            print(f"  [{i}] {h}")
        print()
    print("Options:")
    print("  [1]  Enter a path to an existing model directory")
    print("  [2]  Download Lorbus/Qwen3.6-27B-int4-AutoRound from Hugging Face (~16 GB)")
    if extra_hits:
        print("  [3]  Use one of the candidates listed above")
    print("  [q]  Quit")
    print()
    while True:
        choice = input("Choice: ").strip().lower()
        if choice == "q":
            return ("quit", None)
        if choice == "1":
            raw = input("Full path to model directory: ").strip().strip('"')
            if not raw:
                continue
            p = Path(raw)
            if not paths.looks_like_model_dir(p):
                print(f"  ✗ {p} does not look like a model dir (need config.json + .safetensors).")
                continue
            return ("use", p)
        if choice == "2":
            return ("download", paths.download_target_dir())
        if choice == "3" and extra_hits:
            if len(extra_hits) == 1:
                return ("use", extra_hits[0])
            try:
                n = int(input(f"Which candidate (1-{len(extra_hits)})? ").strip())
                if 1 <= n <= len(extra_hits):
                    return ("use", extra_hits[n - 1])
            except ValueError:
                pass
            continue


# ---------------------------------------------------------------- entrypoint


def ensure_model() -> Path:
    """Block until a usable model dir is identified. Sets VLLM_MODEL_DIR.

    Persists the resolved path to user_config.json so subsequent launches
    skip the prompt entirely.
    """
    found = _discover()
    if found is not None:
        os.environ["VLLM_MODEL_DIR"] = str(found)
        cfg = paths.load_user_config()
        if cfg.get("model_dir") != str(found):
            cfg["model_dir"] = str(found)
            paths.save_user_config(cfg)
        return found

    _print_banner()
    hits = _scan_fixed_drives()
    while True:
        action, path = _prompt_choice(hits)
        if action == "quit":
            print("\nAborted.")
            sys.exit(0)
        if action == "use" and path is not None:
            os.environ["VLLM_MODEL_DIR"] = str(path)
            cfg = paths.load_user_config()
            cfg["model_dir"] = str(path)
            paths.save_user_config(cfg)
            print(f"\n✓ Using model at: {path}\n")
            return path
        if action == "download" and path is not None:
            try:
                _download_repo(path)
            except Exception as e:  # noqa: BLE001
                print(f"\n✗ Download failed: {e}")
                print("You can retry, enter a path manually, or quit.")
                continue
            if not paths.looks_like_model_dir(path):
                print(f"\n✗ Download finished but {path} still doesn't look like a model dir.")
                continue
            os.environ["VLLM_MODEL_DIR"] = str(path)
            cfg = paths.load_user_config()
            cfg["model_dir"] = str(path)
            paths.save_user_config(cfg)
            print(f"\n✓ Model ready at: {path}\n")
            return path
