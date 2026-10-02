# Jena Product Vision

## Product Definition

Jena is a local-first workstation control plane.

It is not a file manager, not a generic cleaner, and not merely an AI wrapper. Jena is a persistent intelligence and orchestration layer for a Windows workstation.

Its purpose is to know:

- what exists;
- what matters;
- what is active;
- what is regenerable;
- what is protected;
- what is backed up;
- where it is backed up;
- what can safely leave local storage;
- how removed or offloaded data can be recovered.

Jena turns those facts into deterministic recommendations, validates user-approved actions against policy, delegates work to mature platform tools, verifies the result, and records what happened.

Its capability chain is:

`REMEMBER + UNDERSTAND + RECOMMEND + ORCHESTRATE + VERIFY + AUTOMATE SAFELY + EXPOSE TRUSTED CAPABILITIES TO AI`

## Questions Jena Must Answer

Jena should eventually allow either a human or an AI agent to ask:

- Why is my disk full?
- How can I safely recover 20 GB?
- Which projects are inactive?
- Which projects consume the most storage?
- Which projects contain mostly regenerable dependencies?
- What exists only locally?
- Where did I archive HIT-ASA?
- Which provider and account contain that archive?
- Was that archive verified?
- Can it be restored?
- What should remain local?
- What can safely become cold storage?
- Which policy prevents a proposed action?

## Product Boundary

Jena owns workstation memory, project lifecycle, storage intelligence, policy, archive and offload records, verification, recovery information, bounded automation, and the future AI harness.

Jena delegates:

- ordinary navigation, thumbnails, previews, opening, drag and drop, and manual file operations to Windows Explorer;
- compression, extraction, listing, and integrity testing to 7-Zip;
- repository state and version control operations to Git;
- cloud transport and synchronization to provider-native clients and APIs;
- filesystem, process, credential, and Recycle Bin primitives to Windows.

Delegation does not mean ignorance. Jena records the metadata, policy, verification result, and recovery path needed to remain the workstation's trusted memory.

## Local-First Promise

Core inventory, storage reasoning, project management, planning, archive/restore, policies, and operation history work offline. AI and cloud integrations are optional later phases and cannot become prerequisites for core safety or usefulness.

## Success

Jena succeeds when it reduces uncertainty and safely completes high-value workstation workflows. It does not succeed by owning more screens, rendering more file formats, or reporting a larger number of findings.
