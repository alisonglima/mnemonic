# Obsidian Integration

Mnemonic can project journal entries into a local Obsidian-compatible vault as Markdown files. This happens asynchronously via the outbox worker.

## How it works

When a memory record is created with `obsidian_projection=True` (automatically set by `memory.journal`), the outbox worker writes a `.md` file to the vault directory:

```
{vault_path}/{record_id}.md
```

Each file contains:

```markdown
---
id: <record_id>
version: <record_version>
---

<record_content>
```

## Vault setup

```bash
mkdir -p ./obsidian-vault
echo '*.md' >> .gitignore  # if you don't want to commit vault content
```

Set `OBSIDIAN_VAULT=./obsidian-vault` in `.env` (default in `.env.example`).

## Materializing records

Journal entries are automatically projected after creation via the outbox worker. For bulk projection or rebuilding after data loss, run:

```bash
make reindex
```

This calls `rebuild_obsidian.py`, which re-materializes every record with `obsidian_projection=True` into the vault.

## Vault health

The `memory.health` tool reports whether the vault path exists. If the vault is missing, `obsidian_projection` reports `down` and the outbox worker retries projection events with backoff.

## Cleanup

Files are not automatically deleted when records are retracted or deleted. Run `make reindex` to sync the vault state — records with `status = deleted` are skipped by the rebuild script, so stale `.md` files from deleted records must be removed manually if desired.
