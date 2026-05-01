from __future__ import annotations
import argparse
import sys
import traceback
from . import model_setup, setup as runtime_setup
from .app import LauncherApp


def main() -> None:
    p = argparse.ArgumentParser(prog="vllm_launcher", description="vLLM config launcher TUI")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="Run web UI only (textual-serve)")
    s.add_argument("--host", default="localhost")
    s.add_argument("--port", type=int, default=8765)
    p.add_argument("--skip-model-check", action="store_true",
                   help="Skip the pre-TUI model discovery prompt.")
    p.add_argument("--skip-runtime-check", action="store_true",
                   help="Skip the pre-TUI vLLM runtime install check.")
    args = p.parse_args()

    if args.cmd == "serve":
        from textual_serve.server import Server
        cmd = f'"{sys.executable}" -m vllm_launcher'
        Server(command=cmd, host=args.host, port=args.port, title="vLLM Launcher").serve()
        return

    if not args.skip_runtime_check:
        try:
            runtime_setup.ensure_runtime()
        except KeyboardInterrupt:
            print("\nAborted.")
            sys.exit(130)
        except Exception:  # noqa: BLE001
            print("\n[start] runtime install failed:\n")
            traceback.print_exc()
            input("\nPress Enter to exit...")
            sys.exit(1)

    if not args.skip_model_check:
        try:
            model_setup.ensure_model()
        except KeyboardInterrupt:
            print("\nAborted.")
            sys.exit(130)
        except Exception:  # noqa: BLE001
            print("\n[start] model setup failed:\n")
            traceback.print_exc()
            input("\nPress Enter to exit...")
            sys.exit(1)

    LauncherApp().run()


if __name__ == "__main__":
    main()
