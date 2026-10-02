from __future__ import annotations

import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class TaskState(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise TaskCancelled()


class TaskCancelled(Exception):
    pass


@dataclass
class Task:
    name: str
    fn: Callable[..., Any]
    args: tuple = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    state: TaskState = TaskState.QUEUED
    token: CancellationToken = field(default_factory=CancellationToken)
    created_at: float = field(default_factory=time.time)


@dataclass
class TaskEvent:
    task_id: str
    name: str
    state: TaskState
    kind: str
    payload: Any = None
    error: str = ""


class TaskManager:
    def __init__(self, event_queue: queue.Queue, max_workers: int = 3) -> None:
        self.event_queue = event_queue
        self.max_workers = max(1, max_workers)
        self.tasks: dict[str, Task] = {}
        self._lock = threading.Lock()
        self._semaphore = threading.Semaphore(self.max_workers)

    def submit(self, name: str, fn: Callable[..., Any], *args, **kwargs) -> Task:
        task = Task(name=name, fn=fn, args=args, kwargs=kwargs)
        with self._lock:
            self.tasks[task.id] = task
        self._emit(task, "queued")
        thread = threading.Thread(target=self._run, args=(task,), daemon=True)
        thread.start()
        return task

    def cancel(self, task_id: str) -> None:
        task = self.tasks.get(task_id)
        if not task:
            return
        task.token.cancel()
        if task.state in {TaskState.QUEUED, TaskState.RUNNING}:
            task.state = TaskState.CANCELLING
            self._emit(task, "state")

    def cancel_all(self) -> None:
        for task_id in list(self.tasks):
            self.cancel(task_id)

    def progress(self, task: Task, payload: Any) -> None:
        self._emit(task, "progress", payload)

    def _run(self, task: Task) -> None:
        with self._semaphore:
            if task.token.cancelled:
                task.state = TaskState.CANCELLED
                self._emit(task, "cancelled")
                return
            task.state = TaskState.RUNNING
            self._emit(task, "state")
            try:
                result = task.fn(task.token, lambda payload: self.progress(task, payload), *task.args, **task.kwargs)
            except TaskCancelled:
                task.state = TaskState.CANCELLED
                self._emit(task, "cancelled")
            except Exception as exc:
                task.state = TaskState.FAILED
                self._emit(task, "failed", error=str(exc))
            else:
                if task.token.cancelled:
                    task.state = TaskState.CANCELLED
                    self._emit(task, "cancelled")
                else:
                    task.state = TaskState.COMPLETED
                    self._emit(task, "completed", result)

    def _emit(self, task: Task, kind: str, payload: Any = None, error: str = "") -> None:
        self.event_queue.put(TaskEvent(task.id, task.name, task.state, kind, payload, error))
