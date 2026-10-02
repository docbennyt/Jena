# Jena Roadmap

The roadmap is ordered by value and readiness, not by how much code already exists. A phase begins only when its inputs are reliable and its Product Value Test is favorable.

## Phase A - Jena v0.4.0 Control Plane Core

Goal: establish a trustworthy, local-first control plane using one service layer.

1. Git baseline and repository hygiene before implementation.
2. Project Registry with correct project roots, durable lifecycle state, meaningful activity, Git state, and non-overlapping size breakdowns.
3. Local storage model with exact volume metrics and unique physical-byte accounting.
4. Deterministic StorageOpportunity records with reason, gain, risk, confidence, effort, recovery path, and allowed action.
5. Target free-space planner that respects all policies and calculates expected gain correctly.
6. Preserve and integrate verified archive/restore through the accepted CompressionService and 7-Zip primitive.
7. Persistent workstation policies and operation history.
8. Thin decision-oriented UI for Home, Projects, Archives, Activity, and Settings.
9. Explorer delegation helpers for opening and revealing items.
10. Versioned JSON CLI that calls the same core services as the GUI.

Phase A excludes cloud providers, MCP, AI chat, aggressive autoarchive, elaborate shell extensions, and automatic permanent deletion.

### Phase A Acceptance Gates

- Library roots and dependency packages are never misclassified as projects.
- Large Project Libraries remain responsive.
- Explicit project state and policy persist after process restart.
- Storage categories and plans do not double count physical data.
- Plans never propose prohibited items and their arithmetic is exact.
- Project source is never removed before archive verification.
- Restore uses staging, validates hashes, and refuses collisions.
- GUI and CLI exercise the same service behavior.
- Each accepted step passes unit, integration, packaged EXE, portable ZIP, filesystem/database-effect, persistence, and regression checks as applicable.
- Source, commit, version, portable build, hashes, and verification evidence correspond to the same accepted state.

## Phase B - Backup and Offload Ledger

Track where recoverable data lives, including provider, account, remote path, verification state, restore-test state, local-source state, and recovery procedure. The ledger does not treat synchronization alone as an independent backup.

## Phase C - Cloud Integrations

Integrate mature provider capabilities for OneDrive, Google Drive, Dropbox, or later providers. Prefer native transport and synchronization. Jena owns policy, memory, verification, and recovery metadata rather than rebuilding cloud clients.

## Phase D - AI Harness

Stabilize JSON CLI schemas first, then evaluate MCP, Codex/ChatGPT adapters, and other model integrations. AI receives structured facts and bounded semantic operations, never unrestricted destructive access.

## Phase E - Automation

Add trusted inactive-project recommendations, safe autoarchive, low-storage response, and Downloads policies. Automation requires accurate state, explicit policy, verified destinations, operation receipts, and safe recovery. Last-access timestamps alone never trigger autoarchive.

## Definition of Done

Every engineering step follows:

`UNDERSTAND -> IMPLEMENT -> UNIT TEST -> INTEGRATION TEST -> BUILD PORTABLE JENA -> RUN PACKAGED EXE -> EXERCISE FLOW -> VERIFY FILESYSTEM/DATABASE EFFECT -> RESTART WHEN PERSISTENCE MATTERS -> REGRESSION TEST -> UPDATE DOCS -> COMMIT -> PUSH`

If anything fails, fix, rebuild, and retest. A feature is not complete because source code looks correct or because unit tests pass.
