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
