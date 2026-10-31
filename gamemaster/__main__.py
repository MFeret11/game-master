"""Start the server: `uv run python -m gamemaster` (start.command does this)."""

import os

import uvicorn

from .app import create_app
from .netinfo import lan_ip


def main() -> None:
    port = int(os.environ.get("GM_PORT", "8000"))
    print(f"\n  Game Master is running.\n"
          f"  TV:     http://localhost:{port}/tv\n"
          f"  Phones: http://{lan_ip()}:{port}\n"
          f"  Leave this window open. Close it to stop.\n")
    uvicorn.run(create_app(port=port), host="0.0.0.0", port=port, log_level="warning")


if __name__ == "__main__":
    main()
