from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path

from core.models import Finding, ProjectInfo, RiskLevel, ScanResult
from utils.paths import data_dir


class Database:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or data_dir() / "jena.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.migrate()

    def migrate(self) -> None:
        self.connection.executescript(
            """
            create table if not exists scans (
                id integer primary key autoincrement,
                source_scope text not null,
                root text not null,
                created_at real not null,
                scanned_items integer not null,
                scanned_bytes integer not null,
                error_count integer not null
            );
            create table if not exists findings (
                id text primary key,
                scan_id integer not null,
                payload text not null,
                path text not null,
                name text not null,
                category text not null,
                risk_level text not null,
                size_bytes integer not null,
                recoverable_bytes integer not null
            );
            create table if not exists projects (
                id integer primary key autoincrement,
                scan_id integer not null,
                payload text not null,
                path text not null,
                size_bytes integer not null
            );
            create table if not exists operations (
                id text primary key,
                created_at real not null,
                payload text not null,
                manifest_path text
            );
            """
        )
        self.connection.commit()

    def save_scan(self, result: ScanResult) -> int:
        cursor = self.connection.execute(
            "insert into scans(source_scope, root, created_at, scanned_items, scanned_bytes, error_count) values (?, ?, ?, ?, ?, ?)",
            (result.source_scope, result.root, time.time(), result.scanned_items, result.scanned_bytes, len(result.errors)),
        )
        scan_id = int(cursor.lastrowid)
        self.connection.executemany(
            "insert or replace into findings(id, scan_id, payload, path, name, category, risk_level, size_bytes, recoverable_bytes) values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    finding.id,
                    scan_id,
                    json.dumps(_json_ready(asdict(finding))),
                    finding.path,
                    finding.name,
                    finding.category,
                    finding.risk_level.value,
                    finding.size_bytes,
                    finding.recoverable_bytes,
                )
                for finding in result.findings
            ],
        )
        self.connection.executemany(
            "insert into projects(scan_id, payload, path, size_bytes) values (?, ?, ?, ?)",
            [(scan_id, json.dumps(asdict(project)), project.path, project.size_bytes) for project in result.projects],
        )
        self.connection.commit()
        return scan_id

    def latest_findings(self, source_scope: str | None = None) -> list[Finding]:
        params: tuple = ()
        scope_clause = ""
        if source_scope:
            scope_clause = "where scans.source_scope = ?"
            params = (source_scope,)
        rows = self.connection.execute(
            f"""
            select findings.payload
            from findings
            join scans on scans.id = findings.scan_id
            {scope_clause}
            and scans.id = (select max(id) from scans where source_scope = scans.source_scope)
            order by findings.size_bytes desc
            """.replace("where scans.source_scope = ?\n            and", "where scans.source_scope = ?\n            and"),
            params,
        ).fetchall()
        if not source_scope:
            rows = self.connection.execute(
                """
                select payload from findings
                where scan_id in (select max(id) from scans group by source_scope)
                order by size_bytes desc
                """
            ).fetchall()
        return [_finding_from_json(json.loads(row["payload"])) for row in rows]

    def latest_projects(self) -> list[ProjectInfo]:
        rows = self.connection.execute(
            """
            select payload from projects
            where scan_id in (select max(id) from scans group by source_scope)
            order by size_bytes desc
            """
        ).fetchall()
        return [ProjectInfo(**json.loads(row["payload"])) for row in rows]

    def dashboard_metrics(self) -> dict:
        findings = self.latest_findings()
        recoverable_paths: set[str] = set()
        recoverable = 0
        dev_cache = 0
        duplicate = 0
        for finding in findings:
            if finding.risk_level != RiskLevel.DO_NOT_TOUCH and finding.path not in recoverable_paths:
                recoverable += finding.recoverable_bytes
                recoverable_paths.add(finding.path)
            if finding.risk_level == RiskLevel.SAFE_TO_REGENERATE:
                dev_cache += finding.size_bytes
            if finding.category == "duplicate_file":
                duplicate += finding.size_bytes
        projects = self.latest_projects()
        return {
            "recoverable": recoverable,
            "finding_count": len(findings),
            "dev_cache": dev_cache,
            "duplicate": duplicate,
            "largest_project": projects[0] if projects else None,
        }

    def save_operation(self, manifest: dict) -> None:
        self.connection.execute(
            "insert or replace into operations(id, created_at, payload, manifest_path) values (?, ?, ?, ?)",
            (manifest["operation_id"], time.time(), json.dumps(_json_ready(manifest)), manifest.get("manifest_path")),
        )
        self.connection.commit()

    def operations(self) -> list[dict]:
        rows = self.connection.execute("select payload from operations order by created_at desc").fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def close(self) -> None:
        self.connection.close()


def _json_ready(value):
    if isinstance(value, RiskLevel):
        return value.value
    if isinstance(value, dict):
        return {k: _json_ready(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_ready(v) for v in value]
    return value


def _finding_from_json(payload: dict) -> Finding:
    payload["risk_level"] = RiskLevel(payload["risk_level"])
    payload.setdefault("tags", [payload.get("category", "other")])
    payload.setdefault("reasons", [payload.get("reason", "")])
    payload.setdefault("recommendations", [payload.get("recommended_action", "")])
    payload.setdefault("canonical_path", payload.get("path", ""))
    return Finding(**payload)
