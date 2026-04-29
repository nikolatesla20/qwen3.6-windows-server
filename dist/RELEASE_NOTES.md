Portable Windows launcher for Qwen3.6-27B inference. Unzip, double-click `start.bat`, you're serving on `http://127.0.0.1:5001/v1`.

## What's in the zip

- Embedded Python 3.12.7 with textual / rich / httpx / pyyaml preinstalled
- Patched vLLM wheel (`0.19.0+devnen.<N>`) bundled under `wheels/`
- 12 validated snapshot configs:
  - `start_72tps` — **~72 tok/s** short-prompt baseline (~200-token chat, 32 k ctx, MTP n=3)
  - `start_speed` — **64.5 tok/s** long-prompt default (~100 KB / ~24 k-token Python source, 90 k ctx, MTP n=6)
  - `start_127k` — 53.4 tok/s, max context on a single 3090
  - `start_mtp4` — 58.3 tok/s, mid-balance speed vs context
  - `start_pp2_160k` — 43.5 tok/s on **2× 3090 PP=2**, 160 k context
  - plus `start_gpu0_50k` and short-prompt variants (full table in the README)
- Helper tools: `bench`, `bench_summarize`, `check_coherence`, `verify_install`, `patch_tokenizer`, `probe_max_ctx`
- Full docs: HARDWARE / COHERENCE / TUNING / TROUBLESHOOTING / MTP_HEAD

## Install

1. Download `qwen3.6-windows-server-portable-x64.zip`.
2. Verify SHA256 (recommended — see below).
3. Extract anywhere — no admin needed.
4. Drop your Qwen3.6-27B INT4 weights into `models\Qwen3.6-27B-int4-AutoRound\`, or set `VLLM_MODEL_DIR`.
5. Double-click `start.bat`.

## SHA256

```
cda7bed6be1ddd6fc47c65e143ba6b7d6d1b8768e552430deddc54fbb02d9c58  qwen3.6-windows-server-portable-x64.zip
```

PowerShell: `Get-FileHash qwen3.6-windows-server-portable-x64.zip -Algorithm SHA256 | Format-List`.

## Tested on

Windows 10 Enterprise 22H2, 2x RTX 3090. Should work on any Ampere/Ada/Blackwell NVIDIA + Windows 10/11. See [`docs/HARDWARE.md`](https://github.com/devnen/qwen3.6-windows-server/blob/main/docs/HARDWARE.md).

## License

Apache-2.0. No telemetry. No analytics. No phone-home. Everything runs on your machine.
