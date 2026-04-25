from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class DockerComposeTests(unittest.TestCase):
    def test_dependency_healthchecks_match_minimal_images(self) -> None:
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn('condition: service_healthy', compose)
        self.assertIn("GET /healthz HTTP/1.1", compose)
        self.assertIn("grep -q 'HTTP/1.1 200'", compose)
        self.assertIn('test: ["CMD", "ollama", "list"]', compose)
        self.assertNotIn("http://localhost:6333/health", compose)
        self.assertNotIn("curl", compose)


if __name__ == "__main__":
    unittest.main()
