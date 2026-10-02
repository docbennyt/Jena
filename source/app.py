from __future__ import annotations

import argparse
import json
from pathlib import Path
import traceback

from core.compression import ArchiveFormat
from core.project_library import archive_project
from selftest import (
    _make_large_project_library,
    run_project_registry_test,
    run_reliability_test,
    run_self_test,
    verify_project_registry_persistence,
    verify_self_test_persistence,
)
from ui.main_window import StoragePilotApp


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", type=Path, help="Run disposable v0.3.0 integration fixture and write JSON evidence.")
    parser.add_argument("--reliability-test", type=Path, help="Run disposable v0.3.1 reliability fixture and write JSON evidence.")
    parser.add_argument("--project-registry-test", type=Path, help="Run disposable v0.4.0 Project Registry fixture and write JSON evidence.")
    parser.add_argument("--ui-responsiveness-test", type=Path, help="Run a disposable Tk responsiveness check and write JSON evidence.")
    parser.add_argument("--verify-persistence", nargs=2, metavar=("FIXTURE_ROOT", "OUTPUT_JSON"), help="Verify an existing self-test fixture from a separate process.")
    parser.add_argument("--verify-project-registry-persistence", nargs=2, metavar=("FIXTURE_ROOT", "OUTPUT_JSON"), help="Verify Project Registry state from a separate process.")
    args = parser.parse_args()
    if args.self_test:
        _write_cli_result(args.self_test, lambda: run_self_test(args.self_test))
        return
    if args.reliability_test:
        _write_cli_result(args.reliability_test, lambda: run_reliability_test(args.reliability_test))
        return
    if args.project_registry_test:
        _write_cli_result(args.project_registry_test, lambda: run_project_registry_test(args.project_registry_test))
        return
    if args.ui_responsiveness_test:
        run_ui_responsiveness_test(args.ui_responsiveness_test)
        return
    if args.verify_persistence:
        output = Path(args.verify_persistence[1])
        _write_cli_result(output, lambda: verify_self_test_persistence(Path(args.verify_persistence[0]), output))
        return
    if args.verify_project_registry_persistence:
        output = Path(args.verify_project_registry_persistence[1])
        _write_cli_result(output, lambda: verify_project_registry_persistence(Path(args.verify_project_registry_persistence[0]), output))
        return
    StoragePilotApp().run()


def _write_cli_result(output_path: Path, runner) -> None:
    try:
        runner()
    except Exception as exc:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps({"error": str(exc), "traceback": traceback.format_exc()}, indent=2),
            encoding="utf-8",
        )
        raise


def run_ui_responsiveness_test(output_path: Path) -> None:
    root = output_path.parent / "jena-ui-responsiveness-fixture"
    library = root / "TestProjects"
    if root.exists():
        import shutil

        shutil.rmtree(root)
    _make_large_project_library(library, 20000)
    preview_project = _make_large_project_library_for_preview(root / "PreviewSource")
    preview_archive = archive_project(
        preview_project,
        root / "PreviewArchives",
        root / "PreviewData",
        archive_format=ArchiveFormat.SEVEN_ZIP,
    )
    app = StoragePilotApp()
    app.settings.set("project_library_root", str(library))
    app.project_library_var.set(str(library))
    app.show_page("projects")
    app.refresh_project_library()
    app.start_preview(Path(preview_archive.archive_path), target="downloads")
    state = {"ticks": 0, "page_changes": 0, "started": __import__("time").time(), "done": False}
    pages = ["dashboard", "downloads", "projects", "settings", "projects"]

    def tick() -> None:
        import time

        state["ticks"] += 1
        try:
            app.show_page(pages[state["ticks"] % len(pages)])
            state["page_changes"] += 1
        except Exception:
            pass
        task_states = [task.state.value for task in app.task_manager.tasks.values() if task.name.startswith("projects.")]
        finished = task_states and all(value in {"COMPLETED", "CANCELLED", "FAILED"} for value in task_states)
        archive_tree_nodes = _tree_node_count(app.archive_browser)
        if finished and len(app.project_records) >= 4 and archive_tree_nodes > 0:
            state["done"] = True
        if state["done"] or time.time() - state["started"] > 30:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(
                    {
                        "ticks": state["ticks"],
                        "page_changes": state["page_changes"],
                        "project_count": len(app.project_records),
                        "task_states": task_states,
                        "archive_tree_nodes": archive_tree_nodes,
                        "archive_container_navigable": archive_tree_nodes > 0,
                        "responsive": state["ticks"] >= 10 and state["page_changes"] >= 5 and len(app.project_records) >= 4 and archive_tree_nodes > 0,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            app.on_close()
            return
        app.root.after(50, tick)

    app.root.after(50, tick)
    app.run()


def _make_large_project_library_for_preview(root: Path) -> Path:
    project = root / "Archive Preview"
    for relative, content in {
        "package.json": "{}",
        "src/app.ts": "export const preview = 'Jena';",
        "docs/README.md": "# Archive container",
    }.items():
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return project


def _tree_node_count(tree, parent: str = "") -> int:
    children = tree.get_children(parent)
    return len(children) + sum(_tree_node_count(tree, child) for child in children)


if __name__ == "__main__":
    main()
