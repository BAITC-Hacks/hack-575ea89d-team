"""One entry point for Windows, macOS and Linux; no separate frontend server."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="Start the Network Intelligence dashboard and API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--demo", action="store_true", help="Generate separate synthetic 40-tower/4000-complaint data")
    parser.add_argument("--no-ai", action="store_true", help="Use Python demo mode even if a key is configured")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    environment = ROOT / "backend" / ".venv"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        print("Preparing the Python environment (first run)...", flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
    ready = subprocess.run([str(python), "-c", "import fastapi,uvicorn,openai,dotenv"], capture_output=True)
    if ready.returncode:
        subprocess.run([str(python), "-m", "pip", "install", "-r", str(ROOT / "backend/requirements.txt")], check=True)
    env = os.environ.copy()
    if args.demo:
        from scripts.generate_demo import generate
        directory = ROOT / "backend" / ".demo-data"
        manifest = generate(directory)
        env["NETWORK_DATA_DIR"] = str(directory)
        env["NETWORK_STATE_DB"] = str(directory / "state.sqlite3")
        print(f"Synthetic demo: {manifest['counts']['towers']} towers, {manifest['counts']['complaints']} complaints.", flush=True)
    if args.no_ai:
        # dotenv does not override an explicitly supplied environment value.
        env["OPENAI_API_KEY"] = ""
        env["OPENAI_MODEL"] = ""
    display_host = "127.0.0.1" if args.host == "0.0.0.0" else args.host
    print(f"Dashboard: http://{display_host}:{args.port}/", flush=True)
    print(f"API documentation: http://{display_host}:{args.port}/docs", flush=True)
    try:
        result = subprocess.run([str(python), "-m", "uvicorn", "app.main:app", "--host", args.host,
                                 "--port", str(args.port)], cwd=ROOT / "backend", env=env)
    except KeyboardInterrupt:
        return
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
