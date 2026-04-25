from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import tempfile
import textwrap
import time
import unittest
import uuid
from pathlib import Path

from fastmcp import Client


ROOT = Path(__file__).resolve().parents[2]


def _docker_e2e_enabled() -> bool:
    return os.getenv("RUN_DOCKER_E2E") == "1"


def _run_compose(project: str, override_file: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "docker",
            "compose",
            "-p",
            project,
            "-f",
            str(override_file),
            *args,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def _call_tool(client: Client, name: str, arguments: dict):
    result = await client.call_tool(name, arguments)
    return result.data


@unittest.skipUnless(_docker_e2e_enabled(), "set RUN_DOCKER_E2E=1 to run Docker E2E tests")
class DockerMcpE2ETests(unittest.TestCase):
    def test_container_serves_mcp_memory_flow_over_sse(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mnemonic-e2e-") as tmp:
            tmp_path = Path(tmp)
            data_dir = tmp_path / "data"
            vault_dir = tmp_path / "vault"
            data_dir.mkdir()
            vault_dir.mkdir()
            host_port = _free_tcp_port()
            override_file = tmp_path / "docker-compose.e2e.yml"
            override_file.write_text(
                textwrap.dedent(
                    f"""
                    services:
                      mcp-memory:
                        build: {ROOT / "mcp-memory"}
                        environment:
                          SQLITE_PATH: /data/memory.db
                          OBSIDIAN_VAULT: /vault
                          MCP_PORT: "8080"
                          QDRANT_URL: http://qdrant:6333
                        volumes:
                          - {data_dir}:/data
                          - {vault_dir}:/vault
                        ports:
                          - "127.0.0.1:{host_port}:8080"
                        depends_on:
                          qdrant:
                            condition: service_healthy
                        command: ["python", "-m", "mcp_memory.main", "--host", "0.0.0.0", "--port", "8080", "--serve"]
                        healthcheck:
                          test: ["CMD", "python", "-m", "mcp_memory.health_check", "/data/memory.db"]
                          interval: 5s
                          timeout: 5s
                          retries: 12
                          start_period: 5s

                      qdrant:
                        image: qdrant/qdrant:v1.13.2
                        healthcheck:
                          test: ["CMD", "bash", "-c", "</dev/tcp/127.0.0.1/6333"]
                          interval: 5s
                          timeout: 5s
                          retries: 12
                          start_period: 5s
                    """
                ),
                encoding="utf-8",
            )
            project = f"mnemonic-e2e-{uuid.uuid4().hex[:12]}"

            try:
                up = _run_compose(project, override_file, "up", "-d", "--build")
                self.assertEqual(up.returncode, 0, up.stderr + up.stdout)
                self._wait_for_healthy_container(project, override_file)

                asyncio.run(self._assert_memory_flow(host_port))
            finally:
                _run_compose(project, override_file, "down", "-v", "--remove-orphans")

    def _wait_for_healthy_container(self, project: str, override_file: Path) -> None:
        deadline = time.time() + 120
        last_output = ""
        while time.time() < deadline:
            ps = _run_compose(project, override_file, "ps", "--format", "json", "mcp-memory")
            last_output = ps.stderr + ps.stdout
            if ps.returncode == 0 and ps.stdout.strip():
                for line in ps.stdout.splitlines():
                    service = json.loads(line)
                    if service.get("Health") == "healthy":
                        return
            time.sleep(2)

        logs = _run_compose(project, override_file, "logs", "--no-color", "mcp-memory")
        self.fail("mcp-memory container did not become healthy\n" + last_output + logs.stdout + logs.stderr)

    async def _assert_memory_flow(self, host_port: int) -> None:
        async with Client(f"http://127.0.0.1:{host_port}/sse") as client:
            created = await _call_tool(
                client,
                "memory.write",
                {
                    "content": "Docker E2E memory flow",
                    "type": "fact",
                    "namespace": "e2e",
                    "scope_id": "docker",
                    "source": "test-suite",
                    "tags": ["docker", "e2e"],
                    "idempotency_key": "docker-e2e-flow",
                },
            )
            memory_id = created["record"]["id"]

            fetched = await _call_tool(client, "memory.get", {"id": memory_id})
            vector_only_query = "vector-only-not-in-sqlite-content"
            sqlite_fallback = await _call_tool(
                client,
                "memory.search",
                {"query": vector_only_query, "namespace": "e2e", "scope_id": "docker", "status": "active"},
            )
            search = await _call_tool(
                client,
                "memory.search",
                {"query": vector_only_query, "namespace": "e2e", "scope_id": "docker"},
            )
            updated = await _call_tool(
                client,
                "memory.update",
                {
                    "id": memory_id,
                    "expected_version": fetched["record"]["version"],
                    "content": "Docker E2E memory flow updated",
                    "change_reason": "e2e-update",
                },
            )
            health = await _call_tool(client, "memory.health", {})

        self.assertEqual(fetched["record"]["id"], memory_id)
        self.assertEqual(sqlite_fallback["items"], [])
        self.assertEqual(sqlite_fallback["search_mode"], "fallback_sqlite")
        self.assertEqual(search["items"][0]["id"], memory_id)
        self.assertEqual(search["search_mode"], "hybrid")
        self.assertFalse(search["degraded"])
        self.assertEqual(updated["record"]["version"], fetched["record"]["version"] + 1)
        self.assertEqual(health["sqlite"], "up")
        self.assertEqual(health["qdrant"], "up")
        self.assertEqual(health["worker"], "up")


if __name__ == "__main__":
    unittest.main()
