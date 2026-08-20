"""Wrapper: run uvicorn with correct env"""
import os, sys, subprocess

PYTHON = r"C:\Users\zhudaoren\.conda\envs\AgentService\python.exe"
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SERVICES = os.path.join(ROOT, "services")
SHARED = os.path.join(SERVICES, "shared")
LOGDIR = os.path.join(ROOT, "logs")
os.makedirs(LOGDIR, exist_ok=True)

svc_name = sys.argv[1]
port = sys.argv[2]

env = os.environ.copy()
env["PYTHONPATH"] = SHARED + os.pathsep + "."
env["PYTHONIOENCODING"] = "utf-8"
env["PYTHONUTF8"] = "1"

cwd = os.path.join(SERVICES, svc_name)
logfile = os.path.join(LOGDIR, f"{svc_name}-bg.log")
errfile = os.path.join(LOGDIR, f"{svc_name}-bg.err")

# Keep running uvicorn, restart on crash MAX times
max_restarts = 5
restarts = 0
with open(logfile, "ab", buffering=0) as fout, open(errfile, "ab", buffering=0) as ferr:
    while True:
        print(f"[launcher] Starting {svc_name} on port {port} (restart {restarts}/{max_restarts})", flush=True)
        proc = subprocess.Popen(
            [PYTHON, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", str(port)],
            cwd=cwd, env=env, stdout=fout, stderr=ferr,
        )
        code = proc.wait()
        print(f"[launcher] {svc_name} exited code={code}", flush=True)
        restarts += 1
        if restarts > max_restarts:
            print(f"[launcher] {svc_name} max restarts reached, give up", flush=True)
            sys.exit(code)
        import time
        time.sleep(3)
