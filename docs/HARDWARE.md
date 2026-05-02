# Hardware reality

Honest answers about what works on what.

## Tested

- Windows 10 Enterprise 22H2, 19044.x
- 2× NVIDIA RTX 3090, 24 GB each, Ampere sm_86, no NVLink, PCIe Gen 4 ×16
- Power cap up to 350 W per card (250 W also benchmarked, see TUNING.md)
- 256 GB DDR4 (model weights stream from disk, RAM hardly matters)
- Models live on a separate NVMe; no measurable load-time difference vs system disk

## Should work, untested

- RTX 4090 / 4080 (Ada, sm_89), same code path; expect higher numbers
- Single 3090 / 4090, but see the display-attached caveat below
- A6000 / A40 / data-centre Ampere, in theory; nobody has tested

## RTX 50-series (Blackwell, sm_120), not in the current wheel

The bundled wheel is `vllm-0.19.0+devnen.1`, built against CUDA 12.6 and
PyTorch 2.11.0+cu126. That torch build only ships kernels up to sm_90,
so on RTX 5060 / 5070 / 5080 / 5090 the engine fails at boot with
`cudaErrorNoKernelImageForDevice` on the first `torch.zeros` call.
Confirmed on a 5070 + 5060 setup by a community member.

This is a wheel issue, not a code issue. SystemPanic shipped
`vllm-windows v0.20.0` on 2026-04-30 (CUDA 13, Ampere + Blackwell, NCCL
TP/PP on Windows). The devnen patches need to be rebased onto that
release before this launcher can ship a 50-series build. Tracked as a
separate branch.

In the meantime, two working alternatives:

