from __future__ import annotations

import subprocess
import sys
import time
import os
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    backend_dir = root / "backend"
    frontend_dir = root / "frontend"
    backend_port = os.getenv("OPENFINANCE_BACKEND_PORT", "8000")
    backend_url = f"http://127.0.0.1:{backend_port}"
    frontend_cmd = ["npm", "run", "dev"]
    backend_cmd = [sys.executable, "-m", "uvicorn", "openfinance.api.main:app", "--reload", "--port", backend_port]
    is_windows = sys.platform == "win32"
    frontend_cmd = ["npm.cmd" if is_windows else "npm", "run", "dev"]
    frontend_env = os.environ.copy()
    frontend_env["NEXT_PUBLIC_API_BASE"] = backend_url

    print(f"Starting backend on {backend_url}")
    backend = subprocess.Popen(backend_cmd, cwd=backend_dir)
    print(f"Starting frontend on http://localhost:3000 (NEXT_PUBLIC_API_BASE={backend_url})")
    frontend = subprocess.Popen(frontend_cmd, cwd=frontend_dir, env=frontend_env)

    procs = [backend, frontend]

    try:
        while True:
            for proc in procs:
                code = proc.poll()
                if code is not None:
                    print(f"Process exited early (pid={proc.pid}, code={code}). Stopping others.")
                    raise SystemExit(code)
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping dev services...")
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
        print("Stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
