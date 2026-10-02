from __future__ import annotations

import argparse
import json
import random
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "source"))

from core.compression import ArchiveFormat, SevenZipCompressionService, find_7zip_executable  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Jena's balanced ZIP and 7z project archive profiles.")
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "compression-benchmark.json")
    parser.add_argument("--runs", type=int, default=3, help="Timed runs per fixture and format; medians are reported.")
    args = parser.parse_args()

    executable = find_7zip_executable()
    if executable is None:
        raise SystemExit("7-Zip is required for this benchmark.")
    engine = SevenZipCompressionService(executable)
    with tempfile.TemporaryDirectory(prefix="jena-compression-benchmark-") as temporary:
        work = Path(temporary)
        fixtures = _make_fixtures(work / "fixtures")
        rows = []
        for fixture_name, source in fixtures.items():
            members = _members(source)
            input_bytes = sum((source / relative).stat().st_size for relative in members)
            for archive_format in (ArchiveFormat.ZIP, ArchiveFormat.SEVEN_ZIP):
                runs = []
                archive_bytes = 0
                for run_index in range(max(1, args.runs)):
                    destination = work / "archives" / f"{fixture_name}-{archive_format.value}-{run_index}.{archive_format.value}"
                    result = engine.create(source, members, destination, archive_format, compression_level=5)
                    if not engine.test_archive(destination):
                        raise RuntimeError(f"Integrity test failed for {destination}")
                    archive_bytes = result.archive_bytes
                    runs.append(round(result.elapsed_seconds, 4))
                median_elapsed = statistics.median(runs)
                rows.append(
                    {
                        "fixture": fixture_name,
                        "format": archive_format.value,
                        "files": len(members),
                        "input_bytes": input_bytes,
                        "archive_bytes": archive_bytes,
                        "ratio": round(archive_bytes / input_bytes, 4),
                        "elapsed_seconds_median": round(median_elapsed, 4),
                        "runs_seconds": runs,
                        "throughput_mib_per_second": round(
                            (input_bytes / (1024 * 1024)) / max(median_elapsed, 0.0001),
                            2,
                        ),
                    }
                )

    summary = _summarize(rows)
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "engine": engine.engine_name,
        "profile": "balanced (-mx=5, multithreaded)",
        "fixtures": rows,
        "summary": summary,
        "decision": {
            "default_format": "zip",
            "compact_option": "7z",
            "reason": (
                "ZIP is the recovery-first default because Windows can open it without Jena or 7-Zip. "
                "7z remains the compact option when the measured space saving matters more than native recovery compatibility."
            ),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


def _make_fixtures(root: Path) -> dict[str, Path]:
    python_app = root / "jena-python"
    shutil.copytree(ROOT / "source", python_app)

    typescript = root / "typescript-monorepo"
    for index in range(1200):
        _write(
            typescript / "packages" / f"package-{index // 100}" / "src" / f"module-{index}.ts",
            (f"export function value{index}() {{ return '{index:04d}-jena'; }}\n" * 60),
        )
    _write(typescript / "package.json", '{"private":true,"workspaces":["packages/*"]}')
    _write(typescript / "pnpm-lock.yaml", ("lockfileVersion: '9.0'\nresolution: integrity-sha512-fixture\n" * 30000))

    mixed = root / "mixed-source-assets"
    for index in range(500):
        _write(
            mixed / "src" / f"screen-{index // 50}" / f"view-{index}.tsx",
            (f"export const View{index} = () => <main>Jena {index}</main>;\n" * 50),
        )
    generator = random.Random(314159)
    for index in range(12):
        path = mixed / "assets" / f"asset-{index}.bin"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(generator.randbytes(512 * 1024))
    _write(mixed / "README.md", "# Mixed source and design assets\n" * 2000)
    return {"jena-python": python_app, "typescript-monorepo": typescript, "mixed-source-assets": mixed}


def _members(root: Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())


def _summarize(rows: list[dict]) -> dict:
    summary = {}
    for archive_format in ("zip", "7z"):
        selected = [row for row in rows if row["format"] == archive_format]
        total_input = sum(row["input_bytes"] for row in selected)
        total_archive = sum(row["archive_bytes"] for row in selected)
        total_time = sum(row["elapsed_seconds_median"] for row in selected)
        summary[archive_format] = {
            "input_bytes": total_input,
            "archive_bytes": total_archive,
            "weighted_ratio": round(total_archive / total_input, 4),
            "elapsed_seconds": round(total_time, 4),
            "throughput_mib_per_second": round((total_input / (1024 * 1024)) / max(total_time, 0.0001), 2),
        }
    zip_summary = summary["zip"]
    seven_summary = summary["7z"]
    summary["comparison"] = {
        "seven_zip_space_saving_vs_zip_percent": round(
            (1 - seven_summary["archive_bytes"] / zip_summary["archive_bytes"]) * 100,
            2,
        ),
        "seven_zip_time_multiple_vs_zip": round(
            seven_summary["elapsed_seconds"] / max(zip_summary["elapsed_seconds"], 0.0001),
            2,
        ),
        "native_windows_recovery": {"zip": True, "7z": False},
    }
    return summary


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
