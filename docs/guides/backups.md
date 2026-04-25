# Backups

The SQLite database is the source of truth for all memory records. Back it up regularly.

## Run a backup

```bash
make backup
```

This runs `backup_sqlite.py`, which copies `SQLITE_PATH` to a `.backup.db` file in the same directory. The script is idempotent — running it multiple times overwrites the same backup file.

## Backup location

By default, `make backup` replaces the original suffix with `.backup.db` next to the original. With the default `SQLITE_PATH=./data/memory.db`, the backup lands at `./data/memory.backup.db`.

## What is backed up

The backup includes:
- All memory records
- Revision history
- Outbox events
- Projection state

It is a direct file copy of the SQLite file at backup time. It does not include:
- Qdrant data (rebuild from SQLite with `make reindex`)
- Obsidian vault files (these are reconstructed projections, not primary data)

## Automating backups

For automated backups, add a cron job or systemd timer:

```cron
# daily backup at 3am
0 3 * * * cd /path/to/mnemonic && make backup
```

Or mount a volume snapshot at `./data` to capture consistent snapshots at the infrastructure level.

## Restore from backup

If data loss occurs, restore from the backup file:

```bash
make restore
```

This runs `restore_sqlite.py`, which copies `SQLITE_PATH.backup.db` back to `SQLITE_PATH`. After restoring, rebuild Qdrant and Obsidian projections:

```bash
make reindex
```

### Restore with explicit paths

To restore a specific backup file to a specific location:

```bash
python mcp-memory/scripts/restore_sqlite.py /path/to/backup.backup.db /path/to/target.db
```

### Restore options

| Option | Description |
|--------|-------------|
| `--dry-run` | Validate source but do not copy |
| `--no-backup` | Skip pre-restore backup of existing target |

**Dry run** is useful to verify a backup is valid before restoring:

```bash
python mcp-memory/scripts/restore_sqlite.py /path/to/backup.backup.db /path/to/target.db --dry-run
```

**Pre-restore backup**: Before overwriting the target, the script automatically backs up the existing target to `target.pre-restore.db`. Use `--no-backup` to skip this.

### Restore exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Source backup not found |
| 2 | Source failed validation (PRAGMA integrity_check) |
| 3 | Pre-restore backup of existing target failed |

### What is restored

The restore operation copies the backup file directly to the target path. It includes:
- All memory records
- Revision history
- Outbox events
- Projection state

After restore, run `make reindex` to rebuild Qdrant vector projections and Obsidian files from the restored SQLite data.

### Verify before restoring

Always verify the backup file exists and is non-empty before restoring:

```bash
ls -la ./data/memory.backup.db
```
