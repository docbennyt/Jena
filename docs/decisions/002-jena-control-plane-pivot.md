# ADR-002: Jena Is a Workstation Control Plane, Not a File Manager

## Status

Accepted

## Date

2026-10-02

## Context

Earlier Jena versions moved toward an internal Explorer-style browsing and preview experience. That direction required Jena to duplicate filesystem navigation, previews, folder browsing, media handling, document rendering, navigation history, and related behavior already solved by Windows Explorer and specialized tools.

The v0.3.1 preview work improved recognition before cleanup and remains valid historical engineering. However, expanding it into an Explorer Core or general Workspace Browser would add implementation and packaging cost without proportionate unique user value. It would also divert effort from Jena's unproven high-value responsibilities: persistent workstation knowledge, trustworthy storage accounting, project lifecycle, recoverability, policy, and verified orchestration.

## Decision

Jena will be a local-first workstation control plane. It will delegate ordinary filesystem interaction to Explorer and mature tools while focusing engineering on:

- persistent workstation knowledge;
- storage reasoning and recovery planning;
- project registry and lifecycle;
- verified archive and restore;
- backup and offload tracking;
- policy enforcement;
- operation history and verification;
- bounded automation;
- a structured future AI harness.

Explorer remains the primary interactive filesystem browser. Jena provides focused shell actions such as Open in Explorer, Reveal Item, Open Project Folder, Open Archive Location, and Open Recycle Bin where useful.

The internal Workspace Browser and generalized internal preview stack are no longer strategic product requirements. Existing preview code is not deleted by this decision. It may remain temporarily when tested, low-maintenance, or uniquely useful to a bounded Jena workflow, such as showing verification-relevant archive contents.

Jena retains and builds on reusable components including TaskManager, CompressionService, the 7-Zip integration, project detection and analysis, archive verification and restore, filesystem safety helpers, operation logging, and storage analysis.

## Alternatives Considered

### Continue Explorer Core

Rejected because it duplicates mature Windows behavior, expands the compatibility surface, increases package size, and does not address Jena's most valuable unanswered questions.

### Remove all preview and browsing code immediately

Rejected because the existing work is tested and some bounded preview behavior may still support safety. Removal must wait for an established delegation path and regression proof that no required workflow disappears.

### Build an AI-first shell

Rejected for the current phase. AI must reason over trusted Jena Core facts and operations; it cannot compensate for an unreliable storage model, project registry, or policy layer.

## Consequences

- Jena's UI becomes a smaller decision-oriented control surface.
- Explorer remains the main place for manual inspection and ordinary file management.
- Internal preview features are deprecated as a general product direction and reviewed case by case.
- The accepted 7-Zip CompressionService remains the archive primitive described by ADR-001.
- GUI, JSON CLI, later automation, MCP, and AI adapters must share one core service layer.
- v0.4.0 prioritizes Project Registry correctness, storage accounting, deterministic opportunities, free-space planning, policies, verified archive/restore, operation history, Explorer delegation, and a JSON CLI foundation.
- Cloud providers, MCP, AI chat, aggressive autoarchive, and elaborate shell integration remain later work.

## Supersedes

This ADR supersedes any prior product direction that treats Explorer Core, Workspace Browser, Back/Forward/Up navigation, generalized internal previews, or a Jena file manager as strategic requirements. Historical release documents remain as records of what was built and verified.
