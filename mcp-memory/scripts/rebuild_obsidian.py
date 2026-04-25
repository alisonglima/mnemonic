from __future__ import annotations

from mcp_memory.config import Settings
from mcp_memory.database import Database
from mcp_memory.obsidian_store import ObsidianProjectionStore
from mcp_memory.repository import MemoryRepository


def main() -> int:
    settings = Settings.from_env()
    db = Database(settings.database_path)
    db.initialize()
    repository = MemoryRepository(db)
    obsidian = ObsidianProjectionStore(settings.vault_path)
    for record in repository.list_records():
        if record.obsidian_projection and record.status != "deleted":
            obsidian.materialize_journal(record)
            repository.set_projection_version(record.id, "obsidian", record.version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
