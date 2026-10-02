# Jena Product Rules

This document is a highest-authority product contract. When another product document conflicts with it, this document and accepted architecture decision records take precedence.

VALUE IS KING.

DO NOT REBUILD WHAT MATURE TOOLS ALREADY DO WELL.

JENA IS NOT THE FILE MANAGER.

JENA IS THE WORKSTATION MEMORY, POLICY ENGINE,
STORAGE INTELLIGENCE LAYER AND SAFE EXECUTOR.

EXPLORER BROWSES.

7-ZIP COMPRESSES.

GIT VERSIONS.

CLOUD PROVIDERS STORE.

AI REASONS.

THE USER DECIDES.

JENA KNOWS, VALIDATES, ACTS AND REMEMBERS.

If a feature adds complexity without enough unique user value:

DO NOT BUILD IT.

## Rule 1 - Value Is King

Every feature must justify itself through measurable user value. A feature should materially improve at least one of:

- storage recovered;
- storage understood;
- recoverability;
- organization;
- cognitive load;
- automation safety;
- project lifecycle management;
- backup certainty;
- the ability for an AI agent to manage the workstation safely.

If it does none of these, do not build it.

## Rule 2 - Do Not Rebuild Mature Plumbing

Prefer integrating proven tools over recreating them. Explorer owns ordinary file browsing. 7-Zip owns compression machinery. Git owns version control. Cloud clients and providers own cloud transport. Windows owns the filesystem, Shell, credential storage, and Recycle Bin. Jena orchestrates them.

## Rule 3 - Jena Is the Workstation Memory

Jena should remember facts humans otherwise forget:

- where projects live;
- which projects are active, paused, inactive, ignored, or archived;
- which projects must never be archived;
- what was archived and where the archive lives;
- which provider and account contain an offloaded archive;
- whether an archive was verified and restore-tested;
- what was removed locally and how it can be restored;
- what storage actions occurred;
- what policies the user established.

## Rule 4 - Jena Must Be Powerful Without AI

AI is optional. Without AI, Jena must still provide storage analysis, a project registry, storage opportunities, safe archive and restore, project lifecycle management, operation history, deterministic recommendations, policy enforcement, and recovery information.

## Rule 5 - AI Reasons; Jena Validates and Acts

AI must never become Jena's source of truth. The architecture is:

1. JENA KNOWS.
2. AI REASONS.
3. THE USER DECIDES.
4. JENA VALIDATES.
5. JENA ACTS.
6. JENA REMEMBERS.

## Rule 6 - Safety Is Architectural

- Ordinary deletion uses the Windows Recycle Bin.
- Permanent deletion requires a separate, explicit confirmation and is never automatic.
- Project source removal after archive occurs only after successful archive verification.
- Cloud or offload source removal occurs only after destination verification.
- Existing destinations are never overwritten silently.
- AI never receives unrestricted destructive filesystem access through Jena.
- User-protected source code, documents, databases, design sources, photographs, assignments, and repositories are never treated as disposable merely because they are large or old.

## Rule 7 - One Business Logic Layer

The GUI, JSON CLI, automation, future MCP server, and future AI adapters must all call the same Jena Core service layer. Never implement separate archive, delete, project, policy, or storage logic in each interface.

## Rule 8 - Everything Expensive Is Asynchronous

Filesystem scans, compression, hashing, Git inspection, backup, restore, and cloud operations must run through the task system and must never freeze the UI. Helper processes must remain hidden in the packaged Windows application.

## Rule 9 - Explain Every Recommendation

Every recommendation must expose:

- WHAT;
- WHY;
- SPACE GAIN;
- RISK;
- RECOVERY PATH;
- CONFIDENCE.

## Rule 10 - Reliability Beats Feature Count

If a feature is not reliably working in the packaged application, it is not complete. Source tests alone do not satisfy the release bar.

## Rule 11 - Real Workflow Beats Synthetic Success

Fixtures prove deterministic invariants. Packaged-app testing proves integration. When a feature operates over user-selected real-world structures, at least one safe, non-destructive acceptance test should use the actual shape of the user's environment where practical.

Never perform destructive tests on real data. Project discovery can be tested against real project libraries because it only reads filesystem structure. Delete, recycle, archive, restore, and cleanup workflows must use disposable fixtures or copies.

## Product Value Test

Before implementing any substantial feature, answer these questions in its issue, design note, or ADR:

1. Can Windows, Explorer, 7-Zip, Git, or cloud software already do this well? If yes, integrate or delegate unless Jena adds unique value.
2. Does Jena need this information later? If yes, Jena may need to record or observe it even when another tool performs the operation.
3. Does the feature save meaningful time, storage, or mental effort? If no, do not prioritize it.
4. Does it improve recovery safety? If yes, it has high potential value.
5. Does it make future AI reasoning safer or more accurate? If yes, it has potentially high strategic value.

Prioritize work as:

- P0 - Core safety and correctness.
- P1 - High recurring user value.
- P2 - Useful enhancement.
- P3 - Convenience and polish.

Never implement P3 work while P0 or P1 problems remain.

## Feature Value Dimensions

Score every proposed substantial feature from 0 to 5 on each dimension:

| Dimension | Question |
| --- | --- |
| Recurring value | How often does this improve a real user workflow? |
| Storage impact | How materially can it recover or explain storage? |
| Cognitive load reduction | How much uncertainty or manual tracking does it remove? |
| Recovery and safety value | How much does it improve reversibility, verification, or protection? |
| AI and automation enabling value | Does it create trustworthy facts or bounded operations? |
| Implementation cost | How expensive is it to build and verify? |
| Maintenance cost | How much ongoing compatibility and support burden does it create? |

Do not reduce these dimensions to a single magic number. Make the tradeoffs explicit. Reject low-value, high-cost features unless they are strategically necessary.

High-value examples include the Project Registry, verified archives, backup/offload ledger, target free-space planner, recoverability information, storage opportunities, Never Archive policies, and a structured AI interface.

Usually low-value examples include building a video player, PDF viewer, image viewer, file navigator, text editor, archive codec, Git UI, elaborate animation, or a dashboard dominated by counters. A concrete Jena-specific use case must justify any exception.

## Ultimate Product Test

A Jena feature is valuable when it materially improves one or more of these questions:

- What is using my disk?
- What can I safely remove?
- What can be regenerated?
- Which project costs the most storage?
- Which project have I not worked on?
- What should I archive?
- Where did an archived project go?
- Can I restore it?
- How much space do I need?
- What is the safest plan to recover it?
- Which policy prevents this action?
- Can an AI reason over this state safely?

If a proposed feature does not improve one of these questions, challenge whether Jena should contain it.

## Documentation Authority

Product direction is interpreted in this order:

1. `PRODUCT-RULES.md` and accepted ADRs;
2. `PRODUCT-VISION.md`;
3. `ARCHITECTURE.md` and `USER-FLOWS.md`;
4. the active phase in `ROADMAP.md`;
5. historical release and verification records.

Every major product change must update the affected rules, vision, architecture, flows, roadmap, and ADR. Historical records remain intact but must be marked when their direction is superseded.
