# qwen3.6-windows-server

> **One-click [Qwen3.6-27B](https://huggingface.co/Qwen) inference on Windows.**
> Unzip, double-click, you're serving on `http://127.0.0.1:5001/v1`.
> No WSL, no Docker, no conda, no pip, no admin. **Everything runs on
> your machine. No telemetry. No analytics. No phone-home.**

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Made for Windows](https://img.shields.io/badge/OS-Windows%2010%2F11-0078d6.svg)](https://www.microsoft.com/windows)
[![GPU](https://img.shields.io/badge/tested-RTX%203090-76b900.svg)](https://www.nvidia.com/)
[![Local AI](https://img.shields.io/badge/100%25-local%20%2F%20offline-success.svg)](#the-local-ai-ethos)

---

## What this is

A small portable Windows app that gives you an OpenAI-compatible API
serving Qwen3.6-27B locally, with config presets that I actually
measured myself. The launcher is a Textual TUI: arrow keys, Enter
to start a snapshot, Esc to stop. That's the whole UX.

It is the matching launcher for the [`devnen/vllm-windows`](https://github.com/devnen/vllm-windows)
patched wheel, but you don't need to know or care about that. The wheel
ships inside the launcher zip.

## What you get

On a single RTX 3090 (24 GB), running [Lorbus AutoRound INT4](https://huggingface.co/Lorbus/Qwen3.6-27B-int4-AutoRound):

Every snapshot below has the tool-calling fix baked in (PR #35687 + #40861 + `qwen3.5-enhanced.jinja` + `preserve_thinking=false`), so any one of them works with any OpenAI-compatible client, Cline, Cursor, Codex CLI, Continue, LM Studio, OpenWebUI, etc. Just point it at the listed port.

| Snapshot              | Decode tok/s | Prompt class      | Context | Use it when |
|-----------------------|--------------|-------------------|---------|-------------|
| `start_72tps`         | **~72**      | short (~200 tok)  | 32 k    | Short-prompt / chat baseline. MTP n=3. |
| `start_speed`         | **64.5**     | long (100 KB)     | 90 k    | Default for long prompts. MTP n=6, see note below. |
| `start_127k`          | 53.4         | long (100 KB)     | 127 k   | Maximum context on a single 3090. |
| `start_mtp4`          | 58.3         | long (100 KB)     | 120 k   | Mid-balance speed vs context. |
| `start_pp2_160k` (2 GPU) | 43.5      | long (100 KB)     | 160 k   | Pipeline-parallel for the largest contexts. |
| `start_gpu0_50k`      | volatile     | mixed             | 9–50 k  | Single-GPU, monitor plugged into the same card. |

> **GPU index note.** `start_72tps`, `start_speed`, `start_127k`, and
> `start_mtp4` pin to **GPU 1** so GPU 0 stays free for the desktop
> compositor and other apps on a 2× 3090 box. On a single-GPU host the
> snapshot detects that via `nvidia-smi` and falls back to GPU 0 with a
> warning, but for a tuned single-GPU run use `start_gpu0_50k` directly.
> `start_pp2_160k` requires two GPUs.

Long-prompt rows were measured on a ~100 KB / ~24 k-token Python
source-summary prompt (a real Windows-service module fed to
`windows_tools\bench_summarize.py`). The short-prompt row was measured
on a ~200-token chat turn via `windows_tools\bench.py`. All numbers
[coherence-validated](docs/COHERENCE.md), TPS without coherence is a
lie.

> **Why MTP n=6 on `start_speed`?** n=3 is the universal *short-prompt*
> sweet spot and ships as `start_72tps`. On long, dense Python source
> the acceptance curve shifts later, n=6 won my coherence sweep
> (n=3 / 4 / 5 / 6 / 7 / 8 → 53.4 / 58.3 / 62.8 / 64.5 / 61.5 / 58.0
> tok/s; full sweep in [`docs/TUNING.md`](docs/TUNING.md)). Always
> re-sweep on a representative prompt for your workload.

> **Honest framing:** these are not r/LocalLLaMA records. Community has
> hit 80–82 tok/s on a 3090 with TurboQuant 3-bit KV, and 160 tok/s on a
> 5090. The unique angle here is **native Windows, no WSL**. Same
> recipe, no virtualization tax, one community member measured the
> same hardware going from **85 tok/s in WSL to 160 tok/s in native
> Ubuntu** ([reported here](https://www.reddit.com/r/LocalLLaMA/comments/1sw21op/comment/oid8d9n/)).
> This launcher closes that gap on Windows.

## Why this exists

Most fast Qwen3.6-27B recipes on r/LocalLLaMA assume Linux + Docker, or
Linux-in-WSL. Windows users either pay the WSL tax, dual-boot, or skip
inference entirely. None of those is great if your daily driver is
Windows.

This launcher is the third option:

- **Native Windows.** Runs as a normal Windows process. No virtualization layer.
- **Portable.** Unzip the launcher, drop your model into a folder, double-click. That's it.
- **Validated.** Every config in here was measured against a coherence battery before being checked in. No copy-pasted Reddit recipes that look fast but emit `* * * *`.
- **Local-only.** No outbound calls except when you explicitly ask the launcher to download a model from HuggingFace. No telemetry of any kind, ever.

## Install

**TL;DR for CI / agents / scripted installs**, one line, no TUI:

```powershell
start.bat --auto-download --snapshot start_72tps
```

That installs the runtime, downloads the model if missing, and starts
serving on `http://127.0.0.1:5001/v1`. See
[Headless / scripted install](#headless--scripted-install) below for
all the flags.

**Hand the install to a coding agent**, copy/paste prompt at
[`docs/AGENT_INSTALL_PROMPT.md`](docs/AGENT_INSTALL_PROMPT.md). Edit the
one `INSTALL_DIR` line, paste into Claude Code / Cursor / Codex CLI /
any agent with shell access, and it does the download + extract +
runtime install + model fetch + smoke test end-to-end while you do
something else.

**Interactive path:**

1. Download [`qwen3.6-windows-server-portable-x64.zip`](../../releases/latest)
   from the latest Release. Extract anywhere (no admin needed).
2. Double-click `start.bat`. The first run does two one-time steps,
   then drops you in the TUI:
   - **Runtime install** (~5–15 min, several GB). The bundled vLLM
     wheel + ~150 transitive deps (torch, CUDA wheels, transformers,
     etc.) install into the embedded Python's `site-packages`. A
     marker file is written so subsequent launches skip this entirely.
   - **Model setup.** Looks for `Qwen3.6-27B-int4-AutoRound` weights
     on your fixed drives (scans `<drive>:\`, `_models\`, `models\`,
     `AI\`, `AI\models\`, `huggingface\`, `huggingface\hub\`,
     `models\Lorbus\`). If it doesn't find them, offers to
     **auto-download from Hugging Face** (~16 GB, public, no token)
     or accepts a path to weights you already have. If your weights
     live somewhere else, pass `--model-dir <path>` to skip the scan.
3. Pick a snapshot, press Enter, you're serving on
   `http://127.0.0.1:5001/v1`.

The portable zip ships with an embedded Python 3.12 runtime, the
patched vLLM wheel, the launcher TUI, a portable Windows Terminal,
and a vendored `get-pip.py`. No conda, no system-Python install, no
registry changes, no admin prompts. The runtime install on first run
is the only network-dependent step besides the model download.

Don't have the model yet? See [`docs/MTP_HEAD.md`](docs/MTP_HEAD.md),
**use the Lorbus AutoRound quant**, the others won't draft.

Detailed install (including the wheel-only path for users who already
have their own venv): [`docs/INSTALL.md`](docs/INSTALL.md).

## Test it

Once the server is up:

```powershell
curl http://127.0.0.1:5001/v1/chat/completions ^
  -H "Content-Type: application/json" ^
  -d "{\"model\":\"any\",\"messages\":[{\"role\":\"user\",\"content\":\"Capital of France?\"}],\"max_tokens\":2000}"
```

Note the `"model": "any"`, the patched wheel accepts any value. You
don't have to know what the model is called.

> **Why `max_tokens: 2000`?** Qwen3.6 is a thinking model: it spends the
> first chunk of its budget reasoning inside `<think>...</think>` and
> only then writes the answer to `content`. With `max_tokens: 50` the
> entire budget gets eaten by the thinking phase and you'll see
> `content: null` plus `finish_reason: "length"`, the server is fine,
> the budget was just too small. 1500–2000 is a safe floor for short Q&A.

> **Where's the answer in the response?** The final answer lands in
> `choices[0].message.content`. The chain-of-thought lands in a separate
> `choices[0].message.reasoning` field, that's the `--reasoning-parser=qwen3`
> wheel patch doing its job, not a bug. Most chat clients show
> `content` and ignore `reasoning`; if yours doesn't, point it at
> `content`.

> **If the request hangs**, tail `logs\vllm_server.<port>.log` for vLLM's
> own stdout, the parent launcher logs only the boot banner; the
> serving process tees its progress to that file.

## Headless / scripted install

End-to-end automated install (no TUI, no prompts), useful for CI,
remote machines, agent installers, or just keeping a repeatable
recipe:

```powershell
start.bat --auto-download --snapshot start_72tps
```

The launcher runs the first-run setup (vLLM wheel + ~150 deps),
auto-downloads the Lorbus quant from Hugging Face if it's missing,
applies the tokenizer patch automatically, and execs the chosen
snapshot, all without opening the TUI. Other useful flags:

```powershell
start.bat --model-dir G:\_models\Qwen3.6-27B-int4-AutoRound --snapshot start_speed
start.bat --headless     :: skip TUI, run the default snapshot (start_72tps)
start.bat --setup-only   :: install runtime + model, then exit (no serving)
```

`--headless` without `--snapshot` now runs the default snapshot
(`start_72tps`) instead of exiting after setup checks. To run only
the setup checks (the old `--headless` behavior), pass `--setup-only`.

The launcher also stays in the parent terminal, instead of detaching
into a new Windows Terminal window, when it sees any of `WT_SESSION`,
`VLLM_NO_WT`, `CI`, `GITHUB_ACTIONS`, `MSYSTEM`, or `TERM` in the
environment. That covers GitHub Actions, git-bash, MSYS, agent
runners, and anything that exports `TERM`. So your captured stdout
won't go missing.

For benchmark numbers like the table above, use the bundled tools:

```powershell
windows_tools\bench.bat              :: short prompt, decode-only TPS
windows_tools\bench_summarize.bat    :: ~100 KB / ~24 k-token prompt, prefill + decode + KV
windows_tools\check_coherence.bat    :: 3-tier coherence validator
```

## Hardware reality

Tuned and measured on:

- Windows 10 Enterprise 22H2
- 2× NVIDIA RTX 3090 (Ampere `sm_86`), no NVLink, PCIe Gen 4
- 350 W power cap (250 W also benchmarked, see [`docs/TUNING.md`](docs/TUNING.md))

Should also work on any Ampere or newer NVIDIA GPU running Windows 10/11,
3090, 4090, 5090, A6000, etc. **Will not work** on Pascal, Turing,
Intel Arc, or any AMD card. **Single GPU with the display attached**
loses 1–3 GiB of VRAM to the desktop compositor and another 2–5 GiB to
running apps; use the `start_gpu0_50k` snapshot, and read
[`docs/WINDOWS_VRAM_HEADLESS.md`](docs/WINDOWS_VRAM_HEADLESS.md) for the
free-up-VRAM playbook.

If you're on a 4090 or 5090, expect higher numbers than mine. If you're
on something more exotic, nothing here is going to work without your own
tuning, that's fine, please share what you find.

## The local-AI ethos

Everything runs on your machine. No telemetry. No analytics. No
phone-home. No cloud inference. No model weights downloaded behind your
back. The launcher never opens an outbound connection except when you
explicitly ask it to (downloading a model from HuggingFace via your own
browser/`huggingface-cli`). This is in the spirit of
[r/LocalLLaMA](https://www.reddit.com/r/LocalLLaMA/): your hardware,
your weights, your prompts, your business.

The launcher and every script are Apache-2.0. The bundled wheel inherits
upstream vLLM's Apache-2.0 license. SHA256 of every release asset is
published next to the release, verify before extracting.

## What's under the hood

The wheel that powers this launcher is
[`devnen/vllm-windows`](https://github.com/devnen/vllm-windows): a
patched native-Windows build of [vLLM](https://github.com/vllm-project/vllm),
with three Windows-specific fixes (CPU-relay for Gloo collectives, Qwen3
reasoning-parser fix mirrored from PR #35687, hardwired wildcard model
name). The full diff is at
[`CHANGES_VS_SYSTEMPANIC.md`](https://github.com/devnen/vllm-windows/blob/main/CHANGES_VS_SYSTEMPANIC.md)
in that repo. You don't have to download it separately, it's bundled
inside this launcher's portable zip.

## Documentation

- [`docs/INSTALL.md`](docs/INSTALL.md), full install + the bring-your-own-venv path.
- [`docs/CLAUDE_CODE.md`](docs/CLAUDE_CODE.md), point Claude Code at the local server (native `/v1/messages`, no proxy).
- [`docs/UNINSTALL.md`](docs/UNINSTALL.md), clean removal (it's portable, so just delete folders).
- [`docs/HARDWARE.md`](docs/HARDWARE.md), what works, what doesn't, and why.
- [`docs/COHERENCE.md`](docs/COHERENCE.md), degenerate-output guide and the 3-tier validator.
- [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md), every failure mode I've hit.
- [`docs/TUNING.md`](docs/TUNING.md), the lever set, anti-levers, how to sweep your own configs.
- [`docs/MTP_HEAD.md`](docs/MTP_HEAD.md), why Lorbus AutoRound is the only INT4 quant that works.
- [`docs/SPEC_DECODE_MATRIX.md`](docs/SPEC_DECODE_MATRIX.md), what spec-decode + parallelism combos work.
- [`docs/WINDOWS_VRAM_HEADLESS.md`](docs/WINDOWS_VRAM_HEADLESS.md), free VRAM on Windows for single-GPU.
- [`docs/HALLUCINATED_FLAGS.md`](docs/HALLUCINATED_FLAGS.md), flags from web search results that don't exist on this wheel.
- [`docs/CREDITS.md`](docs/CREDITS.md), vLLM team, SystemPanic, Lorbus, the community.

## Contributing

Bug reports welcome, please include GPU model, driver version, Windows
build, and the relevant slice of `logs\vllm_server.<port>.log`. The
[issue template](.github/ISSUE_TEMPLATE/bug_report.md) walks you
through it.

This project is intentionally narrow scope: **Windows + Ampere/Ada/Blackwell
NVIDIA + Qwen3.6-27B**. PRs that extend it to other Qwen-class models on the
same hardware (Qwen3-Next, Qwen3.5) are welcome. PRs that extend it to
other operating systems or other GPU vendors are politely out of scope,
please go upstream.

## Credits

- [vLLM](https://github.com/vllm-project/vllm), the engine.
- [SystemPanic/vllm-windows](https://github.com/SystemPanic/vllm-windows), the upstream Windows wheel build infrastructure.
- [Lorbus](https://huggingface.co/Lorbus), the AutoRound INT4 quant of Qwen3.6-27B that makes any of this fast.
- [r/LocalLLaMA](https://www.reddit.com/r/LocalLLaMA/), the configs in here started from recipes posted on the subreddit, and got refined by the honest feedback in the comments.
