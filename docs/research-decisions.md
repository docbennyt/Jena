# Research Decisions

## Windows Recycle Bin

Current choice: use `send2trash`, which delegates to platform recycle/trash behavior instead of deleting files directly.

Reason: It is a small open-source dependency and is safer than custom delete/move logic for normal user cleanup.

Open research:
- Native shell restore tracking for Jena-owned recycle operations.
- Better receipts for Recycle Bin item IDs, if available.

## Backup Versus Sync

Current position: Jena does not yet treat synced folders as backups.

Reason: Sync can propagate deletion and is not equivalent to an independent recoverable copy.

Open research:
- OneDrive Files On-Demand detection and "free up space" behavior.
- Google Drive for desktop online-only semantics.
- Dropbox online-only behavior.

## Recovery Confidence

Current choice: model confidence explicitly with levels from `UNPROTECTED` through `RESTORE_TESTED`.

Reason: A binary "backed up" flag would create false safety.

Current implementation:
- Regenerable development data is marked recoverable by recreation path.
- Protected personal/source documents remain `UNPROTECTED` until a backup ledger exists.
