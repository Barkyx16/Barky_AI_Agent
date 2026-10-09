"""Command line: `python -m boardroom` to serve, `python -m boardroom set-plan EMAIL pro` to manage plans."""

from __future__ import annotations

import argparse
import os
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="boardroom")
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="run the web app (default)")
    serve.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    plan = sub.add_parser("set-plan", help="set a user's plan")
    plan.add_argument("email")
    plan.add_argument("plan", choices=["free", "pro"])
    backup = sub.add_parser("backup", help="write a consistent copy of the database")
    backup.add_argument("dest", nargs="?", help="output path (default: data/backups/boardroom-<timestamp>.db)")
    args = parser.parse_args(argv)

    if args.command == "backup":
        from datetime import datetime, timezone
        from pathlib import Path

        import sqlite3

        from .config import Settings

        db_path = Settings.from_env().db_path
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        dest = args.dest or str(Path(db_path).parent / "backups" / f"boardroom-{stamp}.db")
        if not Path(db_path).is_file():
            print(f"No database at {db_path}", file=sys.stderr)
            return 1
        # A raw connection: opening it via Database() would run migrations on the live file.
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        src, target = sqlite3.connect(db_path), sqlite3.connect(dest)
        try:
            src.backup(target)
        finally:
            src.close()
            target.close()
        print(f"Backed up {db_path} to {dest}")
        return 0

    if args.command == "set-plan":
        from .config import Settings
        from .db import Database

        db = Database(Settings.from_env().db_path)
        if not db.set_plan(args.email.strip().lower(), args.plan):
            print(f"No user with email {args.email}", file=sys.stderr)
            return 1
        print(f"{args.email} is now on the {args.plan} plan.")
        return 0

    import uvicorn

    from .app import create_app

    host = getattr(args, "host", os.environ.get("HOST", "127.0.0.1"))
    port = getattr(args, "port", int(os.environ.get("PORT", "8000")))
    app = create_app()
    print(f"Boardroom is open at http://{host}:{port}" + ("  (demo mode)" if app.state.engine.name == "demo" else ""))
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
