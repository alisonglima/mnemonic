# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `qdrant_coverage_ratio` in health endpoint — exposes fraction of active records with current Qdrant projection.
- `token_estimate` and `item_count` fields in `memory.search` results — allows agents to estimate token overhead per search.
- `scripts/benchmark_native.py` — direct write-path benchmark that bypasses HTTP/SSE overhead.
- `scripts/benchmark.py --recall-only` — run only the recall/precision test without performance benchmarks.
- `scripts/benchmark.py --wait-coverage` — poll until Qdrant coverage threshold is met before running tests.
- Migration v3 — SQL indexes on `memory_records(namespace, status)` and `memory_records(scope_id)` for faster filtered queries.

### Changed

- **Migration runner fix**: `PRAGMA user_version` moved outside `executescript()` and committed separately. ALTER TABLE is now idempotent — checks `PRAGMA table_info` before adding columns, recovering databases left in a broken state by the original bug. Migration DDL is wrapped in `BEGIN IMMEDIATE`/`COMMIT`.
- **Staleness metric replaced**: `oldest_pending_age_seconds()` → `qdrant_coverage_ratio()`. Hybrid RRF activates when ≥80% of records in the queried scope have current Qdrant vectors, instead of relying on outbox backlog age. Coverage is scoped by namespace, scope_id, and archived status.
- **RRF tuning**: k=60 → k=30, candidate limit 50 → 100. Expanded synonym dictionary for query expansion.
- **WAL tuning**: Auto-checkpoint disabled (`wal_autocheckpoint=10000`), `synchronous=NORMAL`. Pragmas applied per-connection in `Database.connect()`.
- **Qdrant-disabled degradation**: When Qdrant is explicitly disabled, search returns `degraded=false` instead of `degraded=true`.
- `freshness_seconds` field in `SearchResult` is always 0 — replaced by `qdrant_coverage_ratio` as the staleness indicator.

### Fixed

- **P0 — Migration runner**: `PRAGMA user_version` inside `executescript(BEGIN IMMEDIATE; ...; COMMIT;)` did not persist, causing `duplicate column name` crash on container restart.
- **P0 — Staleness metric**: Outbox backlog age caused hybrid_rrf to never activate under sustained write load.
- **P1 — Recall**: Hybrid search now correctly excludes archived and stale records from semantic results.
- **Benchmark cleanup**: All benchmark test records now carry `#benchmark` tag for deterministic cleanup.

### Infrastructure

- Improved `mcp-memory/Dockerfile` to install the project package in editable mode.
- Improved `docker-compose.yml` with explicit service wiring and health intent.
- Improved `mcp-memory/pyproject.toml` with project metadata, keywords, and classifiers.
- `mcp-memory/Dockerfile` now copies `scripts/` into the container image.

## [0.1.0] — Alpha

Initial functional release covering the core memory model, MCP tools, SQLite source of truth, Qdrant vector projections, and Obsidian vault sync.
