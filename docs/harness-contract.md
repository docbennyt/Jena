# Harness Contract

Status: foundational v0.3.x contract. `AI-HARNESS-VISION.md` is the current product-level authority; this file remains a compatible technical sketch and is not an instruction to implement MCP or AI in v0.4.0.

Jena Core is the trusted executor. Future AI integrations reason over structured state and request bounded operations; they do not bypass policy.

## Read Model

Initial AI-readable state will include:

- volume state
- target free-space gap
- ranked opportunities
- local-only warnings
- project summaries
- operation receipts

## Opportunity Schema

```json
{
  "id": "dev-caches",
  "title": "Clean regenerable development data",
  "category": "Development caches",
  "space_gain_bytes": 123,
  "user_effort": "One confirmation",
  "risk": "Very low",
  "why": "These are dependency, cache, or build artifacts.",
  "recovery_path": "Recreate with the project package manager or build tool.",
  "confidence_percent": 92,
  "finding_ids": ["..."]
}
```

## Write Boundary

Future plans must be validated by Jena before execution.

Required plan checks:

- state revision still current
- referenced findings/projects exist
- policy allows requested action
- user approval is present for write operations
- no permanent deletion unless the specific post-verified-archive policy allows it

## Privacy

Snapshots must not contain credentials, tokens, private keys, or cloud passwords.
