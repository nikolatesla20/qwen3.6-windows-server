Portable Windows launcher for Qwen3.6-27B inference. Unzip, double-click `start.bat`, you're serving on `http://127.0.0.1:5001/v1`.

## What's in the zip

- Embedded Python 3.12.7 with textual / rich / httpx / pyyaml preinstalled
- Patched vLLM wheel (`0.19.0+devnen.<N>`) bundled under `wheels/`
- 12 validated snapshot configs (`start_speed` 64.5 tok/s, `start_127k` 53.4, etc.)
- Helper tools: `bench`, `check_coherence`, `verify_install`, `patch_tokenizer`, `probe_max_ctx`
- Full docs: HARDWARE / COHERENCE / TUNING / TROUBLESHOOTING / MTP_HEAD

## Install

1. Download `qwen3.6-windows-server-portable-x64.zip`.
2. Verify `SHA256SUMS.txt` (optional).
3. Extract anywhere — no admin needed.
4. Drop your Qwen3.6-27B INT4 weights into `models\Qwen3.6-27B-int4-AutoRound\`, or set `VLLM_MODEL_DIR`.
5. Double-click `start.bat`.

## Tested on

Windows 10 Enterprise 22H2, 2x RTX 3090. Should work on any Ampere/Ada/Blackwell NVIDIA + Windows 10/11. See [`docs/HARDWARE.md`](https://github.com/devnen/qwen3.6-windows-server/blob/main/docs/HARDWARE.md).

## License

Apache-2.0. No telemetry. No analytics. No phone-home. Everything runs on your machine.
