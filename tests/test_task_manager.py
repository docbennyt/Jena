import queue
import threading

from core.tasks import TaskEvent, TaskManager, TaskState


def test_task_manager_runs_work_off_calling_thread_and_reports_events():
    events: queue.Queue = queue.Queue()
    manager = TaskManager(events, max_workers=1)
    calling_thread = threading.get_ident()

    def worker(token, progress):
        progress({"step": "started"})
        return threading.get_ident()

    task = manager.submit("fixture", worker)
    completed = None
    seen_progress = False
    for _ in range(20):
        event: TaskEvent = events.get(timeout=2)
        if event.kind == "progress":
            seen_progress = True
        if event.task_id == task.id and event.state == TaskState.COMPLETED:
            completed = event.payload
            break

    assert seen_progress
    assert completed is not None
    assert completed != calling_thread
