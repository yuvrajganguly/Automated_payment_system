"""payout-api - launch the FastAPI server with uvicorn."""

from __future__ import annotations

import argparse


def main() -> None:
    import uvicorn

    p = argparse.ArgumentParser(prog="payout-api", description="Run the Payout API server")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true", help="Auto-reload on code changes")
    args = p.parse_args()
    uvicorn.run("payout.api.app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
