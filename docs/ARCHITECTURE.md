# Jena Architecture

## Architectural Intent

Jena is a local-first workstation control plane. The UI is a thin decision surface over one reusable Jena Core. Core owns facts, policy, planning, semantic operations, verification, and durable memory. Mature tools perform commodity operations.

```text
                         +---------------+
                         |     User      |
                         +-------+-------+
                                 |
                         +-------v-------+
                         |    Jena UI    |
                         | thin control  |
                         | surface       |
                         +-------+-------+
                                 |
                +----------------v----------------+
                |             JENA CORE           |
                |                                 |
                | Inventory        Policies       |
                | Project Registry Storage Plan   |
                | Archive Ledger   History        |
                | Opportunities    Verification   |
                +----------------+----------------+
                                 |
               +-----------------+-----------------+
               |                 |                 |
          +----v-----+      +----v-----+      +----v-----+
          | Explorer |      |  7-Zip  |      |   Git    |
          +----------+      +----------+      +----------+
                                 |
                     Future: cloud providers
```

## Authority and Interfaces

Jena Core is the only business-logic layer. The desktop GUI, JSON CLI, later automation, later MCP server, and later AI adapters all call the same services.

No interface may implement its own archive, restore, recycle, project-state, storage-accounting, policy, or approval rules.

## Core Domains

### Inventory

Collects bounded, explainable local facts about volumes, Project Libraries, projects, Downloads, and candidate storage. Inventory records canonical paths and stable identities so physical data is not counted more than once.

### Project Registry

Stores one durable record per actual project root, not per library root or dependency package. The target record includes `project_id`, root path, display name, technology, Git state, total and categorized bytes, lifecycle state, meaningful activity, pinned and Never Archive policy, and archive or recovery references.

Lifecycle states are Active, Paused, Inactive, Archived, Never Archive, and Ignored. Explicit user decisions override heuristics.

### Storage Model

Maintains volume capacity, free space, target reserve, gap to target, and uniquely counted storage classes: regenerable, temporary, reviewable, protected, and project storage. Storage reporting is byte-based; finding counts are diagnostic only.

### Opportunity Engine

Produces deterministic `StorageOpportunity` records containing identity, type, description, unique space gain, risk, effort, confidence, reason, recovery path, affected item identities, and an allowed semantic action.

### Storage Planner

Selects allowed opportunities until a requested free-space target is met or no valid opportunities remain. It respects Active, Never Archive, Pinned, protected paths, user exclusions, approval state, and unique-byte accounting.

### Policies

Stores durable user decisions such as target free space, Project Libraries, protected paths, lifecycle overrides, archive exclusions, and post-archive behavior. Policies are enforced by Core, not merely represented in UI controls.

### Archive Ledger and Verification

Jena chooses what to archive, exclusions, destination, verification requirements, and post-archive behavior. ADR-001's CompressionService delegates creation, listing, integrity testing, and extraction to 7-Zip. Jena owns manifests, hashes, verification state, restore staging, collision refusal, and the durable archive record.

### Operation History

Records semantic intent, affected identities, plan, approval, start and completion times, result, verification evidence, errors, and recovery information. History must be useful to both the user and future bounded automation.

## External Tool Boundaries

### Windows Explorer

Explorer owns normal navigation, thumbnails, previews, file opening, drag and drop, and manual file operations. Jena invokes focused actions: Open in Explorer, Reveal Item, Open Project Folder, Open Archive Location, and Open Recycle Bin where useful.

### 7-Zip

7-Zip owns archive codecs and archive mechanics. Calls use argument arrays, hidden helper processes, cancellation, TaskManager execution, and post-operation validation. Jena never equates a zero process exit code with complete archive verification.

### Git

Git owns repository state and version control. Jena may inspect structured Git state to inform project safety, but it does not become a Git client or mutate a repository without an explicit, approved workflow.

### Cloud Providers

Future integrations delegate transport and synchronization to provider-native capabilities. Jena will remember provider, account, remote path, verification, and recovery state. Cloud work is outside v0.4.0.

## Execution Model

All potentially expensive operations run through TaskManager with explicit state, progress, cancellation, and UI-safe event delivery. This includes discovery, size analysis, hashing, Git inspection, archive, restore, and future provider operations.

Write operations are semantic requests, not arbitrary paths plus shell commands. Core validates current state and policy immediately before execution. Destructive operations require approval; ordinary removal uses the Recycle Bin; project-source removal follows verified archiving only.

## Persistence

The current JSON and SQLite stores are migration inputs, not separate sources of truth. v0.4.0 should converge them behind repositories or services that expose stable records for projects, policies, archives, opportunities, and operations. The GUI and CLI must not read or write persistence directly.

## v0.4.0 Boundary

The proposed v0.4.0 Control Plane Core contains:

1. reliable Project Registry;
2. reliable, non-duplicating local storage model;
3. deterministic StorageOpportunity engine;
4. target free-space planner;
5. the accepted verified archive/restore integration;
6. persistent workstation policies;
7. durable operation history;
8. a thin decision-oriented UI;
9. Explorer delegation helpers;
10. a JSON CLI foundation using the same services.

It excludes cloud integrations, MCP, AI chat, aggressive autoarchive, permanent automatic deletion, and elaborate shell extensions.
