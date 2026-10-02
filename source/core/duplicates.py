from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def duplicate_groups(files_by_size: dict[int, list[Path]], min_size: int = 25 * 1024 * 1024) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = {}
    group_number = 0
    for size, paths in files_by_size.items():
        if size < min_size or len(paths) < 2:
            continue
        by_hash: dict[str, list[Path]] = {}
        for path in paths:
            try:
                by_hash.setdefault(sha256_file(path), []).append(path)
            except OSError:
                continue
        for hashed_paths in by_hash.values():
            if len(hashed_paths) > 1:
                group_number += 1
                groups[f"dup-{group_number}"] = hashed_paths
    return groups
