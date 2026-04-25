from __future__ import annotations

from pathlib import Path

from mcp_memory.models import MemoryRecord


class ObsidianProjectionStore:
    # Status subdirectories
    STATUS_SUBDIRS = {
        "active": "",
        "archived": "archived",
        "retracted": "retracted",
        "deleted": "deleted",
    }

    def __init__(self, vault_path: Path):
        self.vault_path = Path(vault_path)

    def health(self) -> str:
        return "up" if self.vault_path.exists() else "down"

    def _get_status_dir(self, status: str) -> Path:
        """Get the subdirectory path for a given status."""
        subdir = self.STATUS_SUBDIRS.get(status, "")
        if subdir:
            return self.vault_path / subdir
        return self.vault_path

    def materialize_journal(self, record: MemoryRecord) -> Path:
        """Materialize a memory record as a Markdown file with YAML frontmatter."""
        status_dir = self._get_status_dir(record.status)
        status_dir.mkdir(parents=True, exist_ok=True)

        path = status_dir / f"{record.id}.md"

        # Build frontmatter
        frontmatter_lines = [
            "---",
            f"id: {record.id}",
            f"version: {record.version}",
            f"type: {record.type}",
            f"status: {record.status}",
            f"namespace: {record.namespace}",
            f"scope_id: {record.scope_id}",
            f"created_at: {record.created_at}",
            f"updated_at: {record.updated_at}",
        ]

        # Add tags if present
        if record.tags:
            frontmatter_lines.append("tags:")
            for tag in record.tags:
                frontmatter_lines.append(f"  - {tag}")

        frontmatter_lines.append("---")

        content = "\n".join(frontmatter_lines) + f"\n\n{record.content}\n"
        path.write_text(content, encoding="utf-8")
        return path
