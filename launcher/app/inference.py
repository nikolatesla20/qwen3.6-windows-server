from __future__ import annotations
import json
import time
from typing import Callable, Optional
import httpx


BENCH_PROMPT = (
    "Write a 300-word plain-text explanation of how transformer attention "
    "works. No lists, no code, no markdown. Single flowing prose."
)


def test_chat(
    port: int,
    model: str = "any",
    timeout: float = 180.0,
    host: str = "127.0.0.1",
    prompt: str = BENCH_PROMPT,
    max_tokens: int = 300,
    on_progress: Optional[Callable[[int], None]] = None,
) -> dict:
    """Stream a benchmark-quality chat completion and return TTFT / decode tok/s.

    Mirrors windows_tools/bench.py so the TUI Test button gives the same
    apples-to-apples number as running `python windows_tools/bench.py` from
    the command line. on_progress(n) is called periodically with the count
    of decoded chunks so the caller can update a status toast.
    """
    url = f"http://{host}:{port}/v1/chat/completions"
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    text_chunks: list[str] = []
    completion_tokens = 0
    prompt_tokens = 0
    n_chunks = 0
    last_progress = 0.0
    t0 = time.perf_counter()
    t_first = None
    try:
        with httpx.stream("POST", url, json=body, timeout=timeout) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload.strip() == "[DONE]":
                    break
                try:
                    obj = json.loads(payload)
                except Exception:
                    continue
                if obj.get("usage"):
                    completion_tokens = obj["usage"].get("completion_tokens", completion_tokens)
                    prompt_tokens = obj["usage"].get("prompt_tokens", prompt_tokens)
                for ch in obj.get("choices", []) or []:
                    delta_obj = ch.get("delta", {}) or {}
                    delta = (
                        delta_obj.get("content")
                        or delta_obj.get("reasoning")
                        or delta_obj.get("reasoning_content")
                        or ""
                    )
                    if delta:
                        if t_first is None:
                            t_first = time.perf_counter()
                        text_chunks.append(delta)
                        n_chunks += 1
                        if on_progress is not None:
                            now = time.perf_counter()
                            if now - last_progress > 0.5:
                                last_progress = now
                                try:
                                    on_progress(n_chunks)
                                except Exception:
                                    pass
        t_end = time.perf_counter()
    except Exception as e:
        return {"ok": False, "error": str(e)}

    elapsed = t_end - t0
    decode_window = (t_end - t_first) if t_first else elapsed
    text = "".join(text_chunks)
    completion_tokens = completion_tokens or n_chunks
    decode_tps = (completion_tokens / decode_window) if (completion_tokens and decode_window > 0) else 0.0
    wall_tps = (completion_tokens / elapsed) if (completion_tokens and elapsed > 0) else 0.0
    return {
        "ok": True,
        "text": text,
        "completion_tokens": completion_tokens,
        "prompt_tokens": prompt_tokens,
        "decode_tps": decode_tps,
        "wall_tps": wall_tps,
        "ttft_s": (t_first - t0) if t_first else None,
        "decode_window_s": decode_window if t_first else None,
        "total_s": elapsed,
    }
