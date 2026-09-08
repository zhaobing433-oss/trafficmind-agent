"""Launch the backend against the isolated Qiantang Pilot demo stores."""

from __future__ import annotations

import argparse
from pathlib import Path

from backend.tools.qiantang_demo_runtime import (
    DEFAULT_RUNTIME_DIR,
    configure_demo_environment,
    ensure_isolated_runtime,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the isolated Qiantang Pilot demo backend")
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME_DIR)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    runtime_dir = ensure_isolated_runtime(args.runtime_dir)
    database = runtime_dir / "trafficmind_demo.db"
    if not database.exists():
        raise SystemExit(
            "Qiantang demo is not materialized. Run "
            "`python -m backend.tools.materialize_qiantang_demo` first."
        )
    configure_demo_environment(runtime_dir)

    import uvicorn

    uvicorn.run("backend.app:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
