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
| Improved MCP client integration guides | Planned | Phase 1 of improve-roadmap-readiness |
| Reliable Docker Compose with health checks | Planned | Phase 2 of improve-roadmap-readiness |
| Verified backup and restore tooling | Partial | Backup implemented; restore planned in Phase 2 |
| Batch MCP operations and advanced queries | Planned | Phase 3 of improve-roadmap-readiness |
| Improved vector projection quality | Partial | Deterministic hash active; Ollama path planned in Phase 4 |
| Enhanced Obsidian vault projection | Planned | Phase 4 of improve-roadmap-readiness |
| Expanded configuration options | Planned | Phase 4 of improve-roadmap-readiness |