- WSL2 + Docker, see jaMMint's
  [vllm-blackwell-guide](https://github.com/lastloop-ai/vllm-blackwell-guide).
  Reports up to 120 tok/s on 27B and 200 tok/s on the 35B MoE on a
  5090. Pays the WSL tax (see below) but works today.
- Wait for the Blackwell branch of this project to ship.

Independent of the wheel, AutoRound INT4 has a known Marlin bug on
sm_120 (`scalar_types.int4` not in the supported list). The reported
workaround is exporting in AWQ format, which Lorbus's release does not
provide. Even with a CUDA 13 wheel this may be the next wall.

## Probably won't work without effort

- Windows Server (no Windows Terminal by default, TUI works in cmd but is uglier)
- Pascal / Turing GPUs, sm_86 minimum. Pascal lacks BF16 in hardware
  (the Lorbus AutoRound MTP head is BF16, won't load) and INT4 Marlin
  kernels need compute capability 8.0 or higher. The wheel itself
  may build kernels for older arches but TRITON_ATTN code paths
  haven't been validated.
- WSL2, works in principle (you'd just install upstream vLLM there) but
  pays a real virtualisation tax. One community member measured the
  same hardware at **85 tok/s in WSL vs 160 tok/s in native Ubuntu**
  ([reported here](https://www.reddit.com/r/LocalLLaMA/comments/1sw21op/comment/oid8d9n/)).
  Updating WSL to 2.7.3 closes some of the gap (115 vs 160) but not
  all. WSL2 runs on Hyper-V (Type-1), CUDA goes through GPU-PV
  paravirtualisation, the Windows host driver still owns the GPU and
  DWM keeps its allocation. Use native Linux if you have the option.
- Hyper-V / DDA passthrough into a Linux VM, not tested; if you do, please
  open an issue with your numbers

## Will not work

- AMD GPUs (RX 6000/7000/9000, Instinct), vLLM ROCm path doesn't ship in
  this Windows wheel. Use upstream vLLM on Linux.
- Intel Arc / Battlemage, same.
- Apple Silicon, wrong universe; use mlx-lm.
- 16 GB cards (RTX 4060 Ti 16G, 5060 Ti 16G), Qwen3.6-27B INT4 weights
  alone are 16.96 GiB; you'd need a smaller model. Try Qwen3-14B or
  smaller variants.

## Mixed-card multi-GPU (PP=2)

PP splits transformer layers evenly across the two cards, so the
**smaller card sets the upper bound** for half the model plus
activations and KV cache. Worked example: a 4080 Super (16 GB) plus
3060 (12 GB) cannot fit Qwen3.6-27B because the 3060 side has roughly
8.5 GiB of weights to hold, plus activations, plus enough KV for any
useful context. Expect small context, no MTP (PP+MTP is broken on this
wheel), and roughly 30 to 40 tok/s decode if it boots at all.

Often it is better to run a smaller model on the larger card alone
than to split 27B unevenly. Mixed-arch combos (Ada + Ampere, Blackwell
+ Blackwell) are theoretically fine for PP but untested. Always boot
single-card first to confirm the wheel loads, then add the second.

## How to read the headline tok/s numbers

The 64.5 and 72 tok/s figures are **single-card decode**. The model and
KV cache live entirely on one 3090. The reason there are two cards in
the reference rig is the Windows display tax, the second card is for
the desktop. With one 3090 driving your monitor you get the same decode
numbers, just with less context room (use `start_gpu0_50k` for that
case, expect 9 to 50 k context depending on what is open).

The only snapshot that actually uses both GPUs for inference is
`start_pp2_160k` (43.5 tok/s, 160 k context).

## The Windows desktop VRAM tax

The GPU that drives your monitor loses **1–3 GiB** to the Windows desktop
compositor (DWM) before any app is open. Common apps eat more:

| Workload | Extra VRAM |
|---|---|
| Single 1440p SDR monitor, idle desktop | ~0.6–1.0 GiB |
| Dual 4K HDR monitors | ~1.5–2.5 GiB |
| Chrome (10 tabs, HW accel on) | +0.3–0.7 GiB |
| Microsoft Teams, Discord, Outlook | +0.4–1.0 GiB combined |
| dbForge / heavy IDE | +0.5–1.5 GiB |
| 4K YouTube playing | +1.0–1.5 GiB |
| Realistic "office workload" total | ~3–5 GiB |
| Heavy: + 4K media + Snagit | ~5–7 GiB |

So a 24 GiB card with the display attached and a typical workload has
~17–20 GiB *actually free* for vLLM, not 24. Qwen3.6-27B INT4 weights are
16.96 GiB, plus ~5 GiB of activations, plus you want some KV pool, the
math breaks at 24 GiB.

**The default snapshots assume your inference card is display-free.** They
pin `CUDA_VISIBLE_DEVICES=1` and use `--gpu-memory-utilization=0.948`. If
you only have one GPU, those will OOM. Use [`start_gpu0_50k`](../snapshots/start_gpu0_50k.py)
which is conservative (lower mem-util, smaller MNBT, modest ctx) and
expect 9–50 k of usable context depending on what's open.

For permanent VRAM relief on a single-GPU system, see
[`WINDOWS_VRAM_HEADLESS.md`](WINDOWS_VRAM_HEADLESS.md). Short version:
plug a $30 GT 1030 into your monitor, leave the 3090 compute-only.
Or on Intel desktop CPUs, route the display to the iGPU.

## GPU0 vs GPU1 (dual-GPU systems)

If you have two cards and one drives the display:

- **GPU0** (display), display tax applies. Use `mem_util ≤ 0.92`.
- **GPU1** (no display), full ~22.76 GiB free after CUDA context init.
  Default snapshots use `mem_util = 0.948` here; 0.95 trips vLLM's safety
  check by ~40 MiB.

The `start_*` snapshots (other than `pp2`) all pin GPU1. If your headless
card is GPU0 instead, edit the snapshot's `CUDA_VISIBLE_DEVICES`
assignment, or set the `CUDA_VISIBLE_DEVICES` env var before launching.

## Power cap

We measured 250 W → 350 W on these cards:
- Prefill: 845 → 983 tok/s (+16 %)
- Decode: unchanged (decode is memory-bandwidth-bound at batch=1)

Default snapshots assume 350 W. Set with `nvidia-smi -pl 350`. **Don't
exceed your PSU's headroom**, two 3090s at 350 W draw ~750 W from the
12V rails alone before CPU and the rest. We're using a 1300 W Gold PSU.

## Tensor vs pipeline parallelism

- **TP=2 on Windows: don't.** Even with the CPU-relay patch, allreduce
  fires every transformer layer and dominates the per-token cost (~7.5
  tok/s on Qwen3.6-27B). PP=2 is far better.
- **PP=2: usable for big context.** ~43 tok/s, ctx up to 160 k. The
  hidden-state hand-off is the only thing crossing CPU per layer.
- **TP=1: the throughput champion** when one card is enough. MTP works.
  64.5 tok/s on the recommended `start_speed` snapshot.

You cannot have MTP and PP at the same time on this wheel, see
[`SPEC_DECODE_MATRIX.md`](SPEC_DECODE_MATRIX.md).
