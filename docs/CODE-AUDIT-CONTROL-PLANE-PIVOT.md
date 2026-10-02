# Code Audit: Control Plane Pivot

Date: 2026-10-02

## Purpose

This audit classifies the current v0.3.2 implementation against ADR-002. It authorizes no deletion. Functioning code remains until a delegation or replacement path exists and regression tests prove required behavior remains available.

Classifications:

- **KEEP** - aligned and reusable now.
- **REFACTOR** - valuable behavior whose boundary or model must change.
- **DELEGATE** - replace product ownership with a mature external tool while retaining focused orchestration.
- **DEPRECATE** - stop expanding as a product direction; keep temporarily while migration is proven.
- **REMOVE LATER** - remove only after dependencies and tests no longer require it.

## Executive Findings

The strongest existing assets are TaskManager, CompressionService and the vendored 7-Zip backend, verified project archive/restore, project discovery and size breakdown fixtures, Recycle Bin integration, filesystem safety checks, deterministic opportunity groundwork, settings, and operation persistence.

The largest architectural issue is `ui/main_window.py`: it directly coordinates persistence, scanning, preview, project analysis, archive, restore, delete policy, and presentation. v0.4.0 should move those decisions behind reusable services before adding a JSON CLI.

The generalized preview stack is the main superseded direction. It is tested and should not be deleted immediately, but Jena should stop adding media/document/file-browser capability and delegate ordinary inspection to Explorer. The small archive-content tree may remain only when it contributes to archive verification or recovery.

## Source Module Inventory

| Module | Classification | Reason and next action |
| --- | --- | --- |
| `source/app.py` | REFACTOR | Keep the packaged entry point and test harness flags. Add a real JSON CLI only after Core services exist; both GUI and CLI must call the same application service boundary. |
| `source/version.py` | KEEP | Single version constant remains useful. Do not bump until an accepted, verified milestone has matching source, commit, and artifacts. |
| `source/core/__init__.py` | KEEP | Package boundary is harmless; keep exports minimal. |
| `source/core/tasks.py` | KEEP | TaskManager, cancellation, task states, and queue events directly satisfy the asynchronous-work rule. Extend only through stable task contracts. |
| `source/core/compression.py` | KEEP | Accepted by ADR-001. CompressionService and hidden 7-Zip subprocess behavior remain the archive primitive; do not reimplement codecs. |
| `source/core/project_detector.py` | KEEP / FIX | Marker detection and dependency pruning are useful. Harden library-root versus project-root rules, monorepo identity, stable IDs, and Git-state inspection before expanding discovery. |
| `source/core/project_library.py` | REFACTOR | Preserve discovery, categorized byte accounting, state persistence, archive verification, staging restore, and recommendations. Split registry, analyzer, archive ledger, and archive application services; add Paused and Ignored states, pinned policy, meaningful activity, and stable identity. |
| `source/core/workstation.py` | KEEP / REFACTOR | Existing VolumeState, recovery confidence, unique recoverable summing, and opportunity groundwork align with the pivot. Replace the narrow `Opportunity` model with the full StorageOpportunity contract and add an exact policy-aware planner. |
| `source/core/scanner.py` | REFACTOR | Preserve bounded local inventory and error handling. Reframe generic findings as inputs to explicit inventory/storage domains and guarantee canonical unique-byte accounting. |
| `source/core/classifiers.py` | REFACTOR | Keep useful local classifications, but make recovery state and policy first-class. A filename or age alone must not imply disposal safety. |
| `source/core/downloads.py` | KEEP / REFACTOR | Categorized Downloads and explanations remain valuable. Move them behind a Downloads service and generate policy-aware opportunities rather than exposing raw finding mechanics as the product. |
| `source/core/duplicates.py` | KEEP | Hash-based duplicate evidence is useful storage intelligence. It remains review-only and lower priority than Project Registry and exact accounting. |
| `source/core/file_actions.py` | KEEP / REFACTOR | Preserve path deduplication, risk planning, Recycle Bin delegation, and receipts. Expose bounded semantic operations through Core. Permanent deletion must remain separately gated and outside automatic planning. |
| `source/core/operations.py` | KEEP / REFACTOR | Existing recycle/review/restore receipts are the seed of OperationService. Consolidate operation validation and history here instead of calling write helpers directly from UI. |
| `source/core/safety.py` | KEEP | Protected-path and review safeguards remain core policy inputs. Integrate them with the persistent Workstation Policy Profile. |
| `source/core/models.py` | REFACTOR | Existing findings and risk levels are migration inputs. Add stable project, policy, archive, opportunity, and operation contracts without creating parallel GUI-specific models. |
| `source/core/preview.py` | DELEGATE / DEPRECATE | Stop expanding generalized image, video, PDF, Office, text, and file previews. Use Explorer for ordinary inspection. Retain only bounded helpers with proven Jena-specific value during migration. |
| `source/storage/database.py` | REFACTOR | Keep SQLite and operation history capability. Introduce repository boundaries and migrations for Project Registry, policies, archive ledger, and operation receipts; UI must not access the database directly. |
| `source/storage/settings.py` | KEEP / REFACTOR | Preserve durable settings and safe defaults. Evolve into a typed policy repository supporting multiple Project Libraries, exclusions, pinned state, target reserve, and archive policy. |
| `source/storage/__init__.py` | KEEP | Package boundary remains useful. |
| `source/ui/main_window.py` | REFACTOR | Thin this large coordinator into screens that call Core services. Remove direct persistence and policy decisions. Delegate ordinary file inspection to Explorer. Do not add Back/Forward/Up or generalized Workspace Browser behavior. |
| `source/ui/dialogs.py` | KEEP / REFACTOR | Keep focused approval and error dialogs. Align language with semantic actions and centralized policy; avoid generic permanent-delete affordances in normal flows. |
| `source/ui/__init__.py` | KEEP | Package boundary remains useful. |
| `source/utils/disk.py` | KEEP | Volume metrics are required; prove exact behavior with known-byte fixtures and handle Windows volume semantics explicitly. |
| `source/utils/formatting.py` | KEEP | Presentation utility is low-cost and reusable. |
| `source/utils/labels.py` | KEEP / REFACTOR | Retain only as display mapping for Core enums; do not let labels become policy logic. |
| `source/utils/paths.py` | KEEP / REFACTOR | Known-folder and portable-data paths remain useful. Add Shell helpers behind a focused Explorer delegation service rather than UI calls. |
| `source/utils/__init__.py` | KEEP | Package boundary remains useful. |
| `source/selftest.py` | KEEP / REFACTOR | Disposable packaged-app evidence is essential. Replace preview-centric gates over time with Project Registry, storage arithmetic, policy, GUI/CLI parity, archive ledger, and restart persistence gates. |

