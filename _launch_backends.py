"""Persistent launcher for all 5 backend services."""
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

PYTHON = r"C:\Users\zhudaoren\.conda\envs\AgentService\python.exe"
ROOT = Path(__file__).resolve().parent
LOGDIR = ROOT / "logs"
LOGDIR.mkdir(parents=True, exist_ok=True)

SVCS = [
    ("gateway",   8000, "gateway"),
    ("agent-svc", 8001, "agent-svc"),
    ("chat-svc",  8002, "chat-svc"),
    ("tool-svc",  8003, "tool-svc"),
    ("mem-svc",   8004, "mem-svc"),
]

RUNNER = ROOT / "scripts" / "run_svc_bg.py"


def stream_watcher(name: str, pipe):
    try:
        for raw in pipe:
            try:
                line = raw.decode("utf-8", errors="replace").rstrip()
            except Exception:
                line = str(raw)
            print(f"[{name}] {line}", flush=True)
    except Exception:
        pass


def main():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "services" / "shared") + os.pathsep + "."
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    procs = []
    for name, port, d in SVCS:
        print(f"[ALL] starting {name} port={port}", flush=True)
        p = subprocess.Popen(
            [PYTHON, str(RUNNER), d, str(port)],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
        )
        procs.append((name, p))
        t = threading.Thread(target=stream_watcher, args=(name, p.stdout), daemon=True)
        t.start()
        time.sleep(1)

    try:
        while True:
            alive = 0
            for (n, p) in procs:
                if p.poll() is None:
                    alive += 1
            if alive == 0:
                print("[ALL] all launchers exited", flush=True)
                break
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        for (n, p) in procs:
            try:
                if p.poll() is None:
                    p.terminate()
            except Exception:
                pass
        for (n, p) in procs:
            try:
                p.wait(timeout=10)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        print("[ALL] exit", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
