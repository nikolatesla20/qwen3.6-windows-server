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
3. Extract anywhere — no admin needed, **including `Program Files` / `Program Files (x86)`**.
4. Double-click `start.bat`. On first run the launcher auto-discovers existing weights or offers to download Lorbus/Qwen3.6-27B-int4-AutoRound from Hugging Face (~16 GB, public, no token).

## What's new in v0.1.3

- **First-run runtime installer.** The portable zip ships the launcher, the patched vLLM wheel (~200 MB), a vendored `get-pip.py`, and an embedded Python — but NOT the ~6 GB of transitive deps (torch + CUDA wheels + ~150 Python packages). On first launch, `setup.py` bootstraps pip, then installs the bundled wheel + deps into the embedded Python's `site-packages`. One-time, ~5–15 min, several-GB download. A marker file makes subsequent launches no-ops. Honest scope: previous releases claimed "every dependency preinstalled" — that wasn't true and pressing Enter on a snapshot would crash with `ModuleNotFoundError: vllm`.
- **Snapshot scripts now find the embedded Python.** `_common.py` resolves `VLLM_EXE` to `<install>\python\Scripts\vllm.exe` when no developer venv is present. Each `start_*.bat` falls back to `..\python\python.exe` when `..\venv\` doesn't exist.
- **WT relaunch fixed for installs under `Program Files (x86)`.** `start.bat` now matches the working `portable-launcher` pattern (delayed expansion + triple-quote `cmd /c` + `activate_wt.py` foreground bring-up + `ShowWindow(0)` to hide the parent cmd). The previous space-padded form interacted badly with parens in the install path.
- **Bundled jinja chat template.** `templates/qwen3.5-enhanced.jinja` now ships in the zip — earlier builds shipped only when paired with the `vllm-windows` repo checkout.
- **Removed the `start_toolcall` snapshot + harness.** Every snapshot now ships with the tool-calling fix baked in (`qwen3.5-enhanced.jinja` + `preserve_thinking=false`), so a separate config is redundant.

## What's new in v0.1.2

- **Bundled Windows Terminal.** A portable Windows Terminal is shipped under `terminal/` and `start.bat` automatically launches the TUI inside it — no separate install required, no Microsoft Store, works on Windows 10. Falls back gracefully to plain `cmd` if the bundle is missing.

## What's new in v0.1.1

- **Truly portable.** The launcher now works from any path including `Program Files (x86)` (parens-safe `start.bat`, embedded-Python `_pth` correctly wired).
- **Auto-discover model.** Checks env var → saved config → install/models → drive scan; only prompts when nothing is found.
- **Auto-download.** When prompted, the launcher can fetch the Lorbus quant directly from Hugging Face using only stdlib `urllib` — no token, no `huggingface_hub` install needed. Resume-safe.
- **Writable-path fallback.** When the install dir is read-only (e.g. real `Program Files`), logs / downloaded models / saved config auto-route to `%LocalAppData%\qwen36-windows-server\`.
- **Visible errors.** A failure during startup no longer just flashes the cmd window and closes — the error stays on screen with a `Press a key` prompt.

## SHA256

See `SHA256SUMS.txt` in this release.

PowerShell: `Get-FileHash qwen3.6-windows-server-portable-x64.zip -Algorithm SHA256 | Format-List`.

## Tested on

Windows 10 Enterprise 22H2, 2x RTX 3090. Should work on any Ampere/Ada/Blackwell NVIDIA + Windows 10/11. See [`docs/HARDWARE.md`](https://github.com/devnen/qwen3.6-windows-server/blob/main/docs/HARDWARE.md).

## License

Apache-2.0. No telemetry. No analytics. No phone-home. Everything runs on your machine.