## UI and Preview Disposition

| Capability | Classification | Migration condition |
| --- | --- | --- |
| General Workspace Browser / Explorer Core | DEPRECATE | No further development. Use Explorer delegation. There is no standalone browser module today; related archive-tree and preview controls live in `main_window.py`. |
| Internal image preview | DELEGATE / DEPRECATE | Open or reveal in Explorer. Remove only after cleanup review remains safe and tested. |
| Internal video thumbnail/viewing | DELEGATE / DEPRECATE | Open or reveal in Explorer. Do not build playback. |
| Internal PDF rendering | DELEGATE / DEPRECATE | Open in the registered Windows application or Explorer preview. |
| Internal Office text preview | DELEGATE / DEPRECATE | Open in the registered Windows application. |
| Internal text preview | DELEGATE / DEPRECATE | Open in the registered application unless a bounded verification flow needs text evidence. |
| Archive content tree | KEEP / REFACTOR | Keep only as a bounded archive/restore aid if it helps verification or recovery; it must not grow into general file navigation. |

## Supporting Assets

| Asset | Classification | Reason and next action |
| --- | --- | --- |
| `vendor/7zip/*` | KEEP | Accepted, licensed, offline archive primitive. Continue packaging the unmodified matching runtime and upstream license. |
| `scripts/build.ps1`, `clean-build.ps1`, `release.ps1`, `run-dev.ps1` | KEEP / REFACTOR | Preserve reproducible packaging and evidence. Later require commit/version/artifact parity once Git exists. |
| Existing `tests/` | KEEP / REFACTOR | Preserve regression coverage. Add service and fixture coverage at each v0.4.0 gate; retire preview tests only with the associated capability. |
| Preview-only dependencies in `requirements.txt` | REMOVE LATER | Pillow, PyMuPDF, Office parsers, and imageio-ffmpeg remain until preview routes and tests are deliberately migrated. Then remove unused packages to reduce package and maintenance cost. |
| `Jena.spec` and `portable.flag` | KEEP / REFACTOR | Preserve portable packaging; update bundled inputs only when module/dependency migration is verified. |
| v0.3.x verification records | KEEP | Historical release evidence. Add superseded-direction notices where needed; never rewrite the evidence as if old builds had the new architecture. |

## Missing v0.4.0 Boundaries

The current code does not yet have distinct Project Registry, Storage Model, Storage Planner, PolicyService, Archive Ledger, Explorer delegation, or public JSON CLI services. These are refactoring targets, not permission to implement them in parallel.

The current `ProjectState` lacks Paused and Ignored. Project records lack stable IDs, meaningful activity, pinned state, and structured Git state. Settings support one library root. Opportunities do not yet encode affected stable identities or possible semantic actions. The database stores scans and generic operation payloads but is not yet the durable control-plane ledger.

## Safe Migration Order

1. Establish Git and ignore private/runtime data.
2. Correct and persist the Project Registry behind tests and packaged fixtures.
3. Establish unique-byte Storage Model contracts.
4. Build deterministic opportunities and the target planner.
5. Wrap existing archive, file action, settings, and history behavior behind shared services.
6. Thin the GUI and add Explorer delegation.
7. Add the JSON CLI against the same services.
8. Only then remove obsolete preview UI and dependencies, one verified slice at a time.

No code removal is approved by this audit.
