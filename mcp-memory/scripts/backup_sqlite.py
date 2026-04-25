from __future__ import annotations

import shutil
from pathlib import Path

from mcp_memory.config import Settings


def main() -> int:
    settings = Settings.from_env()
    source = settings.database_path
    if not source.exists():
        return 0
    backup = source.with_suffix(".backup.db")
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, backup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
