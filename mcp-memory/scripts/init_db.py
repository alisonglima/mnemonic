from __future__ import annotations

from mcp_memory.config import Settings
from mcp_memory.database import Database


def main() -> int:
    settings = Settings.from_env()
    db = Database(settings.database_path)
    db.initialize()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
