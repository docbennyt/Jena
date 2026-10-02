# Product Decisions

## Decision: Home Must Recommend, Not Merely Count

Problem: The user can be critically low on storage and still face thousands of findings without knowing what to do first.

User pain: Raw scan data increases cognitive load when the laptop is nearly full.

Options considered:
- Keep dashboard counters only.
- Add an AI chat panel.
- Build deterministic opportunity records first.

Chosen approach: Jena now creates structured opportunities from trusted local findings before any AI layer exists.

Why: The app must remain useful offline and without AI, while exposing reliable state for future AI reasoning.

Failure modes:
- Opportunities can overstate safety if recovery paths are vague.
- Local-only warnings are incomplete until backup/offload ledger exists.

How tested:
- Unit tests cover storage states, recovery confidence, unique recoverable accounting, and ranked opportunity generation.
- Packaged Jena.exe launch is verified by `scripts/release.ps1`.

## Decision: Recycle Bin Remains The Normal Cleanup Action

Problem: Users need simple cleanup without permanent loss.

Chosen approach: Normal cleanup uses Windows Recycle Bin via `send2trash`.

Why: It matches user expectations and preserves a familiar recovery path.

Failure modes:
- Recycle Bin restore is outside Jena's direct control for now.
- Protected items remain blocked by policy.

How tested:
- Recycle wrapper uses injected sender in tests so no personal files are recycled.

## Decision: Reliability Patch Uses Background Jobs For Filesystem Work

Problem: Large Project Library selection could make the desktop UI appear Not Responding.

Chosen approach: Jena now uses a reusable TaskManager with explicit task states, cancellation tokens, worker threads, and queue-based UI updates through Tkinter polling.

Why: Tkinter widgets must stay on the main thread, while project discovery, size analysis, previews, archive/restore, and delete operations can be expensive.

Failure modes:
- A single filesystem call can still take time to return, but cancellation stops further scheduling and leaves discovered results usable.
- Existing scan logic already used a worker thread; future work should migrate all long-running workflows to TaskManager for consistent state reporting.

How tested:
- Unit tests prove TaskManager work runs off the calling thread and reports progress/completion events.
- Project Library tests cover dependency pruning, broad library selection, monorepo behavior, and cached analysis.

## Decision: Preview Dependencies Stay Local And Purpose-Built

Status: **SUPERSEDED AS A STRATEGIC PRODUCT DIRECTION by ADR-002.**

Historical note: this decision accurately records the verified v0.3.1 implementation. Jena will not expand these helpers into an Explorer Core, Workspace Browser, media viewer, or general document viewer. Ordinary inspection is delegated to Explorer and registered Windows applications. Existing helpers remain until each replacement path is verified; bounded archive inspection may remain where it adds recovery or verification value.

Problem: Users could not identify images, videos, or documents before deletion.

Options considered:
- Shell-only previews.
- VLC/OpenCV-style full media stack.
- Small purpose-built preview libraries.

Chosen approach:
- Pillow for image thumbnails and EXIF orientation.
- PyMuPDF for first-page PDF thumbnails/text.
- python-docx for DOCX text extraction.
- openpyxl for XLSX worksheet samples.
- safe ZIP/XML parsing for PPTX slide text.
- imageio-ffmpeg for video thumbnails without requiring VLC or system ffmpeg.

Why: This gives useful recognition previews while avoiding Office automation, macro execution, OpenCV, VLC, or cloud services.

Measured impact:
- PyMuPDF wheel download: about 20 MB.
- imageio-ffmpeg wheel download: about 31 MB.
- Office text libraries are comparatively small; lxml is about 4 MB.

Failure modes:
- Preview is recognition-oriented, not perfect document layout reproduction.
- Unsupported formats fall back to metadata plus Open/Open Location/Copy Path actions.

How tested:
- Disposable fixtures generate image, video, PDF, DOCX, XLSX, PPTX, text, and ZIP files and verify useful preview output.
