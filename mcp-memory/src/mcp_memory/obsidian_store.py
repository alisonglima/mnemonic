from __future__ import annotations

from pathlib import Path

from mcp_memory.models import MemoryRecord


class ObsidianProjectionStore:
    def __init__(self, vault_path: Path):
        self.vault_path = Path(vault_path)
        self.vault_path.mkdir(parents=True, exist_ok=True)

    def health(self) -> str:
        return "up" if self.vault_path.exists() else "down"

    def materialize_journal(self, record: MemoryRecord) -> Path:
        path = self.vault_path / f"{record.id}.md"
        path.write_text(
            f"---\nid: {record.id}\nversion: {record.version}\n---\n\n{record.content}\n",
            encoding="utf-8",
        )
        return path
