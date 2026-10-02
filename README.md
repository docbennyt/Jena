# Jena

Jena is a local-first workstation control plane for Windows. It remembers project and recovery state, explains storage, applies policy, orchestrates mature tools, verifies outcomes, and records what happened.

Jena is not a replacement for Windows Explorer, 7-Zip, Git, or cloud clients. Explorer handles ordinary file browsing, 7-Zip handles archive machinery, Git handles version control, and Jena supplies the workstation memory and safety boundary.

It is not an aggressive PC cleaner and never permanently deletes personal files automatically.

The current packaged release is v0.3.2. The proposed next milestone is v0.4.0 Control Plane Core; its contract is documentation-first and implementation has not started.

## Current Capabilities

- Shows real C: drive capacity, free space, and a configurable target reserve.
- Generates ranked low-risk storage opportunities with space gain, risk, effort, reasons, recovery path, and confidence.
- Identifies protected local-only items from the latest scan so the user does not mistake "large" for "safe to remove."
- Scans Downloads or a chosen folder without requiring admin rights.
- Moves normal cleanup selections to the Windows Recycle Bin.
- Uses 7-Zip for project archive creation, listing, integrity testing, and staged extraction when available.
- Creates recovery-compatible ZIP archives by default, with 7z available as a smaller option.
- Recommends old Inactive projects for review without archiving anything automatically.

## Current Working Flow

1. Launch the app.
2. Click **Scan Downloads**.
3. Review findings.
4. Select safe items.
5. Click **Move to Recycle Bin**.
6. Confirm the action.
7. Activity records the operation.

## Development

```powershell
python -m pip install -r requirements.txt
.\scripts\run-dev.ps1
```

Run tests:

```powershell
$env:PYTHONPATH="$PWD\source"
python -m pytest tests -q
```

## Build

```powershell
.\scripts\build.ps1
```

The portable build is written to `dist\Jena`.

## Product Direction

- [Product rules](docs/PRODUCT-RULES.md)
- [Product vision](docs/PRODUCT-VISION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Canonical user flows](docs/USER-FLOWS.md)
- [Control-plane pivot ADR](docs/decisions/002-jena-control-plane-pivot.md)
- [Current roadmap](docs/ROADMAP.md)
- [Code audit](docs/CODE-AUDIT-CONTROL-PLANE-PIVOT.md)
