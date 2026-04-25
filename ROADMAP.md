# Roadmap

## Now — Public repository readiness

- Complete docs tree (installation, guides, architecture, reference).
- CI pipeline and contribution templates.
- Public issue and PR hygiene.
- Stable README, license, and governance files.

## Next — Better developer experience

- Improved MCP client integration guides.
- More reliable Docker Compose setup with health checks.
- Backup and restore documentation with verified tooling.

## Later — Richer memory workflows

- Broader MCP tool surface for batch operations and advanced queries.
- Improved vector projection quality (deterministic hashing is the current lightweight approach).
- Enhanced Obsidian vault projection with richer metadata and linking.
- Expanded configuration options for namespaces, retention, and indexing.

## Status Matrix

| Feature | Status | Notes |
|---|---|---|
| Complete docs tree (installation, guides, architecture, reference) | Implemented | `docs/` tree exists with guides and reference |
| CI pipeline and contribution templates | Implemented | `.github/workflows/ci.yml` runs pytest + Docker build |
| Public issue and PR hygiene | Implemented | Issue templates and PR template in `.github/` |
| Stable README, license, and governance files | Implemented | `README.md`, `LICENSE`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `CONTRIBUTING.md` |
| Improved MCP client integration guides | Implemented | Per-client guides in `docs/guides/mcp-clients/` |
| Reliable Docker Compose with health checks | Implemented | Docker health checks for all services (Phase 2) |
| Verified backup and restore tooling | Implemented | backup + restore scripts with PRAGMA integrity_check (Phase 2) |
| Batch MCP operations and advanced queries | Implemented | batch_write, batch_update_tags, extended search (Phase 3) |
| Improved vector projection quality | Implemented | Ollama embeddings with hash fallback (Phase 4) |
| Enhanced Obsidian vault projection | Implemented | Rich frontmatter, status subdirs (Phase 4) |
| Expanded configuration options | Implemented | embedding_strategy, retention, namespace config (Phase 4) |
