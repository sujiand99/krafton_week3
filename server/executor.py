"""Single-worker command execution for Redis-like serialized processing."""

from __future__ import annotations

from dataclasses import dataclass, field
from queue import Queue
import threading
from typing import Any, Callable

from commands.handler import CommandResult, StorageProtocol, handle_command

_UNSET = object()


@dataclass(slots=True)
class CommandTask:
    command: list[str]
    result: Any = _UNSET
    error: Exception | None = None
    done: threading.Event = field(default_factory=threading.Event)


class SerialCommandExecutor:
    def __init__(
        self,
        storage: StorageProtocol,
        command_handler: Callable[[list[str], StorageProtocol], CommandResult] = handle_command,
    ) -> None:
        self._storage = storage
        self._command_handler = command_handler
        self._queue: Queue[CommandTask | None] = Queue()
        self._worker_thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._worker_thread = threading.Thread(target=self._run, daemon=True)
        self._worker_thread.start()

    def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        self._queue.put(None)
        if self._worker_thread is not None:
            self._worker_thread.join(timeout=1)
            self._worker_thread = None

    def execute(self, command: list[str], timeout: float | None = None) -> CommandResult:
        if not self._running:
            raise RuntimeError("command executor is not running")

        task = CommandTask(command=command)
        self._queue.put(task)

        if not task.done.wait(timeout):
            raise TimeoutError("command execution timed out")

        if task.error is not None:
            raise task.error
        if task.result is _UNSET:
            raise RuntimeError("command execution did not produce a result")

        return task.result

    def _run(self) -> None:
        while True:
            task = self._queue.get()
            if task is None:
                return

            try:
                task.result = self._command_handler(task.command, self._storage)
            except Exception as exc:
                task.error = exc
            finally:
                task.done.set()
