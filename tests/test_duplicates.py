from pathlib import Path

from core.duplicates import duplicate_groups


def test_duplicates_require_matching_hash(tmp_path: Path):
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    c = tmp_path / "c.bin"
    a.write_bytes(b"same")
    b.write_bytes(b"same")
    c.write_bytes(b"nope")

    groups = duplicate_groups({4: [a, b, c]}, min_size=0)

    assert len(groups) == 1
    assert set(next(iter(groups.values()))) == {a, b}
