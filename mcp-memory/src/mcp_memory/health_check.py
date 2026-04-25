from __future__ import annotations

from pathlib import Path
from typing import Dict
from urllib.request import urlopen

from mcp_memory.config import Settings


def check(sqlite_path: Path | str) -> int:
    """
    Docker healthcheck-compatible exit code check.
    Returns 0 if database exists and is accessible, 1 otherwise.
    """
    sqlite_path = Path(sqlite_path)
    if not sqlite_path.exists():
        return 1
    try:
        with open(sqlite_path, "rb") as f:
            header = f.read(16)
        if header != b"SQLite format 3\x00":
            return 1
    except OSError:
        return 1
    return 0


def docker_health(sqlite_path: Path | str, settings: Settings | None = None) -> Dict[str, str]:
    """
    Docker-oriented health check that matches HealthService status keys.

    Returns a dict with keys: sqlite, qdrant, ollama, worker, obsidian_projection.
    Used by Docker healthcheck to determine container health.
    """
    sqlite_path = Path(sqlite_path)
    sqlite_status = "up" if sqlite_path.exists() else "down"

    qdrant_status = "unknown"
    ollama_status = "unknown"

    if settings is None:
        try:
            settings = Settings.from_env()
        except Exception:
            pass

    if settings:
        if settings.qdrant_url:
            qdrant_status = _qdrant_check(settings.qdrant_url)
        if settings.ollama_url:
            ollama_status = _ollama_check(settings.ollama_url)

    vault_path = Path(settings.vault_path) if settings else Path("./obsidian-vault")
    obsidian_status = "up" if vault_path.exists() else "down"

    return {
        "sqlite": sqlite_status,
        "qdrant": qdrant_status,
        "ollama": ollama_status,
        "worker": "up",
        "obsidian_projection": obsidian_status,
    }


def _qdrant_check(url: str) -> str:
    try:
        with urlopen(f"{url}/healthz", timeout=2) as resp:
            if 200 <= resp.status < 300:
                return "up"
            return "down"
    except Exception:
        return "down"


def _ollama_check(url: str) -> str:
    try:
        with urlopen(f"{url}/api/tags", timeout=2) as resp:
            if 200 <= resp.status < 300:
                return "up"
            return "down"
    except Exception:
        return "down"


if __name__ == "__main__":
    import json
    import sys

    sqlite_path = sys.argv[1] if len(sys.argv) > 1 else "./data/memory.db"
    exit_code = check(sqlite_path)
    result = docker_health(sqlite_path)
    print(json.dumps(result, indent=2))
    raise SystemExit(exit_code)
