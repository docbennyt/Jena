# Jena AI Harness Vision

## Status

Design contract only. MCP, AI chat, and model adapters are not part of v0.4.0.

## Principle

AI reasons; Jena validates and acts. Jena Core remains the source of truth and safety boundary.

The future interaction is:

1. AI asks.
2. Jena returns facts.
3. AI proposes.
4. Jena validates.
5. The user approves.
6. Jena acts.
7. Jena verifies and remembers.

## AI May

- query volume, storage, project, archive, policy, and operation state;
- inspect project metadata and recovery information;
- request deterministic plans;
- explain Jena-generated recommendations;
- propose bounded semantic operations;
- observe operation progress and verified receipts.

## AI May Not

- receive unrestricted destructive shell or filesystem access through Jena;
- bypass policy or safety validation;
- claim or synthesize user approval;
- mutate Jena's database directly;
- receive credentials, tokens, private keys, or provider secrets;
- turn a recommendation into execution without the required approval;
- silently broaden paths or operation scope.

## Contract Shape

The first machine-readable contract is the v0.4.0 JSON CLI, not MCP. It should expose versioned schemas for status, projects, opportunities, reclaim plans, archives, policies, and activity. Write requests identify semantic operations and stable record IDs rather than arbitrary shell commands.

Every response should include enough revision or freshness information for Jena to reject stale plans. Every write request is revalidated against current state, policy, approval, and target identity immediately before execution.

## Privacy

AI-facing snapshots exclude file contents by default and never contain credentials, tokens, private keys, cloud passwords, or raw private workstation inventories. Path exposure should be minimized to what the approved workflow requires.

## Why MCP Waits

MCP would amplify the existing core contract. It would not repair unclear services, inconsistent schemas, or unsafe operation boundaries. Jena must first prove stable shared services and JSON contracts through the packaged app and CLI. MCP follows only after those contracts are reliable.

## Automation Boundary

Automation follows trust. Future autoarchive requires accurate activity, explicit policy, candidate selection, plan review rules, archive verification, ledger recording, and a safe source action. Last-access time alone is never sufficient evidence of inactivity.
