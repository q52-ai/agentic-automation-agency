"""Run the agency and its dashboard:  python -m agency [--host 0.0.0.0] [--port 8765] [--reset]"""
import argparse
import os

import uvicorn

from .config import load_settings
from .dashboard.server import create_app


def main():
    parser = argparse.ArgumentParser(prog="agency")
    parser.add_argument("--host", default=None,
                        help="interface to serve the dashboard on; 0.0.0.0 exposes it to the local network")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--reset", action="store_true", help="forget every posting and start over (keeps demos/)")
    args = parser.parse_args()

    settings = load_settings()
    host = args.host or os.getenv("AGENCY_HOST", "127.0.0.1")
    if args.reset:
        for suffix in ("", "-wal", "-shm"):  # SQLite's WAL journal files must go with the database
            settings.db_path.with_name(settings.db_path.name + suffix).unlink(missing_ok=True)
        print(f"Reset {settings.db_path}")

    print(f"Dashboard: http://{host}:{args.port}")
    uvicorn.run(create_app(settings), host=host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
