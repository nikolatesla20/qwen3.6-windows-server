# Using OpenAI Codex CLI with this server

Codex CLI is finickier than Claude Code, Cline, or OpenCode against
this server, for one specific reason: Codex talks to OpenAI's
**Responses API** (`/v1/responses`) rather than the older Chat
Completions API (`/v1/chat/completions`). The bundled vLLM wheel
implements both endpoints, but the Responses API sends a `developer`
role for system-tier instructions that the shipped Qwen3 chat
template does not recognise.

If you do not specifically want Codex CLI, the easier path is one of
these clients, all of which work with this server out of the box:

- Claude Code: see [`CLAUDE_CODE.md`](CLAUDE_CODE.md).
- OpenCode, Cline, Cursor, Continue, KiloCode: point their
  OpenAI-compatible base URL at `http://127.0.0.1:5001/v1` and pick
  any model name. They all use `/v1/chat/completions`, which has
  none of the role-mapping issues below.

The rest of this page is for users who specifically want Codex CLI.

## The error you will see

When Codex sends its first inference request, vLLM logs:

```
ERROR ... [hf.py:502] An error occurred in `transformers` while
applying chat template
ERROR ... jinja2.exceptions.TemplateError: Unexpected message role.
INFO:     127.0.0.1:NNNNN - "POST /v1/responses HTTP/1.1" 400 Bad Request
```

The traceback ends inside `qwen3.5-enhanced.jinja` at the role
dispatch. The shipped template only branches on `system`, `user`,
`assistant`, and `tool`. Codex sends a fifth role, `developer`,
which OpenAI introduced as a system-tier role for the Responses API.
The template falls through to `raise_exception('Unexpected message
role.')` and vLLM returns 400.

## The fix

Two options. Pick one.

### Option A: patch the chat template to accept `developer`

Open `templates/qwen3.5-enhanced.jinja` and add a four-line alias at
the very top of the message loop, before the first `{%- if
message.role == "system" -%}` check. The block converts a
`developer` role into a `system` role for the rest of the template:

```jinja
{%- if message.role == "developer" -%}
    {%- set message = dict(message, role="system") -%}
{%- endif -%}
```

Save the file and restart the snapshot. Codex CLI's first request
will now go through. This is a tiny patch with no effect on Claude
Code, OpenCode, Cline, or any other client that already uses the
four standard roles.

### Option B: replace the template with froggeric/Qwen-Fixed-Chat-Templates

[`froggeric/Qwen-Fixed-Chat-Templates`](https://huggingface.co/froggeric/Qwen-Fixed-Chat-Templates)
on Hugging Face is a community-maintained drop-in replacement for
the official Qwen3.5 / Qwen3.6 templates. Same `developer` to
`system` alias, plus five other fixes:

- `|items` iteration that breaks on llama.cpp / LM Studio / MLX.
- Empty `<think/>` blocks wasting context tokens on every history
  turn.
- `</thinking>` hallucination on Qwen3.6.
- Arguments serialised with `|tojson` crashing when the value is
  already a string.
- `raise_exception('No user query found')` hard-crashing agentic
  tool loops.

Download the relevant `.jinja` and point the snapshot at it via
`--chat-template`. The bundled snapshots use
`templates/qwen3.5-enhanced.jinja` by default, so the simplest
swap is to overwrite that file.

I have not validated the `froggeric` template end-to-end against
this snapshot stack yet, so if you take this path, run
`windows_tools/check_coherence.py --port 5001` afterwards to
confirm output is still clean.

## Codex CLI configuration

Codex does not respect `OPENAI_BASE_URL` or `OPENAI_API_KEY`
environment variables for custom providers. You have to declare the
provider in `~/.codex/config.toml`:

```toml
[model_providers.local_vllm]
name = "Local vLLM"
base_url = "http://127.0.0.1:5001/v1"
env_key = "OPENAI_API_KEY"
wire_api = "responses"

[profiles.qwen]
model_provider = "local_vllm"
model = "any"
```

Then export a dummy key (vLLM does not check it but the env var must
exist) and launch Codex with the profile:

```powershell
$env:OPENAI_API_KEY = "dummy"
codex --profile qwen
```

Notes:

- The `model` field can be literally `any`; the wheel uses a
  wildcard served-model-name so any string accepts.
- Do not use `codex --oss`. That mode hardcodes Ollama-only
  endpoints (`/api/tags`, `/api/pull`) which do not exist on vLLM
  and you will get 404s during model discovery.
- `wire_api = "responses"` is required for current Codex versions.
  Codex 0.80 and earlier accepted `wire_api = "chat"` which routes
  through `/v1/chat/completions` and avoids the `developer` role
  problem entirely, but that path was removed in February 2026.

## Verifying it works

After patching the template and configuring Codex:

1. Restart the snapshot so the new template is loaded.
2. Run `codex --profile qwen` in any project directory.
3. Ask Codex to read a file. The first request hits
   `/v1/responses`. If you see normal output instead of the 400, the
   patch is working.

If you still see `Unexpected message role.` in the vLLM log, the
snapshot is loading a different template than the one you patched.
Check the `--chat-template` flag in your snapshot file matches the
file you edited.

## Why I do not just ship the patch

I built and tested this server with Claude Code, not Codex. I have
no Codex CLI test environment so I cannot promise a Codex-aware
template stays correct across Codex updates. The Chat Completions
clients (Claude Code, Cline, Cursor, OpenCode) all work today
without the patch and that is the supported path.

If the patch above works for you and you have time to send a PR
that bakes it in plus a coherence-check pass, I will merge it.

## Related

- [`CLAUDE_CODE.md`](CLAUDE_CODE.md), the supported integration.
- [`COHERENCE.md`](COHERENCE.md), the validator to run after any
  template change.
- [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md), other vLLM-side
  failure modes.
