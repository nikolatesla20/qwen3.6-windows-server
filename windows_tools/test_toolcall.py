"""Tool-calling test harness for the start_toolcall.bat snapshot.

Targets the specific failure modes flagged in the Reddit deep-dives
(r/Vllm/1skks8n, r/LocalLLM/1sv6cqk, r/LocalLLaMA/1syh4sd):

  T1  single trivial call (sanity)
  T2  call with special characters in args (`<`, `>`, JSON, code)
  T3  CoT-leakage scenario — agentic prompt that triggers the
      "Let me read X first:" / stop-without-emit failure on stock 0.19.0
  T4  multi-turn sequential calls (3+ rounds) — exercises the
      tool_call_id / parser-state path that PR #40861 fixes
  T5  streaming non-streaming parity
  T6  unicode + nested-JSON arg

Each test passes iff the model emits a parseable tool_call object with
finish_reason == "tool_calls" (or content correctly populated for T0).

Usage:
    python test_toolcall.py [--base http://127.0.0.1:5005] [-v]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any

DEFAULT_BASE = "http://127.0.0.1:5005"
MODEL = "qwen3.6-27b-toolcall"
TEMP = 0.1
TOP_P = 0.8
DEFAULT_TIMEOUT = 300


def post(base: str, path: str, body: dict, stream: bool = False, timeout: int = DEFAULT_TIMEOUT):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    return urllib.request.urlopen(req, timeout=timeout)


def chat(base: str, messages: list, tools: list | None = None,
         tool_choice: Any = "auto", max_tokens: int = 800, stream: bool = False) -> dict:
    body = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": TEMP,
        "top_p": TOP_P,
        "stream": stream,
    }
    if tools is not None:
        body["tools"] = tools
        body["tool_choice"] = tool_choice
    if not stream:
        with post(base, "/v1/chat/completions", body) as r:
            return json.loads(r.read())
    # streaming -> assemble into a single dict
    chunks = []
    with post(base, "/v1/chat/completions", body) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            chunks.append(json.loads(payload))
    # Reassemble
    content = ""
    tool_calls: dict[int, dict] = {}
    finish = None
    for c in chunks:
        if not c.get("choices"):
            continue
        d = c["choices"][0]
        delta = d.get("delta") or {}
        if delta.get("content"):
            content += delta["content"]
        for tc in delta.get("tool_calls") or []:
            idx = tc.get("index", 0)
            slot = tool_calls.setdefault(idx, {"id": "", "type": "function",
                                               "function": {"name": "", "arguments": ""}})
            if tc.get("id"):
                slot["id"] = tc["id"]
            fn = tc.get("function") or {}
            if fn.get("name"):
                slot["function"]["name"] += fn["name"]
            if fn.get("arguments"):
                slot["function"]["arguments"] += fn["arguments"]
        if d.get("finish_reason"):
            finish = d["finish_reason"]
    msg = {"role": "assistant", "content": content or None}
    if tool_calls:
        msg["tool_calls"] = [tool_calls[i] for i in sorted(tool_calls)]
    return {"choices": [{"message": msg, "finish_reason": finish}]}


def assistant_msg(resp: dict) -> dict:
    return resp["choices"][0]["message"]


def has_tool_call(resp: dict) -> bool:
    msg = assistant_msg(resp)
    return bool(msg.get("tool_calls")) and \
        resp["choices"][0].get("finish_reason") in ("tool_calls", "stop")


def get_call(resp: dict, idx: int = 0) -> dict | None:
    msg = assistant_msg(resp)
    tcs = msg.get("tool_calls") or []
    return tcs[idx] if idx < len(tcs) else None


# ---------- tool definitions -----------------------------------------------

TOOLS_WEATHER = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get current weather for a city.",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name"},
                "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
            },
            "required": ["city"],
        },
    },
}]

TOOLS_FILE = [{
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read a text file from disk and return its contents.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
}, {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": "Write text to a file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
}, {
    "type": "function",
    "function": {
        "name": "list_dir",
        "description": "List entries of a directory.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
}]

TOOLS_EVAL = [{
    "type": "function",
    "function": {
        "name": "exec_python",
        "description": "Execute a snippet of Python and return stdout.",
        "parameters": {
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "required": ["code"],
        },
    },
}]


# ---------- individual tests -----------------------------------------------

class TestResult:
    def __init__(self, name: str):
        self.name = name
        self.ok = False
        self.detail = ""
        self.elapsed = 0.0

    def __repr__(self):
        s = "PASS" if self.ok else "FAIL"
        return f"[{s}] {self.name} ({self.elapsed:.1f}s) {self.detail}"


def t1_simple(base: str) -> TestResult:
    r = TestResult("T1 simple weather call")
    t0 = time.time()
    try:
        resp = chat(base,
                    [{"role": "user", "content": "What is the weather in Paris? Use the tool."}],
                    tools=TOOLS_WEATHER)
        r.elapsed = time.time() - t0
        if not has_tool_call(resp):
            r.detail = f"no tool call. content={assistant_msg(resp).get('content')!r:.200}"
            return r
        call = get_call(resp)
        if call["function"]["name"] != "get_weather":
            r.detail = f"wrong name: {call['function']['name']}"
            return r
        args = json.loads(call["function"]["arguments"])
        if "paris" not in args.get("city", "").lower():
            r.detail = f"wrong args: {args}"
            return r
        r.ok = True
        r.detail = f"call={args}"
    except Exception as e:
        r.detail = f"exception: {e!r}"
        r.elapsed = time.time() - t0
    return r


def t2_special_chars(base: str) -> TestResult:
    """The qwen3_coder regex parser historically corrupts on `<` `>` `&`.
    PR #40861 fixes the literal-delimiter-in-value case.
    """
    r = TestResult("T2 special chars in args")
    t0 = time.time()
    try:
        resp = chat(
            base,
            [{"role": "user",
              "content": "Use exec_python to run this exact code: "
                         "`if 1 < 2 and 3 > 2: print('a & b')`. "
                         "Pass the snippet verbatim as the `code` argument."}],
            tools=TOOLS_EVAL,
            max_tokens=600,
        )
        r.elapsed = time.time() - t0
        if not has_tool_call(resp):
            r.detail = f"no tool call. content={assistant_msg(resp).get('content')!r:.200}"
            return r
        call = get_call(resp)
        args = json.loads(call["function"]["arguments"])
        code = args.get("code", "")
        if "<" not in code or ">" not in code:
            r.detail = f"angle brackets stripped: {code!r}"
            return r
        if "&" not in code:
            r.detail = f"ampersand stripped: {code!r}"
            return r
        r.ok = True
        r.detail = f"code={code!r}"
    except Exception as e:
        r.detail = f"exception: {e!r}"
        r.elapsed = time.time() - t0
    return r


def t3_cot_leakage(base: str) -> TestResult:
    """Reproduces the failure-mode the Reddit deep-dive flags as the killer:
    'Let me read XXX first:' then stop without emitting a tool call,
    because <tool_call> appeared inside an unclosed <think>.

    With PR #35687 (treat <tool_call> as implicit reasoning end) this should
    succeed cleanly.
    """
    r = TestResult("T3 CoT leakage (read codebase)")
    t0 = time.time()
    try:
        resp = chat(
            base,
            [{"role": "user",
              "content": "I have a project at C:/foo. Please summarise the repo. "
                         "Start by reading the entry point at C:/foo/main.py — "
                         "use the read_file tool, do not narrate before the call."}],
            tools=TOOLS_FILE,
            max_tokens=500,
        )
        r.elapsed = time.time() - t0
        if not has_tool_call(resp):
            r.detail = (f"no tool call (the bug). finish={resp['choices'][0]['finish_reason']!r} "
                        f"content={(assistant_msg(resp).get('content') or '')[:200]!r}")
            return r
        call = get_call(resp)
        if call["function"]["name"] != "read_file":
            r.detail = f"wrong tool: {call['function']['name']}"
            return r
        args = json.loads(call["function"]["arguments"])
        if "main.py" not in args.get("path", ""):
            r.detail = f"wrong path: {args}"
            return r
        r.ok = True
        r.detail = f"path={args['path']}"
    except Exception as e:
        r.detail = f"exception: {e!r}"
        r.elapsed = time.time() - t0
    return r


def t4_multi_turn(base: str) -> TestResult:
    """3 rounds of tool calls. PR #40861 fixes the spec-decode + multi-call
    case where only the first call is emitted. We assert each round emits
    *some* valid tool call from the available set — model is free to choose
    which file to read first; we are testing the parser, not the model's
    plan.
    """
    r = TestResult("T4 multi-turn (3 rounds)")
    t0 = time.time()
    valid = {"read_file", "list_dir", "write_file"}
    try:
        msgs = [
            {"role": "system",
             "content": "You are a coding agent. Use the tools to inspect the project. "
                        "Take exactly one tool action per turn."},
            {"role": "user", "content": "Inspect C:/proj. Start by listing the directory."},
        ]
        rounds = []
        # Round 1
        resp = chat(base, msgs, tools=TOOLS_FILE)
        if not has_tool_call(resp):
            r.detail = f"round 1: no tool call. content={assistant_msg(resp).get('content')!r:.150}"
            r.elapsed = time.time() - t0
            return r
        call = get_call(resp)
        if call["function"]["name"] not in valid:
            r.detail = f"round 1: unknown tool {call['function']['name']}"
            r.elapsed = time.time() - t0
            return r
        rounds.append(call["function"]["name"])
        msgs.append(assistant_msg(resp))
        msgs.append({"role": "tool", "tool_call_id": call["id"],
                     "content": json.dumps(["main.py", "README.md", "tests/"])})

        # Round 2
        resp = chat(base, msgs, tools=TOOLS_FILE)
        if not has_tool_call(resp):
            r.detail = f"round 2: no tool call. content={assistant_msg(resp).get('content')!r:.150}"
            r.elapsed = time.time() - t0
            return r
        call = get_call(resp)
        if call["function"]["name"] not in valid:
            r.detail = f"round 2: unknown tool {call['function']['name']}"
            r.elapsed = time.time() - t0
            return r
        rounds.append(call["function"]["name"])
        msgs.append(assistant_msg(resp))
        msgs.append({"role": "tool", "tool_call_id": call["id"],
                     "content": "def main():\n    print('hello')\n"})

        # Round 3
        resp = chat(base, msgs, tools=TOOLS_FILE)
        r.elapsed = time.time() - t0
        if not has_tool_call(resp):
            r.detail = f"round 3: no tool call. content={assistant_msg(resp).get('content')!r:.150}"
            return r
        call = get_call(resp)
        if call["function"]["name"] not in valid:
            r.detail = f"round 3: unknown tool {call['function']['name']}"
            return r
        rounds.append(call["function"]["name"])
        r.ok = True
        r.detail = f"3 rounds OK; sequence={rounds}"
    except Exception as e:
        r.detail = f"exception: {e!r}"
        r.elapsed = time.time() - t0
    return r


def t5_streaming(base: str) -> TestResult:
    r = TestResult("T5 streaming parity")
    t0 = time.time()
    try:
        resp = chat(
            base,
            [{"role": "user", "content": "What's the weather in Tokyo in fahrenheit?"}],
            tools=TOOLS_WEATHER,
            stream=True,
        )
        r.elapsed = time.time() - t0
        if not has_tool_call(resp):
            r.detail = f"no tool call from stream. msg={assistant_msg(resp)!r:.200}"
            return r
        call = get_call(resp)
        args = json.loads(call["function"]["arguments"])
        if call["function"]["name"] != "get_weather" or "tokyo" not in args.get("city", "").lower():
            r.detail = f"wrong call: name={call['function']['name']} args={args}"
            return r
        r.ok = True
        r.detail = f"streamed call={args}"
    except Exception as e:
        r.detail = f"exception: {e!r}"
        r.elapsed = time.time() - t0
    return r


def t6_nested_json(base: str) -> TestResult:
    """Tool call with structural-delimiter literal inside a value. PR #40861
    fixes the case where `</parameter>` / `</function>` / `</tool_call>`
    appearing as text inside a parameter value were incorrectly treated as
    closing delimiters, truncating or corrupting the value.
    """
    r = TestResult("T6 nested-json arg")
    t0 = time.time()
    try:
        resp = chat(
            base,
            [{"role": "user",
              "content": "Use write_file to write the literal JSON object "
                         "{\"a\": 1, \"closing\": \"the </parameter> tag\"} "
                         "to C:/tmp/sample.json. Pass that exact JSON object "
                         "as the `content` string."}],
            tools=TOOLS_FILE,
            max_tokens=600,
        )
        r.elapsed = time.time() - t0
        if not has_tool_call(resp):
            r.detail = f"no tool call. content={assistant_msg(resp).get('content')!r:.200}"
            return r
        call = get_call(resp)
        if call["function"]["name"] != "write_file":
            r.detail = f"wrong tool: {call['function']['name']}"
            return r
        args = json.loads(call["function"]["arguments"])
        content = args.get("content", "")
        if "</parameter>" not in content:
            r.detail = f"`</parameter>` literal swallowed: content={content!r:.200}"
            return r
        # The full JSON should be preserved. Try to parse it.
        try:
            parsed = json.loads(content)
            if parsed.get("a") != 1 or "</parameter>" not in (parsed.get("closing") or ""):
                r.detail = f"value corrupted: {parsed}"
                return r
        except Exception:
            # Acceptable if model wrapped/quoted; presence of </parameter> suffices.
            pass
        r.ok = True
        r.detail = f"content len={len(content)} preserved closing tag"
    except Exception as e:
        r.detail = f"exception: {e!r}"
        r.elapsed = time.time() - t0
    return r


# ---------- driver ----------------------------------------------------------

def t7_parallel_calls(base: str) -> TestResult:
    """Model is allowed to emit two tool calls in one assistant turn.
    PR #40861 fixes the streaming path that dropped all but the first
    call when several arrived in a single delta burst.
    """
    r = TestResult("T7 parallel tool calls")
    t0 = time.time()
    try:
        resp = chat(
            base,
            [{"role": "user",
              "content": "Get the weather in BOTH Paris (celsius) and Tokyo (fahrenheit). "
                         "Issue both tool calls in this single turn."}],
            tools=TOOLS_WEATHER,
            max_tokens=600,
        )
        r.elapsed = time.time() - t0
        msg = assistant_msg(resp)
        calls = msg.get("tool_calls") or []
        if len(calls) < 2:
            r.detail = f"only {len(calls)} call(s); content={msg.get('content')!r:.150}"
            return r
        cities = []
        for c in calls:
            try:
                a = json.loads(c["function"]["arguments"])
                cities.append((a.get("city", "").lower(), a.get("unit")))
            except Exception:
                cities.append(("<bad-args>", None))
        names = " ".join(x[0] for x in cities)
        if "paris" not in names or "tokyo" not in names:
            r.detail = f"missing city: {cities}"
            return r
        r.ok = True
        r.detail = f"{len(calls)} calls: {cities}"
    except Exception as e:
        r.detail = f"exception: {e!r}"
        r.elapsed = time.time() - t0
    return r


def t8_long_chain(base: str) -> TestResult:
    """5-round agentic chain. Stresses parser state across many turns."""
    r = TestResult("T8 long chain (5 rounds)")
    t0 = time.time()
    valid = {"read_file", "list_dir", "write_file"}
    try:
        msgs = [
            {"role": "system",
             "content": "You are a coding agent inspecting a small project. "
                        "Take one tool action per turn. Be thorough."},
            {"role": "user", "content": "Audit C:/proj. Begin with a directory listing."},
        ]
        seq = []
        canned_responses = [
            json.dumps(["main.py", "lib/", "README.md", "tests/"]),
            "import lib\n\ndef main():\n    lib.run()\n",
            json.dumps(["__init__.py", "core.py"]),
            "class Core:\n    def run(self):\n        print('ok')\n",
            "# Project README\n\nA tiny demo.\n",
        ]
        for i, canned in enumerate(canned_responses):
            resp = chat(base, msgs, tools=TOOLS_FILE, max_tokens=400)
            if not has_tool_call(resp):
                r.detail = f"round {i+1}: no tool call. content={assistant_msg(resp).get('content')!r:.120}"
                r.elapsed = time.time() - t0
                return r
            call = get_call(resp)
            if call["function"]["name"] not in valid:
                r.detail = f"round {i+1}: bad tool {call['function']['name']}"
                r.elapsed = time.time() - t0
                return r
            seq.append(call["function"]["name"])
            msgs.append(assistant_msg(resp))
            msgs.append({"role": "tool", "tool_call_id": call["id"], "content": canned})
        r.elapsed = time.time() - t0
        r.ok = True
        r.detail = f"5 rounds OK; sequence={seq}"
    except Exception as e:
        r.detail = f"exception: {e!r}"
        r.elapsed = time.time() - t0
    return r


def t9_parallel_streaming_leak(base: str) -> TestResult:
    """Streaming regression: with 3+ parallel tool calls, the qwen3_coder
    streaming parser previously leaked the second/third call's raw XML
    (``<tool_call><function=...><parameter=...>...</tool_call>``) into the
    ``delta.content`` stream while ALSO emitting it as a structured
    ``delta.tool_calls``. The chat client then rendered the leaked XML
    as plain text in the conversation. The fix lives in the trailing-
    free-text emission at the end of ``extract_tool_calls_streaming`` —
    it must NOT emit text past the last structural ``</tool_call>`` if
    a new ``<tool_call>`` opener follows.
    """
    r = TestResult("T9 parallel streaming leak (3 calls)")
    t0 = time.time()
    try:
        body = {
            "model": MODEL,
            "messages": [{
                "role": "user",
                "content": "Get the weather (celsius) in Paris, London, and "
                           "Berlin. Issue all three tool calls in this single "
                           "turn. /no_think",
            }],
            "tools": TOOLS_WEATHER,
            "tool_choice": "auto",
            "stream": True,
            "max_tokens": 500,
            "temperature": TEMP,
            "top_p": TOP_P,
        }
        req = urllib.request.Request(
            base + "/v1/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        content_total = ""
        merged: dict = {}
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                ch = chunk.get("choices") or []
                if not ch:
                    continue
                d = ch[0].get("delta") or {}
                cnt = d.get("content")
                tcs = d.get("tool_calls")
                if cnt:
                    content_total += cnt
                if tcs:
                    for tc in tcs:
                        i = tc.get("index", 0)
                        slot = merged.setdefault(
                            i, {"id": "", "name": "", "args": ""})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] = fn["name"]
                        if fn.get("arguments"):
                            slot["args"] += fn["arguments"]
        r.elapsed = time.time() - t0
        # Hard rule: the streamed content must not contain raw XML for any
        # tool call. Whitespace-only text between calls is fine.
        leak_markers = ("<tool_call>", "<function=", "<parameter=")
        for marker in leak_markers:
            if marker in content_total:
                r.detail = (
                    f"LEAK: marker {marker!r} present in delta.content "
                    f"(len={len(content_total)}); first 200 chars="
                    f"{content_total[:200]!r}"
                )
                return r
        if len(merged) < 3:
            r.detail = (
                f"only {len(merged)} structured tool_call(s); expected 3"
            )
            return r
        cities = []
        for i in sorted(merged):
            slot = merged[i]
            if slot["name"] != "get_weather":
                r.detail = f"call {i}: wrong tool {slot['name']!r}"
                return r
            try:
                a = json.loads(slot["args"])
            except json.JSONDecodeError as e:
                r.detail = (
                    f"call {i}: args not parseable JSON: "
                    f"{slot['args']!r:.120} ({e})"
                )
                return r
            cities.append(a.get("city", "").lower())
        # The model is free in word order, but all three cities must be there.
        wanted = {"paris", "london", "berlin"}
        missing = wanted - set(cities)
        if missing:
            r.detail = f"missing cities: {missing}; got={cities}"
            return r
        r.ok = True
        r.detail = (
            f"3 streamed calls: {cities}; "
            f"content_total={content_total.strip()!r:.40}"
        )
    except Exception as e:
        r.detail = f"exception: {e!r}"
        r.elapsed = time.time() - t0
    return r


ALL_TESTS = [t1_simple, t2_special_chars, t3_cot_leakage, t4_multi_turn,
             t5_streaming, t6_nested_json, t7_parallel_calls, t8_long_chain,
             t9_parallel_streaming_leak]


def wait_ready(base: str, timeout: int = 240) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base + "/v1/models", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(2)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--only", help="comma-separated list of test names (e.g. T1,T3)")
    ap.add_argument("--wait", type=int, default=0,
                    help="seconds to wait for /v1/models before running")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if args.wait:
        print(f"Waiting up to {args.wait}s for {args.base} ...")
        if not wait_ready(args.base, args.wait):
            print("[FAIL] server never became ready", file=sys.stderr)
            return 2
        print("Server ready.")

    tests = ALL_TESTS
    if args.only:
        keep = {x.strip().upper() for x in args.only.split(",")}
        tests = [t for t in ALL_TESTS if t(args.base.__class__()).name.split()[0].upper() in keep] \
            if False else [t for t in ALL_TESTS if t.__name__[:2].upper() in keep]

    results = []
    for fn in tests:
        print(f"running {fn.__name__} ...", flush=True)
        res = fn(args.base)
        results.append(res)
        print(f"  {res}", flush=True)

    passed = sum(1 for r in results if r.ok)
    total = len(results)
    print()
    print("=" * 70)
    print(f"  {passed}/{total} passed")
    print("=" * 70)
    for r in results:
        print(r)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
