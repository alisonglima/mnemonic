# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `CODE_OF_CONDUCT.md` — Contributor Covenant code of conduct.
- `CONTRIBUTING.md` — Development workflow and scope rules for contributors.
- `FAQ.md` — Answers to common questions about naming, architecture, and project status.
- `LICENSE` — MIT license file.
- `ROADMAP.md` — Now/Next/Later roadmap for the project.
- `SECURITY.md` — Private disclosure policy for security issues.
- `docs/` — Structured documentation tree covering installation, guides, architecture, and reference.
- `.editorconfig`, `Makefile` — Local developer tooling and command surface.
- `.github/workflows/ci.yml` — GitHub Actions CI pipeline.
- `.github/ISSUE_TEMPLATE/` — Structured issue templates for bugs, features, and documentation.
- `.github/pull_request_template.md` — PR template with verification checklist.

### Changed

- Rebranded repository from internal `memory-stack` naming to public-facing **Mnemonic** product name.
- Expanded `.env.example` with documented runtime environment variables.
- Updated `README.md` with full feature overview, architecture diagram, and docs index.

### Infrastructure

- Improved `mcp-memory/Dockerfile` to install the project package in editable mode.
- Improved `docker-compose.yml` with explicit service wiring and health intent.
- Improved `mcp-memory/pyproject.toml` with project metadata, keywords, and classifiers.

## [0.1.0] — Alpha

Initial functional release covering the core memory model, MCP tools, SQLite source of truth, Qdrant vector projections, and Obsidian vault sync.
