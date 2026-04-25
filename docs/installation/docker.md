# Docker Installation

Mnemonic ships with a three-service Docker Compose stack: the MCP server, Qdrant for vector projections, and Ollama (included for future local-model workflows — not used by the current projection logic).

## Prerequisites

- Docker Compose v2+
- 4 GB RAM available (for Qdrant and Ollama containers)

## Start the stack

```bash
cp .env.example .env
docker compose up -d --build
```

This builds the MCP server image and starts all three services.

- **MCP server** — `localhost:8080`
- **Qdrant** — internal only (not exposed to host by default)
- **Ollama** — internal only (not exposed to host by default); health-checked when configured

To expose Qdrant's port to the host, add a `ports` entry to the `qdrant` service in `docker-compose.yml`:

```yaml
qdrant:
  image: qdrant/qdrant:v1.13.2
  ports:
    - "6333:6333"
```

Similarly for Ollama:

```yaml
ollama:
  image: ollama/ollama:0.6.8
  ports:
    - "11434:11434"
```

The compose-managed `mcp-memory` container uses the internal service URL `http://qdrant:6333` from `docker-compose.yml`. Use `http://localhost:6333` only for host-local workflows such as `make run` after exposing Qdrant to the host.

## Verify

Check that the container is running:

```bash
docker compose ps
```

Or check container logs:

```bash
docker compose logs mcp-memory
```

To check system health, call `memory.health` via the MCP protocol — it reports SQLite status, optional Qdrant reachability, Obsidian vault path, worker status, and outbox queue depth.

## Stop

```bash
docker compose down
```

This stops all containers. Data volumes (`./data`, `./obsidian-vault`) are preserved on disk.

## Persistence

The following directories are bind-mounted:

| Host path | Container path | Contents |
|---|---|---|
| `./data` | `/data` | SQLite database file |
| `./obsidian-vault` | `/vault` | Obsidian Markdown projections |

Backup or volume-mount them as needed for your workflow.
