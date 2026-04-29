"""Tool-calling-fixed snapshot for Qwen3.6-27B (Lorbus AutoRound INT4).

Pairs the patched vllm-windows venv (PR #35687 + PR #40861 backports applied,
see windows_patches/) with the canonical Qwen 3.6 agentic recipe:

  - chat-template = qwen3.5-enhanced.jinja  (vendored at templates/)
  - tool-call-parser = qwen3_coder          (XML parser fails on unclosed <think>)
  - reasoning-parser = qwen3
  - preserve_thinking = false               (mandatory; true breaks enhanced.jinja)
  - MTP n=3                                 (short-prompt sweet spot, agentic loops are short)
  - GPU1 only, TP=1 PP=1, ctx 64k           (room for an agentic chain plus tool outputs)

Port 5005 (5001=speed, 5002=pp2, 5003=draft reserved, 5004=luce-dflash).
Request-side, clients should use temperature ~0.1 — the default 0.7-0.9
wrecks tool calling on Qwen 3.6.
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
from _common import (
    VENV, VLLM_EXE, MODEL_PATH, VCVARS, log_path_for, enhanced_jinja_path,
)

SERVED_NAME = "qwen3.6-27b-toolcall"
HOST = "0.0.0.0"
PORT = 5005

TP = 1
PP = 1
USE_MTP = True
NUM_SPEC_TOKENS = 3

CTX = 64000
GPU_MEM_UTIL = 0.948
KV_CACHE_DTYPE = "fp8_e4m3"
MAX_NUM_BATCHED_TOKENS = 4128

ENFORCE_EAGER = False
ENABLE_VISION = False


def msvc_env() -> dict:
    if not Path(VCVARS).exists():
        print(f"[warn] vcvars64.bat not found at {VCVARS} — FlashInfer JIT may fail.")
        return {}
    out = subprocess.check_output(
        f'cmd /S /C ""{VCVARS}" && set"', text=True, errors="replace",
    )
    env = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            env[k] = v
    return env


def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect((host if host != "0.0.0.0" else "127.0.0.1", port))
            return True
        except OSError:
            return False


def main() -> int:
    if not VLLM_EXE.exists():
        print(f"[ERROR] vllm.exe not found at {VLLM_EXE}", file=sys.stderr)
        return 1
    if not Path(MODEL_PATH).exists():
        print(f"[ERROR] Model dir not found: {MODEL_PATH}", file=sys.stderr)
        return 1
    template = enhanced_jinja_path()
    if not template.exists():
        print(f"[ERROR] enhanced jinja template not found: {template}\n"
              f"        Set VLLM_WINDOWS_ENHANCED_JINJA or copy it into "
              f"{HERE.parent / 'templates'}.", file=sys.stderr)
        return 1
    if port_in_use(HOST, PORT):
        print(f"[ERROR] Port {PORT} already in use.", file=sys.stderr)
        return 1

    env = os.environ.copy()
    env.update(msvc_env())
    _world = TP * PP
    env["CUDA_VISIBLE_DEVICES"] = "0,1" if _world > 1 else "1"
    env["VLLM_SLEEP_WHEN_IDLE"] = "1"
    env["VLLM_ENABLE_CUDAGRAPH_GC"] = "1"
    env["VLLM_USE_FLASHINFER_SAMPLER"] = "1"
    env["VLLM_ALLOW_LONG_MAX_MODEL_LEN"] = "1"
    env["VLLM_MARLIN_USE_ATOMIC_ADD"] = "1"
    env["RAY_memory_monitor_refresh_ms"] = "0"
    env["OMP_NUM_THREADS"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["VLLM_ATTENTION_BACKEND"] = "TRITON_ATTN"
    env["USE_LIBUV"] = "0"
    env["TORCH_NCCL_ASYNC_ERROR_HANDLING"] = "0"
    env["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
    env["NCCL_ASYNC_ERROR_HANDLING"] = "0"
    env["PYTHONFAULTHANDLER"] = "1"

    args = [
        str(VLLM_EXE), "serve", MODEL_PATH,
        f"--served-model-name={SERVED_NAME}",
        "--quantization=auto-round",
        f"--max-model-len={CTX}",
        "--max-num-seqs=1",
        f"--max-num-batched-tokens={MAX_NUM_BATCHED_TOKENS}",
        "--block-size=32",
        "--enable-prefix-caching",
        "--enable-chunked-prefill",
        "--enable-auto-tool-choice",
        "--tool-call-parser=qwen3_coder",
        "--reasoning-parser=qwen3",
        f"--chat-template={template}",
        '--default-chat-template-kwargs={"preserve_thinking": false}',
        f"--kv-cache-dtype={KV_CACHE_DTYPE}",
        f"--tensor-parallel-size={TP}",
        f"--pipeline-parallel-size={PP}",
        f"--gpu-memory-utilization={GPU_MEM_UTIL}",
        "--trust-remote-code",
        "--attention-backend=TRITON_ATTN",
        "--no-use-tqdm-on-load",
        f"--host={HOST}",
        f"--port={PORT}",
    ]
    if ENFORCE_EAGER:
        args.append("--enforce-eager")
    if not ENABLE_VISION:
        args.append('--limit-mm-per-prompt={"image":0,"video":0}')
    if USE_MTP:
        args.append(
            f'--speculative-config={{"method":"mtp","num_speculative_tokens":{NUM_SPEC_TOKENS}}}'
        )

    print("=" * 60)
    print(f"vLLM serve: {SERVED_NAME}  (tool-calling snapshot)")
    print(f"  Template: {template.name}  (preserve_thinking=false)")
    print(f"  Parser  : qwen3_coder + qwen3 reasoning")
    print(f"  Ctx     : {CTX}  |  TP: {TP}  |  PP: {PP}  |  MTP n={NUM_SPEC_TOKENS}")
    print(f"  Listen  : http://{HOST}:{PORT}")
    print("=" * 60)
    print(" ".join(args))
    print("=" * 60, flush=True)

    log_path = log_path_for(PORT)
    log_f = open(log_path, "w", encoding="utf-8", buffering=1)
    print(f"[launcher] tee stdout -> {log_path}")
    proc = subprocess.Popen(
        args, env=env, cwd=str(VENV),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1,
        text=True, encoding="utf-8", errors="replace",
    )

    import threading
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    def _tee():
        assert proc.stdout is not None
        for line in proc.stdout:
            try:
                sys.stdout.write(line)
                sys.stdout.flush()
            except Exception:
                pass
            log_f.write(line)
    threading.Thread(target=_tee, daemon=True).start()

    def _forward(sig, _frame):
        proc.send_signal(signal.SIGTERM)
    signal.signal(signal.SIGINT, _forward)
    signal.signal(signal.SIGTERM, _forward)

    try:
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        return proc.wait()


if __name__ == "__main__":
    raise SystemExit(main())
