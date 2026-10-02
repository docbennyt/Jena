# Changelog

## 0.3.2 - 2026-10-02

### Added
- Added a `CompressionService` boundary with 7-Zip and built-in ZIP engines.
- Added ZIP/7z creation, integrity testing, safe listing, staged extraction, and cooperative cancellation.
- Added read-only archive container trees for ZIP, 7z, RAR, TAR, ISO, and related formats where 7-Zip supports them.
- Added old Inactive project archive recommendations; archive execution still requires user confirmation.
- Added a repeatable ZIP-versus-7z benchmark and recorded the recovery-first default decision.

### Changed
- Project archive manifests now record engine, format, balanced profile, and verification state.
- Archive and restore jobs now pass TaskManager cancellation/progress through the compression engine.

### Security
- Archive extraction validates all member paths and refuses overwrite before extraction.
- Project archive destinations inside the source project are rejected.

## 0.3.1

- Added a reusable background TaskManager for expensive filesystem work.
- Moved Project Library discovery and size analysis off the Tkinter UI thread.
- Added quick bounded-depth project discovery with dependency/cache pruning and streamed project results.
- Added project-analysis caching so returning to Projects does not rescan huge libraries automatically.
- Added reusable local preview support for images, videos, PDFs, DOCX, XLSX, PPTX, text/source files, ZIP archives, audio metadata fallback, and unknown files.
- Added central Windows-style delete routing: Delete moves to Recycle Bin; Shift+Delete permanently deletes after explicit confirmation.
- Added background delete execution for large Recycle Bin and permanent-delete operations.
- Added context-menu filesystem actions that use the same command engine as keyboard shortcuts.
- Preserved the v0.3.0 scope freeze; no cloud, AI/MCP, watchers, or automation expansion.

## 0.2.0

- Renamed the product surface to Jena.
- Merged multiple classifications for one filesystem object into a single finding with multiple tags.
- Fixed recoverable storage accounting so each physical item is counted once.
- Fixed duplicate-space accounting so only extra copies count.
- Prevented dependency packages inside development caches from appearing as user projects.
- Replaced normal cleanup wording with Windows Recycle Bin behavior.
- Removed approved-move mode from the normal UI.
