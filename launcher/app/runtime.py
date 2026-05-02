from __future__ import annotations
import re
import subprocess
from dataclasses import dataclass

CREATE_NEW_CONSOLE = 0x00000010
CREATE_NO_WINDOW = 0x08000000


@dataclass
class RunningProc:
    pid: int
    port: int
    cmdline: str
    max_model_len: int | None
    mtp_n: int | None
    matched_id: str | None = None


def _netstat_pids(ports: list[int]) -> dict[int, int]:
    """Return {port: pid} for LISTENING tcp ports."""
    out: dict[int, int] = {}
    try:
        r = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True,
            timeout=5, creationflags=CREATE_NO_WINDOW,
        )
    except Exception:
        return out
    for line in r.stdout.splitlines():
        if "LISTENING" not in line:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        local = parts[1]
        try:
            port = int(local.rsplit(":", 1)[-1])
        except ValueError:
            continue
        if port in ports:
            try:
                out[port] = int(parts[-1])
            except ValueError:
                pass
    return out


def _cmdline_for(pid: int) -> str:
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"],
            capture_output=True, text=True, timeout=8,
            creationflags=CREATE_NO_WINDOW,
        )
        return (r.stdout or "").strip()
    except Exception:
        return ""


_RE_LEN = re.compile(r"--max-model-len[= ](\d+)")
_RE_MTP = re.compile(r'num_speculative_tokens"\s*:\s*(\d+)')


def detect_running(ports: list[int], configs) -> dict[str, RunningProc]:
    """Return {config_id: RunningProc} for matched configs."""
    pid_by_port = _netstat_pids(ports)
    result: dict[str, RunningProc] = {}
    for port, pid in pid_by_port.items():
        cmd = _cmdline_for(pid)
        m1 = _RE_LEN.search(cmd)
        m2 = _RE_MTP.search(cmd)
        ml = int(m1.group(1)) if m1 else None
        mn = int(m2.group(1)) if m2 else None
        proc = RunningProc(pid=pid, port=port, cmdline=cmd, max_model_len=ml, mtp_n=mn)
        # match against configs
        for c in configs:
            if c.port != port:
                continue
            if ml is not None and c.ctx == ml:
                if mn is None and c.mtp_n is None:
                    proc.matched_id = c.id; break
                if mn is not None and c.mtp_n == mn:
                    proc.matched_id = c.id; break
        if proc.matched_id is None:
            # fallback: just port match
            for c in configs:
                if c.port == port:
                    proc.matched_id = c.id; break
        if proc.matched_id:
            result[proc.matched_id] = proc
    return result


def _wt_exe() -> str | None:
    """Locate Windows Terminal — prefer bundled portable, then system, then PATH."""
    import os, shutil
    root = os.environ.get("CC_PORTABLE_ROOT")
    candidates = []
    if root:
        candidates.append(os.path.join(root, "terminal", "WindowsTerminal.exe"))
    candidates += [
        r"C:\Program Files\WindowsTerminal\wt.exe",
        r"C:\Program Files\WindowsTerminal\WindowsTerminal.exe",
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return shutil.which("wt") or shutil.which("WindowsTerminal")


def start_config(bat_path: str, config_id: str = "") -> None:
    """Launch the .bat in a new Windows Terminal tab (falls back to cmd console)."""
    import os
    cwd = os.path.dirname(bat_path)
    title = f"vLLM {config_id}" if config_id else "vLLM"
    wt = _wt_exe()
    if wt:
        # Reuse a named window so repeated launches stack as tabs.
        subprocess.Popen(
            [wt, "-w", "vllm-launcher", "new-tab", "-d", cwd,
             "--title", title, "cmd", "/k", bat_path],
            creationflags=CREATE_NO_WINDOW,
            cwd=cwd,
        )
        return
    subprocess.Popen(
        ["cmd", "/c", "start", "", "/D", cwd, bat_path],
        creationflags=CREATE_NEW_CONSOLE,
        cwd=cwd,
    )


def _ancestor_chain(pid: int, max_depth: int = 8) -> list[tuple[int, str]]:
    """Walk parent pids up to max_depth. Returns [(pid, name), ...] starting from pid."""
    chain: list[tuple[int, str]] = []
    cur = pid
    seen: set[int] = set()
    for _ in range(max_depth):
        if cur in seen or cur <= 0:
            break
        seen.add(cur)
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"$p = Get-CimInstance Win32_Process -Filter 'ProcessId={cur}';"
                 " if ($p) { \"$($p.ProcessId)|$($p.Name)|$($p.ParentProcessId)\" }"],
                capture_output=True, text=True, timeout=8,
                creationflags=CREATE_NO_WINDOW,
            )
            line = (r.stdout or "").strip()
            if not line or "|" not in line:
                break
            spid, name, ppid = line.split("|", 2)
            chain.append((int(spid), name.strip().lower()))
            cur = int(ppid)
        except Exception:
            break
    return chain


def kill_pid(pid: int) -> tuple[bool, str]:
    """Kill the vLLM process tree AND its parent cmd.exe so the terminal tab closes.

    Process tree on Windows when launched via wt -> cmd /k bat -> python:
      WindowsTerminal.exe -> OpenConsole.exe -> cmd.exe -> python.exe -> python.exe (workers)
    taskkill /T from python only kills descendants, leaving cmd.exe alive (because of /k),
    so the WT tab stays. We additionally locate and kill the parent cmd.exe.
    """
    msgs: list[str] = []
    ok_any = False
    cmd_pid: int | None = None
    chain = _ancestor_chain(pid)
    for ancestor_pid, name in chain[1:]:  # skip self
        if name == "cmd.exe":
            cmd_pid = ancestor_pid
            break
        if name in ("windowsterminal.exe", "openconsole.exe", "conhost.exe"):
            break  # don't kill the terminal itself
    try:
        r = subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True, text=True, timeout=10,
            creationflags=CREATE_NO_WINDOW,
        )
        ok_any = ok_any or (r.returncode == 0)
        msgs.append(f"py:{(r.stdout + r.stderr).strip()}")
    except Exception as e:
        msgs.append(f"py:{e}")
    if cmd_pid is not None:
        try:
            r = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(cmd_pid)],
                capture_output=True, text=True, timeout=10,
                creationflags=CREATE_NO_WINDOW,
            )
            ok_any = ok_any or (r.returncode == 0)
            msgs.append(f"cmd({cmd_pid}):{(r.stdout + r.stderr).strip()}")
        except Exception as e:
            msgs.append(f"cmd:{e}")
    else:
        msgs.append("cmd:not-found")
    return ok_any, " | ".join(msgs)
