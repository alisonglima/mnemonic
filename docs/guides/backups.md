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
