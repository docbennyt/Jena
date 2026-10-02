# ADR-001: Use 7-Zip Behind Jena's CompressionService

## Status

Accepted

## Date

2026-10-02

## Context

Jena must create and restore verified project archives without maintaining a second archive implementation. It also needs archive listing for bounded archive inspection, cancellable background execution, no visible console windows, and portable offline operation.

Jena remains responsible for policy: project eligibility, dependency/cache exclusions, manifest hashes, verification state, restore staging, collision handling, and the Recycle Bin action after successful verification.

## Decision

Use the unmodified 7-Zip command-line engine behind `core.compression.CompressionService` behavior for:

- archive listing;
- ZIP and 7z creation;
- archive integrity testing;
- staged extraction.

The adapter passes argument arrays directly to `subprocess.Popen` with `shell=False` and `CREATE_NO_WINDOW` on Windows. Operations accept Jena `CancellationToken` objects and are called from `TaskManager` jobs.

Jena validates archive member paths before extraction, refuses overwrites, writes an external versioned manifest, runs `7z t`, compares the exact member/size map, extracts to a temporary verification directory, and checks every SHA-256 before post-archive behavior.

The built-in Python ZIP implementation remains a recovery fallback when 7-Zip is unavailable. It cannot create or extract 7z archives.

## Default Format

Balanced ZIP (`-mx=5`) is the default. Balanced 7z is an explicit compact option.

The 2026-10-02 benchmark used Jena's Python source, a TypeScript monorepo fixture, and a mixed source/assets fixture. Each fixture/format pair ran three times and the median elapsed time was used. Across 13,801,814 input bytes:

- ZIP: 6,937,132 bytes in 0.8339 seconds.
- 7z: 6,447,031 bytes in 1.5170 seconds.
- 7z saved 7.06% versus ZIP and took 1.82 times as long.

ZIP wins as the recovery-first default because Windows can open it without Jena or 7-Zip. The TypeScript fixture showed that 7z can be dramatically smaller for repetitive source, so the compact option is retained.

Raw results are stored in `docs/compression-benchmark.json` and can be regenerated with `python scripts/benchmark-compression.py`.

## Licensing and Packaging

Jena vendors unmodified x64 runtime files from 7-Zip 26.03: `7z.exe`, `7z.dll`, and upstream `License.txt`.

The official release installer SHA-256 is:

`0859C524B8A63551848F0C246ABDDCB1D0B7B656B0FBFE879F8D85E61A9E6EDD`

The downloaded file matched the checksum published by the official 7-Zip GitHub release and SourceForge. The portable package reproduces the upstream license at `tools\7zip\License.txt`, and Jena's license notice states that it uses LGPL-licensed 7-Zip and links to the source.

Sources:

- https://www.7-zip.org/
- https://www.7-zip.org/faq.html
- https://github.com/ip7z/7zip/releases/tag/26.03
- https://docs.python.org/3/library/subprocess.html#subprocess.CREATE_NO_WINDOW

## Consequences

- Portable Jena archive behavior is independent of a machine-wide 7-Zip installation.
- ZIP archives remain broadly recoverable even if Jena is unavailable.
- 7z archives require Jena or another 7z-compatible tool.
- The x64 portable package grows by about 2.4 MB before outer ZIP compression.
- ARM64/x86 packages need architecture-matching 7-Zip binaries in a future packaging pass.
- ADR-002 narrows archive browsing to a recovery or verification aid; it must not grow into a general Workspace Browser.
